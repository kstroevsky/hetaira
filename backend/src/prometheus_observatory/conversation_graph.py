from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .codebooks import release_identity
from .config import get_settings
from .model_gateway import (
    EvidenceItem,
    LocalOpenAICompatibleEmbeddingAdapter,
    ModelPolicy,
    ModelRouter,
    TaskCapabilityRegistry,
)
from .models import (
    AnalysisRun,
    AnalysisTask,
    Annotation,
    AnnotationReview,
    AnnotationSet,
    Corpus,
    CorpusSnapshot,
    DependencyFingerprint,
    DerivationEdge,
    DiscourseRelation,
    GoldJudgmentAnnotation,
    GoldTaskJudgment,
    Message,
    MessageFeature,
    MessageRevision,
    Participant,
    ResponseRelation,
    SnapshotMessageRevision,
    new_id,
)
from .ontology import PrivacyPolicy
from .text import normalize_text
from .workspace import sender_display_name

ANALYSIS_VERSION = "conversation-graph-rules-ru@0.1.0"
LEXICAL_METHOD = "lexical-cosine-ru@0.1.0"
ENCODER_METHOD = "multilingual-e5-cosine@0.1.0"
TOKEN_PATTERN = re.compile(r"[\w-]+", re.UNICODE)
DISCOURSE_PATTERNS: dict[str, re.Pattern[str]] = {
    "ACKNOWLEDGES": re.compile(r"\b(понял[аи]?|ясно|спасибо|ок(?:ей)?|принято)\b", re.I),
    "CORRECTS": re.compile(r"\b(нет[, :]|не так|поправ(?:ка|лю)|точнее говоря)\b", re.I),
    "CONTRASTS": re.compile(r"\b(но|однако|зато|впрочем)\b", re.I),
    "CLARIFIES": re.compile(r"\b(точнее|то есть|имею в виду|уточн(?:ю|ение))\b", re.I),
    "ACCEPTS": re.compile(r"\b(соглас(?:ен|на|ны)|принимаю|давайте|давай|поддерживаю)\b", re.I),
    "REJECTS": re.compile(r"\b(не соглас(?:ен|на|ны)|не подходит|отклон(?:яю|яем)|против)\b", re.I),
}


@dataclass(frozen=True, slots=True)
class MessageRow:
    message_id: str
    revision_id: str
    conversation_id: str
    external_id: str
    reply_to_external_id: str | None
    sender_id: str | None
    sent_at: datetime
    text: str
    text_hash: str

    def checkpoint(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "revision_id": self.revision_id,
            "conversation_id": self.conversation_id,
            "external_id": self.external_id,
            "reply_to_external_id": self.reply_to_external_id,
            "sender_id": self.sender_id,
            "sent_at": self.sent_at.isoformat(),
            "text": self.text,
            "text_hash": self.text_hash,
        }

    @classmethod
    def from_checkpoint(cls, value: dict[str, Any]) -> MessageRow:
        return cls(
            message_id=value["message_id"],
            revision_id=value["revision_id"],
            conversation_id=value["conversation_id"],
            external_id=value["external_id"],
            reply_to_external_id=value.get("reply_to_external_id"),
            sender_id=value.get("sender_id"),
            sent_at=datetime.fromisoformat(value["sent_at"]),
            text=value["text"],
            text_hash=value["text_hash"],
        )


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    row: MessageRow
    score: float
    source_native: bool


class ConversationGraphService:
    """Corpus-wide provisional response and discourse graph analysis."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()

    def create(
        self,
        corpus_id: str,
        *,
        include_encoder: bool = True,
        candidate_limit: int | None = None,
        result_limit: int | None = None,
        execute: bool = True,
    ) -> AnalysisRun:
        corpus = self.session.get(Corpus, corpus_id)
        if corpus is None:
            raise LookupError("corpus not found")
        snapshot = self._latest_snapshot(corpus_id)
        candidate_limit = candidate_limit or self.settings.conversation_graph_candidate_limit
        result_limit = result_limit or self.settings.conversation_graph_result_limit
        if not 1 <= result_limit <= candidate_limit <= 200:
            raise ValueError(
                "result_limit must be positive and no greater than candidate_limit <= 200"
            )
        codebook_release, codebook_hash = release_identity(
            self.session, "conversation-graph-ru", "0.1.0"
        )
        configuration = {
            "analysis_version": ANALYSIS_VERSION,
            "codebook_release": codebook_release,
            "codebook_artifact_hash": codebook_hash,
            "candidate_limit": candidate_limit,
            "result_limit": result_limit,
            "gap_hours": self.settings.default_session_gap_hours,
            "batch_size": self.settings.conversation_graph_batch_size,
            "include_encoder": include_encoder,
            "encoder": {
                "provider": "local-openai-compatible-embeddings",
                "base_url": self.settings.local_embedding_base_url,
                "model": self.settings.local_embedding_model,
                "model_revision": self.settings.local_embedding_revision,
                "input_prefix": "query: ",
                "max_tokens": 512,
                "pooling": "mean",
                "normalized": True,
            },
            "score_semantics": "uncalibrated_similarity",
            "accepted_edges": False,
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                {"snapshot_id": snapshot.id, **configuration},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        existing = next(
            (
                candidate
                for candidate in self.session.scalars(
                    select(AnalysisRun).where(
                        AnalysisRun.snapshot_id == snapshot.id,
                        AnalysisRun.run_type == "conversation-graph",
                    )
                )
                if candidate.configuration.get("fingerprint") == fingerprint
            ),
            None,
        )
        if existing is not None:
            if execute and existing.status in {"pending", "failed", "cancelled"}:
                return self.resume(existing.id)
            return existing
        run = AnalysisRun(
            id=new_id(),
            snapshot_id=snapshot.id,
            run_type="conversation-graph",
            status="pending",
            progress=0,
            configuration={**configuration, "fingerprint": fingerprint},
        )
        self.session.add(run)
        self.session.flush()
        for index, task_key in enumerate(
            ("candidate_generation", "lexical_scoring", "discourse_proposals", "encoder_challenger")
        ):
            task = AnalysisTask(
                id=new_id(),
                run_id=run.id,
                task_key=task_key,
                status="pending",
                progress=0,
                idempotency_key=f"{run.id}:{task_key}",
                checkpoint={} if index else {"offset": 0, "history": []},
            )
            self.session.add(task)
            self.session.flush()
            self.session.add(
                DependencyFingerprint(
                    id=new_id(),
                    task_id=task.id,
                    dependency_type="conversation_graph_configuration",
                    dependency_key=task_key,
                    fingerprint=fingerprint,
                )
            )
        self.session.commit()
        return self.execute(run.id) if execute else run

    def execute(self, run_id: str) -> AnalysisRun:
        run = self._run(run_id)
        if run.status == "completed":
            return run
        if run.status == "cancelled":
            return run
        run.status = "running"
        run.started_at = run.started_at or datetime.now(UTC)
        run.error = None
        self.session.commit()
        try:
            self._run_baseline(run)
            if self._is_cancelled(run.id):
                return self._run(run.id)
            try:
                self._run_encoder(run)
            except Exception as encoder_error:
                self.session.rollback()
                run = self._run(run.id)
                encoder_task = self._tasks(run.id)["encoder_challenger"]
                encoder_task.status = "failed"
                encoder_task.error = str(encoder_error)
                run.configuration = {
                    **run.configuration,
                    "encoder_warning": str(encoder_error),
                }
                self.session.commit()
            run = self._run(run.id)
            if run.status != "cancelled":
                run.status = "completed"
                run.progress = 1
                run.completed_at = datetime.now(UTC)
                self.session.commit()
            return run
        except Exception as error:
            self.session.rollback()
            run = self._run(run_id)
            run.status = "failed"
            run.error = str(error)
            self.session.commit()
            raise

    def cancel(self, run_id: str) -> AnalysisRun:
        run = self._run(run_id)
        if run.status != "completed":
            run.status = "cancelled"
            run.completed_at = datetime.now(UTC)
            self.session.commit()
        return run

    def resume(self, run_id: str) -> AnalysisRun:
        run = self._run(run_id)
        if run.status == "completed":
            return run
        expected = run.configuration.get("fingerprint")
        fingerprints = list(
            self.session.scalars(
                select(DependencyFingerprint.fingerprint)
                .join(AnalysisTask, AnalysisTask.id == DependencyFingerprint.task_id)
                .where(AnalysisTask.run_id == run.id)
            )
        )
        if not fingerprints or any(item != expected for item in fingerprints):
            raise ValueError("analysis dependency fingerprint changed; create a new run")
        run.status = "pending"
        run.completed_at = None
        self.session.commit()
        return self.execute(run.id)

    def run_payload(self, run_id: str) -> dict[str, Any]:
        run = self._run(run_id)
        tasks = list(
            self.session.scalars(
                select(AnalysisTask)
                .where(AnalysisTask.run_id == run.id)
                .order_by(AnalysisTask.created_at, AnalysisTask.task_key)
            )
        )
        return {
            "id": run.id,
            "snapshot_id": run.snapshot_id,
            "run_type": run.run_type,
            "status": run.status,
            "progress": run.progress,
            "configuration": run.configuration,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "error": run.error,
            "tasks": [
                {
                    "id": task.id,
                    "task_key": task.task_key,
                    "status": task.status,
                    "progress": task.progress,
                    "checkpoint": task.checkpoint,
                    "error": task.error,
                }
                for task in tasks
            ],
        }

    def graph(
        self,
        corpus_id: str,
        *,
        run_id: str | None = None,
        message_id: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        corpus = self.session.get(Corpus, corpus_id)
        if corpus is None:
            raise LookupError("corpus not found")
        run = self._graph_run(corpus_id, run_id)
        limit = min(max(limit, 1), 250)
        response_query = select(ResponseRelation).where(ResponseRelation.run_id == run.id)
        discourse_query = select(DiscourseRelation).where(DiscourseRelation.run_id == run.id)
        if message_id:
            response_query = response_query.where(
                or_(
                    ResponseRelation.source_message_id == message_id,
                    ResponseRelation.target_message_id == message_id,
                )
            )
            discourse_query = discourse_query.where(
                or_(
                    DiscourseRelation.source_message_id == message_id,
                    DiscourseRelation.target_message_id == message_id,
                )
            )
        responses = list(
            self.session.scalars(
                response_query.order_by(
                    ResponseRelation.source_message_id,
                    ResponseRelation.scoring_method,
                    ResponseRelation.rank,
                )
                .offset(offset)
                .limit(limit)
            )
        )
        discourse = list(
            self.session.scalars(
                discourse_query.order_by(
                    DiscourseRelation.source_message_id,
                    DiscourseRelation.relation_type,
                )
                .offset(offset)
                .limit(limit)
            )
        )
        explicit = self._explicit_edges(run.snapshot_id, message_id, offset, limit)
        message_ids = {edge.source_message_id for edge in [*responses, *discourse]} | {
            edge.target_message_id for edge in [*responses, *discourse]
        }
        message_ids |= {edge["source_message_id"] for edge in explicit}
        message_ids |= {edge["target_message_id"] for edge in explicit}
        messages = self._message_payloads(run.snapshot_id, message_ids)
        reviews = self._review_map(
            [edge.annotation_id for edge in responses if edge.annotation_id]
            + [edge.annotation_id for edge in discourse]
        )
        return {
            "run": self.run_payload(run.id),
            "messages": messages,
            "explicit_replies": explicit,
            "response_candidates": [
                {
                    "id": edge.id,
                    "annotation_id": edge.annotation_id,
                    "source_message_id": edge.source_message_id,
                    "target_message_id": edge.target_message_id,
                    "source_revision_id": edge.source_revision_id,
                    "target_revision_id": edge.target_revision_id,
                    "method": edge.scoring_method,
                    "rank": edge.rank,
                    "raw_score": edge.confidence,
                    "score_semantics": "uncalibrated_similarity",
                    "status": edge.status,
                    "review": reviews.get(edge.annotation_id),
                }
                for edge in responses
            ],
            "discourse_relations": [
                {
                    "id": edge.id,
                    "annotation_id": edge.annotation_id,
                    "source_message_id": edge.source_message_id,
                    "target_message_id": edge.target_message_id,
                    "source_revision_id": edge.source_revision_id,
                    "target_revision_id": edge.target_revision_id,
                    "relation_type": edge.relation_type,
                    "method": edge.scoring_method,
                    "raw_score": edge.raw_score,
                    "status": edge.status,
                    "review": reviews.get(edge.annotation_id),
                }
                for edge in discourse
            ],
            "page": {"offset": offset, "limit": limit},
            "guardrail": (
                "All inferred links are provisional proposals. Raw similarity is not a "
                "probability, and an absent proposal is not a negative judgment."
            ),
        }

    def search_conversation_messages(
        self,
        corpus_id: str,
        conversation_id: str,
        *,
        query: str = "",
        limit: int = 100,
        before_message_id: str | None = None,
    ) -> list[dict[str, Any]]:
        snapshot = self._latest_snapshot(corpus_id)
        statement = (
            select(Message, MessageRevision, Participant)
            .join(SnapshotMessageRevision, SnapshotMessageRevision.message_id == Message.id)
            .join(MessageRevision, MessageRevision.id == SnapshotMessageRevision.revision_id)
            .outerjoin(Participant, Participant.id == Message.sender_id)
            .where(
                SnapshotMessageRevision.snapshot_id == snapshot.id,
                Message.conversation_id == conversation_id,
            )
            .order_by(Message.resolved_timestamp, Message.id)
        )
        if query.strip():
            statement = statement.where(MessageRevision.text.ilike(f"%{query.strip()}%"))
        if before_message_id:
            anchor = self.session.get(Message, before_message_id)
            if anchor is None or anchor.conversation_id != conversation_id:
                raise LookupError("anchor message not found in conversation")
            statement = statement.where(
                Message.id != anchor.id,
                Message.resolved_timestamp <= anchor.resolved_timestamp,
            )
        return [
            {
                "message_id": message.id,
                "revision_id": revision.id,
                "external_id": message.external_id,
                "sender_id": message.sender_id,
                "sender_name": sender_display_name(message, participant),
                "sent_at": message.sent_at,
                "text": revision.text,
                "text_hash": revision.text_hash,
            }
            for message, revision, participant in self.session.execute(
                statement.limit(min(max(limit, 1), 500))
            )
        ]

    def evaluate_reference(self, annotation_set_id: str, run_id: str) -> dict[str, Any]:
        annotation_set = self.session.get(AnnotationSet, annotation_set_id)
        if annotation_set is None:
            raise LookupError("annotation set not found")
        if annotation_set.sampling_spec.get("judgment_protocol") != "single_final_reference_v1":
            raise ValueError("annotation set is not a conversation graph reference")
        if annotation_set.status != "frozen":
            raise ValueError("conversation graph reference must be frozen before evaluation")
        run = self._run(run_id)
        if run.snapshot_id != annotation_set.snapshot_id:
            raise ValueError("analysis run and reference set must use the same snapshot")
        judgments = list(
            self.session.scalars(
                select(GoldTaskJudgment).where(
                    GoldTaskJudgment.annotation_set_id == annotation_set.id,
                    GoldTaskJudgment.slot == "FINAL",
                )
            )
        )
        links = (
            list(
                self.session.scalars(
                    select(GoldJudgmentAnnotation).where(
                        GoldJudgmentAnnotation.judgment_id.in_([item.id for item in judgments])
                    )
                )
            )
            if judgments
            else []
        )
        annotation_by_id = (
            {
                annotation.id: annotation
                for annotation in self.session.scalars(
                    select(Annotation).where(
                        Annotation.id.in_([link.annotation_id for link in links])
                    )
                )
            }
            if links
            else {}
        )
        judgment_by_id = {judgment.id: judgment for judgment in judgments}
        gold_reply: set[tuple[str, str]] = set()
        gold_discourse: set[tuple[str, str, str]] = set()
        for link in links:
            judgment = judgment_by_id[link.judgment_id]
            annotation = annotation_by_id.get(link.annotation_id)
            if annotation is None:
                continue
            if judgment.task == "reply_target":
                targets = annotation.value.get("target_message_ids") or [
                    annotation.value.get("target_message_id")
                ]
                gold_reply.update(
                    (annotation.object_id, target_id) for target_id in targets if target_id
                )
            elif judgment.task == "discourse_relation":
                gold_discourse.add(
                    (
                        annotation.value["source_message_id"],
                        annotation.value["target_message_id"],
                        annotation.value["relation_type"],
                    )
                )
        lexical_rows = list(
            self.session.scalars(
                select(ResponseRelation).where(
                    ResponseRelation.run_id == run.id,
                    ResponseRelation.scoring_method == LEXICAL_METHOD,
                )
            )
        )
        encoder_rows = list(
            self.session.scalars(
                select(ResponseRelation).where(
                    ResponseRelation.run_id == run.id,
                    ResponseRelation.scoring_method == ENCODER_METHOD,
                )
            )
        )
        predicted_discourse = {
            (row.source_message_id, row.target_message_id, row.relation_type)
            for row in self.session.scalars(
                select(DiscourseRelation).where(DiscourseRelation.run_id == run.id)
            )
        }
        units = {judgment.unit_id for judgment in judgments}
        statuses = Counter((judgment.task, judgment.status) for judgment in judgments)
        return {
            "schema": "hetaira.conversation-graph-evaluation.v1",
            "annotation_set_id": annotation_set.id,
            "run_id": run.id,
            "snapshot_id": run.snapshot_id,
            "reply_ranking": {
                LEXICAL_METHOD: self._ranking_metrics(gold_reply, lexical_rows, len(units)),
                ENCODER_METHOD: self._ranking_metrics(gold_reply, encoder_rows, len(units)),
                "top1_disagreement": self._top1_disagreement(lexical_rows, encoder_rows),
            },
            "discourse": self._set_metrics(gold_discourse, predicted_discourse),
            "reference_judgments": {
                "units": len(units),
                "reply_target_absent": statuses[("reply_target", "ABSENT")],
                "reply_target_abstain": statuses[("reply_target", "ABSTAIN")],
                "discourse_absent": statuses[("discourse_relation", "ABSENT")],
                "discourse_abstain": statuses[("discourse_relation", "ABSTAIN")],
            },
            "calibration": {
                "ece": None,
                "brier": None,
                "reason": "no calibrated probabilistic task model",
            },
            "status": "single_human_provisional",
        }

    @staticmethod
    def _ranking_metrics(
        gold: set[tuple[str, str]], rows: list[ResponseRelation], unit_count: int
    ) -> dict[str, Any]:
        rank_by_pair = {
            (row.source_message_id, row.target_message_id): row.rank or 0 for row in rows
        }
        hits = [rank_by_pair[pair] for pair in gold if pair in rank_by_pair]
        sources = {row.source_message_id for row in rows}
        return {
            "reference_targets": len(gold),
            "hits": len(hits),
            "candidate_recall": len(hits) / len(gold) if gold else None,
            "mean_reciprocal_rank": (
                sum(1 / rank for rank in hits if rank) / len(gold) if gold else None
            ),
            "coverage": len(sources) / unit_count if unit_count else None,
        }

    @staticmethod
    def _top1_disagreement(
        left: list[ResponseRelation], right: list[ResponseRelation]
    ) -> dict[str, Any]:
        left_top = {row.source_message_id: row.target_message_id for row in left if row.rank == 1}
        right_top = {row.source_message_id: row.target_message_id for row in right if row.rank == 1}
        common = set(left_top) & set(right_top)
        disagreements = sum(left_top[source] != right_top[source] for source in common)
        return {
            "comparable_sources": len(common),
            "disagreements": disagreements,
            "rate": disagreements / len(common) if common else None,
        }

    @staticmethod
    def _set_metrics(gold: set[Any], predicted: set[Any]) -> dict[str, Any]:
        summary = ConversationGraphService._basic_set_metrics(gold, predicted)
        labels = sorted({item[2] for item in gold | predicted})
        return {
            **summary,
            "by_label": {
                label: ConversationGraphService._basic_set_metrics(
                    {item for item in gold if item[2] == label},
                    {item for item in predicted if item[2] == label},
                )
                for label in labels
            },
        }

    @staticmethod
    def _basic_set_metrics(gold: set[Any], predicted: set[Any]) -> dict[str, Any]:
        true_positive = len(gold & predicted)
        precision = true_positive / len(predicted) if predicted else None
        recall = true_positive / len(gold) if gold else None
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision is not None and recall is not None and precision + recall
            else None
        )
        return {
            "reference_relations": len(gold),
            "predicted_relations": len(predicted),
            "true_positive": true_positive,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }

    def _run_baseline(self, run: AnalysisRun) -> None:
        tasks = self._tasks(run.id)
        candidate_task = tasks["candidate_generation"]
        lexical_task = tasks["lexical_scoring"]
        discourse_task = tasks["discourse_proposals"]
        if all(
            task.status == "completed" for task in (candidate_task, lexical_task, discourse_task)
        ):
            return
        for task in (candidate_task, lexical_task, discourse_task):
            task.status = "running"
            task.error = None
        self.session.commit()
        checkpoint = candidate_task.checkpoint or {"offset": 0, "history": []}
        offset = int(checkpoint.get("offset", 0))
        diagnostics = Counter(checkpoint.get("diagnostics", {}))
        history = deque(
            (MessageRow.from_checkpoint(value) for value in checkpoint.get("history", [])),
            maxlen=int(run.configuration["candidate_limit"]),
        )
        total = (
            self.session.scalar(
                select(func.count(SnapshotMessageRevision.id)).where(
                    SnapshotMessageRevision.snapshot_id == run.snapshot_id
                )
            )
            or 0
        )
        batch_size = int(run.configuration["batch_size"])
        while offset < total:
            if self._is_cancelled(run.id):
                return
            rows = self._rows(run.snapshot_id, offset, batch_size)
            if not rows:
                break
            for row in rows:
                while history and history[0].conversation_id != row.conversation_id:
                    history.popleft()
                horizon = row.sent_at - timedelta(hours=int(run.configuration["gap_hours"]))
                while history and history[0].sent_at < horizon:
                    history.popleft()
                candidates = list(history)
                explicit = self._explicit_target(run.snapshot_id, row)
                if not row.text.strip():
                    diagnostics["empty_source_messages"] += 1
                if row.reply_to_external_id and explicit is None:
                    diagnostics["missing_explicit_targets"] += 1
                if explicit is not None and explicit.sent_at < horizon:
                    diagnostics["explicit_targets_outside_horizon"] += 1
                if explicit is not None and all(
                    item.message_id != explicit.message_id for item in candidates
                ):
                    candidates.append(explicit)
                ranked = self._rank(row, candidates, int(run.configuration["result_limit"]))
                if ranked:
                    self._persist_response_candidates(run, row, ranked, LEXICAL_METHOD)
                    self._persist_discourse(run, row, ranked)
                if row.text.strip():
                    history.append(row)
            offset += len(rows)
            progress = offset / total if total else 1
            candidate_task.checkpoint = {
                "offset": offset,
                "history": [item.checkpoint() for item in history],
                "candidate_limit": run.configuration["candidate_limit"],
                "diagnostics": dict(diagnostics),
            }
            for task in (candidate_task, lexical_task, discourse_task):
                task.progress = progress
            run.progress = progress * 0.8
            self.session.commit()
        for task in (candidate_task, lexical_task, discourse_task):
            task.status = "completed"
            task.progress = 1
        self.session.commit()

    def _run_encoder(self, run: AnalysisRun) -> None:
        task = self._tasks(run.id)["encoder_challenger"]
        if task.status in {"completed", "unavailable", "disabled"}:
            return
        if not run.configuration.get("include_encoder"):
            task.status = "disabled"
            task.progress = 1
            self.session.commit()
            return
        base_url = self.settings.local_embedding_base_url
        if not base_url:
            task.status = "unavailable"
            task.progress = 1
            task.error = "PROMETHEUS_LOCAL_EMBEDDING_BASE_URL is not configured"
            self.session.commit()
            return
        if self.settings.local_embedding_revision == "unversioned":
            task.status = "unavailable"
            task.progress = 1
            task.error = "PROMETHEUS_LOCAL_EMBEDDING_REVISION must pin the model artifact"
            self.session.commit()
            return
        task.status = "running"
        self.session.commit()
        adapter = LocalOpenAICompatibleEmbeddingAdapter(
            base_url=base_url,
            model=self.settings.local_embedding_model,
            model_revision=self.settings.local_embedding_revision,
        )
        registry = TaskCapabilityRegistry()
        registry.register("conversation_graph_embeddings", minimum_context=1024)
        router = ModelRouter(self.session, registry)
        producer_hash = hashlib.sha256(
            f"{adapter.model}:{adapter.model_revision}:query-prefix:mean-normalized".encode()
        ).hexdigest()
        completed = int((task.checkpoint or {}).get("groups_completed", 0))
        last_source_id = (task.checkpoint or {}).get("last_source_message_id")
        total_groups = (
            self.session.scalar(
                select(func.count(func.distinct(ResponseRelation.source_message_id))).where(
                    ResponseRelation.run_id == run.id,
                    ResponseRelation.scoring_method == LEXICAL_METHOD,
                )
            )
            or 0
        )
        while True:
            source_statement = (
                select(ResponseRelation.source_message_id)
                .where(
                    ResponseRelation.run_id == run.id,
                    ResponseRelation.scoring_method == LEXICAL_METHOD,
                )
                .distinct()
                .order_by(ResponseRelation.source_message_id)
                .limit(int(run.configuration["batch_size"]))
            )
            if last_source_id:
                source_statement = source_statement.where(
                    ResponseRelation.source_message_id > last_source_id
                )
            source_ids = list(self.session.scalars(source_statement))
            if not source_ids:
                break
            for source_id in source_ids:
                if self._is_cancelled(run.id):
                    return
                group = list(
                    self.session.scalars(
                        select(ResponseRelation)
                        .where(
                            ResponseRelation.run_id == run.id,
                            ResponseRelation.scoring_method == LEXICAL_METHOD,
                            ResponseRelation.source_message_id == source_id,
                        )
                        .order_by(ResponseRelation.rank)
                    )
                )
                if not group:
                    continue
                completed += 1
                last_source_id = source_id
                self._encode_group(
                    run,
                    task,
                    group,
                    router,
                    adapter,
                    producer_hash,
                    completed,
                    total_groups,
                )
        task.status = "completed"
        task.progress = 1
        self.session.commit()

    def _encode_group(
        self,
        run: AnalysisRun,
        task: AnalysisTask,
        group: list[ResponseRelation],
        router: ModelRouter,
        adapter: LocalOpenAICompatibleEmbeddingAdapter,
        producer_hash: str,
        completed: int,
        total_groups: int,
    ) -> None:
        revision_ids = [group[0].source_revision_id] + [item.target_revision_id for item in group]
        revisions = {
            revision.id: revision
            for revision in self.session.scalars(
                select(MessageRevision).where(MessageRevision.id.in_(revision_ids))
            )
        }
        ordered = [revisions[item] for item in revision_ids if item in revisions]
        if len(ordered) != len(revision_ids):
            raise RuntimeError("candidate revision disappeared during encoder analysis")
        vectors = self._cached_or_embed(router, adapter, run, ordered, producer_hash)
        source_vector = vectors[ordered[0].id]
        ranked = sorted(
            (
                (
                    relation,
                    self._vector_cosine(source_vector, vectors[relation.target_revision_id]),
                )
                for relation in group
            ),
            key=lambda item: (-item[1], item[0].rank or 0, item[0].target_message_id),
        )
        source_revision = revisions[group[0].source_revision_id]
        annotation = Annotation(
            id=new_id(),
            snapshot_id=run.snapshot_id,
            run_id=run.id,
            object_type="message_pair_ranking",
            object_id=group[0].source_message_id,
            kind="responds_to_candidates",
            value={
                "relation_type": "RESPONDS_TO",
                "method": ENCODER_METHOD,
                "source_message_id": group[0].source_message_id,
                "score_semantics": "uncalibrated_similarity",
                "accepted_edge": False,
            },
            evidence=[self._evidence(group[0].source_message_id, source_revision)]
            + [
                self._evidence(relation.target_message_id, revisions[relation.target_revision_id])
                for relation in group
            ],
            status="provisional",
            raw_confidence=None,
            calibrated_confidence=None,
            alternatives=[
                {
                    "value": {
                        "target_message_id": relation.target_message_id,
                        "target_revision_id": relation.target_revision_id,
                        "raw_score": score,
                        "rank": rank,
                        "target_evidence": self._evidence(
                            relation.target_message_id,
                            revisions[relation.target_revision_id],
                        ),
                    }
                }
                for rank, (relation, score) in enumerate(ranked, start=1)
            ],
            provenance=self._provenance(
                run,
                ENCODER_METHOD,
                model=adapter.model,
                model_revision=adapter.model_revision,
            ),
        )
        self.session.add(annotation)
        self.session.flush()
        self.session.add_all(
            DerivationEdge(
                id=new_id(),
                source_type="message_revision",
                source_id=revision_id,
                target_type="annotation",
                target_id=annotation.id,
                relation=(
                    "PROPOSES_RESPONSE_CANDIDATES"
                    if revision_id == group[0].source_revision_id
                    else "USES_CANDIDATE_TARGET"
                ),
                run_id=run.id,
            )
            for revision_id in revision_ids
        )
        for rank, (relation, score) in enumerate(ranked, start=1):
            self.session.add(
                ResponseRelation(
                    id=new_id(),
                    snapshot_id=run.snapshot_id,
                    run_id=run.id,
                    source_message_id=relation.source_message_id,
                    target_message_id=relation.target_message_id,
                    source_revision_id=relation.source_revision_id,
                    target_revision_id=relation.target_revision_id,
                    relation_type="RESPONDS_TO",
                    annotation_id=annotation.id,
                    confidence=score,
                    explicit=False,
                    scoring_method=ENCODER_METHOD,
                    rank=rank,
                    status="provisional",
                )
            )
        task.checkpoint = {
            "groups_completed": completed,
            "groups_total": total_groups,
            "last_source_message_id": group[0].source_message_id,
        }
        task.progress = completed / total_groups if total_groups else 1
        run.progress = 0.8 + task.progress * 0.2
        self.session.commit()

    def _cached_or_embed(
        self,
        router: ModelRouter,
        adapter: LocalOpenAICompatibleEmbeddingAdapter,
        run: AnalysisRun,
        revisions: list[MessageRevision],
        producer_hash: str,
    ) -> dict[str, list[float]]:
        existing = {
            feature.revision_id: feature
            for feature in self.session.scalars(
                select(MessageFeature).where(
                    MessageFeature.snapshot_id == run.snapshot_id,
                    MessageFeature.revision_id.in_([item.id for item in revisions]),
                    MessageFeature.feature_type == "sentence_embedding",
                    MessageFeature.producer_hash == producer_hash,
                )
            )
        }
        missing = [item for item in revisions if item.id not in existing]
        if missing:
            result = router.embed(
                corpus_id=self._snapshot(run.snapshot_id).corpus_id,
                run_id=run.id,
                task="conversation_graph_embeddings",
                adapter=adapter,
                items=[
                    EvidenceItem(evidence_id=item.id, text=f"query: {item.text}")
                    for item in missing
                ],
                policy=ModelPolicy(
                    privacy_policy=PrivacyPolicy.LOCAL_ONLY,
                    max_cost=0,
                    max_input_tokens=8192,
                    preferred_language="ru",
                    redact_pii=False,
                ),
                reason="local uncalibrated conversation-graph similarity",
            )
            message_ids = {
                revision_id: message_id
                for revision_id, message_id in self.session.execute(
                    select(MessageRevision.id, MessageRevision.message_id).where(
                        MessageRevision.id.in_([item.id for item in missing])
                    )
                )
            }
            for index, (revision, vector) in enumerate(zip(missing, result.vectors, strict=True)):
                feature = MessageFeature(
                    id=new_id(),
                    snapshot_id=run.snapshot_id,
                    run_id=run.id,
                    message_id=message_ids[revision.id],
                    revision_id=revision.id,
                    feature_type="sentence_embedding",
                    producer_hash=producer_hash,
                    dimensions=len(vector),
                    values=vector,
                    truncated=result.truncated[index] if result.truncated else False,
                )
                self.session.add(feature)
                existing[revision.id] = feature
            self.session.flush()
        return {revision_id: feature.values for revision_id, feature in existing.items()}

    def _persist_response_candidates(
        self,
        run: AnalysisRun,
        source: MessageRow,
        ranked: list[RankedCandidate],
        method: str,
    ) -> None:
        annotation = Annotation(
            id=new_id(),
            snapshot_id=run.snapshot_id,
            run_id=run.id,
            object_type="message_pair_ranking",
            object_id=source.message_id,
            kind="responds_to_candidates",
            value={
                "relation_type": "RESPONDS_TO",
                "method": method,
                "source_message_id": source.message_id,
                "score_semantics": "uncalibrated_similarity",
                "accepted_edge": False,
            },
            evidence=[self._row_evidence(source)]
            + [self._row_evidence(candidate.row) for candidate in ranked],
            status="provisional",
            raw_confidence=None,
            calibrated_confidence=None,
            alternatives=[
                {
                    "value": {
                        "target_message_id": candidate.row.message_id,
                        "target_revision_id": candidate.row.revision_id,
                        "raw_score": candidate.score,
                        "rank": rank,
                        "source_native": candidate.source_native,
                        "target_evidence": self._row_evidence(candidate.row),
                    }
                }
                for rank, candidate in enumerate(ranked, start=1)
            ],
            provenance=self._provenance(run, method),
        )
        self.session.add(annotation)
        self.session.flush()
        self.session.add_all(
            ResponseRelation(
                id=new_id(),
                snapshot_id=run.snapshot_id,
                run_id=run.id,
                source_message_id=source.message_id,
                target_message_id=candidate.row.message_id,
                source_revision_id=source.revision_id,
                target_revision_id=candidate.row.revision_id,
                relation_type="RESPONDS_TO",
                annotation_id=annotation.id,
                confidence=candidate.score,
                explicit=False,
                scoring_method=method,
                rank=rank,
                status="provisional",
            )
            for rank, candidate in enumerate(ranked, start=1)
        )
        self._derive(
            source,
            annotation.id,
            run.id,
            "PROPOSES_RESPONSE_CANDIDATES",
            targets=[candidate.row for candidate in ranked],
        )

    def _persist_discourse(
        self,
        run: AnalysisRun,
        source: MessageRow,
        ranked: list[RankedCandidate],
    ) -> None:
        for candidate in ranked:
            for relation_type in self._discourse_labels(
                source.text, candidate.row.text, candidate.score
            ):
                annotation = Annotation(
                    id=new_id(),
                    snapshot_id=run.snapshot_id,
                    run_id=run.id,
                    object_type="message_pair",
                    object_id=source.message_id,
                    kind="discourse_relation",
                    value={
                        "relation_type": relation_type,
                        "source_message_id": source.message_id,
                        "target_message_id": candidate.row.message_id,
                        "method": ANALYSIS_VERSION,
                        "accepted_edge": False,
                    },
                    evidence=[self._row_evidence(source), self._row_evidence(candidate.row)],
                    status="provisional",
                    raw_confidence=None,
                    calibrated_confidence=None,
                    alternatives=[],
                    provenance=self._provenance(run, ANALYSIS_VERSION),
                )
                self.session.add(annotation)
                self.session.flush()
                relation = DiscourseRelation(
                    id=new_id(),
                    snapshot_id=run.snapshot_id,
                    run_id=run.id,
                    source_message_id=source.message_id,
                    target_message_id=candidate.row.message_id,
                    source_revision_id=source.revision_id,
                    target_revision_id=candidate.row.revision_id,
                    relation_type=relation_type,
                    annotation_id=annotation.id,
                    scoring_method=ANALYSIS_VERSION,
                    raw_score=candidate.score,
                    status="provisional",
                )
                self.session.add(relation)
                self._derive(
                    source,
                    annotation.id,
                    run.id,
                    "PROPOSES_DISCOURSE_RELATION",
                    targets=[candidate.row],
                )

    @staticmethod
    def _rank(
        source: MessageRow, candidates: list[MessageRow], result_limit: int
    ) -> list[RankedCandidate]:
        source_terms = ConversationGraphService._term_counts(source.text)
        ranked = [
            RankedCandidate(
                row=candidate,
                score=ConversationGraphService._sparse_cosine(
                    source_terms, ConversationGraphService._term_counts(candidate.text)
                ),
                source_native=candidate.external_id == source.reply_to_external_id,
            )
            for candidate in candidates
            if candidate.text.strip() and candidate.message_id != source.message_id
        ]
        ranked.sort(
            key=lambda item: (-item.score, -item.row.sent_at.timestamp(), item.row.message_id)
        )
        selected = ranked[:result_limit]
        explicit = next((item for item in ranked if item.source_native), None)
        if explicit is not None and explicit not in selected:
            selected = [*selected[: max(0, result_limit - 1)], explicit]
        return selected

    @staticmethod
    def _term_counts(value: str) -> Counter[str]:
        return Counter(
            token.casefold()
            for token in TOKEN_PATTERN.findall(normalize_text(value))
            if len(token) > 1
        )

    @staticmethod
    def _sparse_cosine(left: Counter[str], right: Counter[str]) -> float:
        if not left or not right:
            return 0
        numerator = sum(count * right.get(term, 0) for term, count in left.items())
        denominator = math.sqrt(sum(value * value for value in left.values())) * math.sqrt(
            sum(value * value for value in right.values())
        )
        return numerator / denominator if denominator else 0

    @staticmethod
    def _vector_cosine(left: list[float], right: list[float]) -> float:
        if len(left) != len(right) or not left:
            raise ValueError("embedding dimensions do not match")
        denominator = math.sqrt(sum(item * item for item in left)) * math.sqrt(
            sum(item * item for item in right)
        )
        return (
            sum(a * b for a, b in zip(left, right, strict=True)) / denominator if denominator else 0
        )

    @staticmethod
    def _discourse_labels(source: str, target: str, lexical_score: float) -> list[str]:
        labels = [name for name, pattern in DISCOURSE_PATTERNS.items() if pattern.search(source)]
        if "?" in target and "?" not in source and len(source.split()) >= 2:
            labels.append("ANSWERS")
        if lexical_score > 0 and len(source.split()) > len(target.split()):
            labels.append("ELABORATES")
        return sorted(set(labels))

    def _rows(self, snapshot_id: str, offset: int, limit: int) -> list[MessageRow]:
        return [
            MessageRow(
                message_id=message.id,
                revision_id=revision.id,
                conversation_id=message.conversation_id,
                external_id=message.external_id,
                reply_to_external_id=message.reply_to_external_id,
                sender_id=message.sender_id,
                sent_at=message.resolved_timestamp,
                text=revision.text,
                text_hash=revision.text_hash,
            )
            for message, revision in self.session.execute(
                select(Message, MessageRevision)
                .join(SnapshotMessageRevision, SnapshotMessageRevision.message_id == Message.id)
                .join(MessageRevision, MessageRevision.id == SnapshotMessageRevision.revision_id)
                .where(SnapshotMessageRevision.snapshot_id == snapshot_id)
                .order_by(Message.conversation_id, Message.resolved_timestamp, Message.id)
                .offset(offset)
                .limit(limit)
            )
        ]

    def _explicit_target(self, snapshot_id: str, source: MessageRow) -> MessageRow | None:
        if not source.reply_to_external_id:
            return None
        row = self.session.execute(
            select(Message, MessageRevision)
            .join(SnapshotMessageRevision, SnapshotMessageRevision.message_id == Message.id)
            .join(MessageRevision, MessageRevision.id == SnapshotMessageRevision.revision_id)
            .where(
                SnapshotMessageRevision.snapshot_id == snapshot_id,
                Message.conversation_id == source.conversation_id,
                Message.external_id == source.reply_to_external_id,
            )
        ).one_or_none()
        if row is None:
            return None
        message, revision = row
        return MessageRow(
            message_id=message.id,
            revision_id=revision.id,
            conversation_id=message.conversation_id,
            external_id=message.external_id,
            reply_to_external_id=message.reply_to_external_id,
            sender_id=message.sender_id,
            sent_at=message.resolved_timestamp,
            text=revision.text,
            text_hash=revision.text_hash,
        )

    def _explicit_edges(
        self, snapshot_id: str, message_id: str | None, offset: int, limit: int
    ) -> list[dict[str, Any]]:
        source = Message
        target = Message.__table__.alias("explicit_target")
        statement = (
            select(source.id, target.c.id, source.reply_to_external_id)
            .join(SnapshotMessageRevision, SnapshotMessageRevision.message_id == source.id)
            .join(
                target,
                (target.c.conversation_id == source.conversation_id)
                & (target.c.external_id == source.reply_to_external_id),
            )
            .where(
                SnapshotMessageRevision.snapshot_id == snapshot_id,
                source.reply_to_external_id.is_not(None),
            )
        )
        if message_id:
            statement = statement.where(or_(source.id == message_id, target.c.id == message_id))
        return [
            {
                "source_message_id": source_id,
                "target_message_id": target_id,
                "relation_type": "REPLIES_TO",
                "source_native": True,
                "confidence": 1,
            }
            for source_id, target_id, _external in self.session.execute(
                statement.order_by(source.id).offset(offset).limit(limit)
            )
        ]

    def _message_payloads(self, snapshot_id: str, message_ids: set[str]) -> list[dict[str, Any]]:
        if not message_ids:
            return []
        return [
            {
                "id": message.id,
                "conversation_id": message.conversation_id,
                "external_id": message.external_id,
                "revision_id": revision.id,
                "sender_id": message.sender_id,
                "sender_name": sender_display_name(message, participant),
                "sent_at": message.sent_at,
                "text": revision.text,
                "text_hash": revision.text_hash,
            }
            for message, revision, participant in self.session.execute(
                select(Message, MessageRevision, Participant)
                .join(SnapshotMessageRevision, SnapshotMessageRevision.message_id == Message.id)
                .join(MessageRevision, MessageRevision.id == SnapshotMessageRevision.revision_id)
                .outerjoin(Participant, Participant.id == Message.sender_id)
                .where(
                    SnapshotMessageRevision.snapshot_id == snapshot_id,
                    Message.id.in_(message_ids),
                )
                .order_by(Message.resolved_timestamp, Message.id)
            )
        ]

    def _review_map(self, annotation_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not annotation_ids:
            return {}
        return {
            review.annotation_id: {
                "id": review.id,
                "decision": review.decision,
                "reviewer": review.reviewer,
                "rationale": review.rationale,
            }
            for review in self.session.scalars(
                select(AnnotationReview)
                .where(AnnotationReview.annotation_id.in_(annotation_ids))
                .order_by(AnnotationReview.created_at)
            )
        }

    def _graph_run(self, corpus_id: str, run_id: str | None) -> AnalysisRun:
        statement = (
            select(AnalysisRun)
            .join(CorpusSnapshot, CorpusSnapshot.id == AnalysisRun.snapshot_id)
            .where(
                CorpusSnapshot.corpus_id == corpus_id,
                AnalysisRun.run_type == "conversation-graph",
            )
        )
        if run_id:
            statement = statement.where(AnalysisRun.id == run_id)
        run = self.session.scalar(statement.order_by(AnalysisRun.created_at.desc()))
        if run is None:
            raise LookupError("conversation graph run not found")
        return run

    def _latest_snapshot(self, corpus_id: str) -> CorpusSnapshot:
        snapshot = self.session.scalar(
            select(CorpusSnapshot)
            .where(CorpusSnapshot.corpus_id == corpus_id)
            .order_by(CorpusSnapshot.created_at.desc(), CorpusSnapshot.id.desc())
        )
        if snapshot is None:
            raise LookupError("corpus snapshot not found")
        return snapshot

    def _snapshot(self, snapshot_id: str) -> CorpusSnapshot:
        snapshot = self.session.get(CorpusSnapshot, snapshot_id)
        if snapshot is None:
            raise LookupError("corpus snapshot not found")
        return snapshot

    def _run(self, run_id: str) -> AnalysisRun:
        run = self.session.get(AnalysisRun, run_id)
        if run is None or run.run_type != "conversation-graph":
            raise LookupError("conversation graph run not found")
        return run

    def _tasks(self, run_id: str) -> dict[str, AnalysisTask]:
        return {
            task.task_key: task
            for task in self.session.scalars(
                select(AnalysisTask).where(AnalysisTask.run_id == run_id)
            )
        }

    def _is_cancelled(self, run_id: str) -> bool:
        self.session.expire_all()
        return self._run(run_id).status == "cancelled"

    @staticmethod
    def _row_evidence(row: MessageRow) -> dict[str, Any]:
        return {
            "object_type": "message",
            "object_id": row.message_id,
            "revision_id": row.revision_id,
            "start_codepoint": 0,
            "end_codepoint": len(row.text),
            "exact_text_hash": row.text_hash,
        }

    @staticmethod
    def _evidence(message_id: str, revision: MessageRevision) -> dict[str, Any]:
        return {
            "object_type": "message",
            "object_id": message_id,
            "revision_id": revision.id,
            "start_codepoint": 0,
            "end_codepoint": len(revision.text),
            "exact_text_hash": revision.text_hash,
        }

    def _provenance(
        self,
        run: AnalysisRun,
        method: str,
        *,
        model: str = "rules-ru-v1",
        model_revision: str | None = None,
    ) -> dict[str, Any]:
        return {
            "corpus_snapshot_id": run.snapshot_id,
            "ontology_version": self.settings.ontology_version,
            "codebook_version": "conversation-graph-ru@0.1.0",
            "codebook_artifact_hash": run.configuration["codebook_artifact_hash"],
            "pipeline_version": ANALYSIS_VERSION,
            "model_provider": "deterministic" if model == "rules-ru-v1" else "local",
            "model": model,
            "model_revision": model_revision,
            "analysis_run_id": run.id,
            "method": method,
            "random_seed": None,
            "created_at": datetime.now(UTC).isoformat(),
        }

    def _derive(
        self,
        source: MessageRow,
        annotation_id: str,
        run_id: str,
        relation: str,
        *,
        targets: list[MessageRow] | None = None,
    ) -> None:
        rows = [(source, relation)] + [
            (target, "USES_CANDIDATE_TARGET") for target in targets or []
        ]
        self.session.add_all(
            DerivationEdge(
                id=new_id(),
                source_type="message_revision",
                source_id=row.revision_id,
                target_type="annotation",
                target_id=annotation_id,
                relation=edge_relation,
                run_id=run_id,
            )
            for row, edge_relation in rows
        )
