from __future__ import annotations

import hashlib
import heapq
import json
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .codebooks import register_codebooks, release_identity
from .config import get_settings
from .models import (
    AnalysisRun,
    Annotation,
    AnnotationReview,
    AnnotationSet,
    AnnotationSetAnnotation,
    AnnotationUnit,
    CodebookArtifact,
    Conversation,
    Corpus,
    CorpusSnapshot,
    EpisodeMessage,
    GoldJudgmentAnnotation,
    GoldTaskJudgment,
    Message,
    MessageRevision,
    Participant,
    SnapshotMessageRevision,
    new_id,
)
from .ontology import RunStatus
from .text import sentence_spans, text_hash
from .workspace import sender_display_name

REVIEW_DECISIONS = {"confirmed", "disputed", "rejected"}
GOLD_TASKS = (
    "dialogue_act",
    "proposition",
    "stance",
    "epistemic_state",
    "grounding",
    "argumentation",
)
JUDGMENT_STATUSES = {"PRESENT", "ABSENT", "ABSTAIN", "NOT_ANNOTATED"}
JUDGMENT_SLOTS = {"A", "B", "FINAL"}
RARE_CUES = {
    "repair": re.compile(r"\b(точнее|поправлюсь|имел[аи]? в виду|не так выразил)\b", re.I),
    "concession": re.compile(r"\b(согласен|согласна|допустим|пусть).{0,80}\bно\b", re.I),
    "attribution": re.compile(r"\b(по словам|считает|утверждает|говорят|якобы)\b", re.I),
    "uncertainty": re.compile(r"\b(возможно|кажется|наверное|не уверен|не уверена)\b", re.I),
    "argument": re.compile(r"\b(потому что|так как|поэтому|следовательно|однако)\b", re.I),
}


class AnnotationWorkbenchService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()

    def create_reference_pilot(self, corpus_id: str) -> AnnotationSet:
        corpus = self.session.get(Corpus, corpus_id)
        if corpus is None:
            raise LookupError("corpus not found")
        snapshot = self.session.scalar(
            select(CorpusSnapshot)
            .where(CorpusSnapshot.corpus_id == corpus.id)
            .order_by(CorpusSnapshot.created_at.desc(), CorpusSnapshot.id.desc())
        )
        if snapshot is None:
            raise LookupError("corpus snapshot not found")
        slug = re.sub(r"[^a-z0-9а-яё]+", "-", corpus.name.casefold()).strip("-")
        return self.create_set(
            corpus_id=corpus.id,
            snapshot_id=snapshot.id,
            name=f"{slug}-reference-ru-pilot-v1",
            target_size=80,
            codebook_key="foundational-conversation-ru",
            codebook_version="0.1.0",
            seed=f"{corpus.id}:reference-ru-pilot-v1",
            double_annotation_fraction=0.3,
            required_tasks=list(GOLD_TASKS),
            judgment_protocol="blind_ab_final_v1",
        )

    def create_set(
        self,
        *,
        corpus_id: str,
        snapshot_id: str,
        name: str,
        target_size: int,
        codebook_key: str,
        codebook_version: str,
        seed: str = "gold-ru-v0",
        double_annotation_fraction: float = 0,
        required_tasks: list[str] | None = None,
        judgment_protocol: str = "legacy_review",
    ) -> AnnotationSet:
        corpus = self.session.get(Corpus, corpus_id)
        snapshot = self.session.get(CorpusSnapshot, snapshot_id)
        if corpus is None or snapshot is None or snapshot.corpus_id != corpus_id:
            raise LookupError("corpus or snapshot not found")
        if corpus.language != "ru":
            raise ValueError("gold pilot currently accepts Russian corpora only")
        if not 1 <= target_size <= 1_200:
            raise ValueError("target_size must be between 1 and 1200")
        required_tasks = required_tasks or list(GOLD_TASKS)
        unknown_tasks = set(required_tasks) - set(GOLD_TASKS)
        if unknown_tasks:
            raise ValueError(f"unknown required tasks: {sorted(unknown_tasks)}")
        if judgment_protocol not in {"legacy_review", "blind_ab_final_v1"}:
            raise ValueError("unknown judgment protocol")
        existing = self.session.scalar(
            select(AnnotationSet).where(
                AnnotationSet.snapshot_id == snapshot_id,
                AnnotationSet.name == name,
            )
        )
        if existing is not None:
            if existing.status == "draft":
                self._rebalance_splits(existing)
                self._assign_double_annotation(existing)
                self._create_task_judgments(existing)
                self.session.commit()
            return existing
        release, artifact_hash = release_identity(self.session, codebook_key, codebook_version)
        if "@" not in release:
            raise RuntimeError("invalid codebook release identity")
        if self.session.get(CodebookArtifact, artifact_hash) is None:
            register_codebooks(self.session)
        run = AnalysisRun(
            id=new_id(),
            snapshot_id=snapshot_id,
            run_type="human-annotation",
            status=RunStatus.RUNNING,
            progress=0,
            configuration={
                "annotation_set": name,
                "codebook_release": release,
                "codebook_artifact_hash": artifact_hash,
            },
            started_at=datetime.now(UTC),
        )
        annotation_set = AnnotationSet(
            id=new_id(),
            corpus_id=corpus_id,
            snapshot_id=snapshot_id,
            analysis_run_id=run.id,
            name=name,
            language="ru",
            codebook_key=codebook_key,
            codebook_version=codebook_version,
            codebook_artifact_hash=artifact_hash,
            status="draft",
            target_size=target_size,
            sampling_spec={
                "strategy": "deterministic-stratified-group-balanced-v2",
                "seed": seed,
                "target_size": target_size,
                "split_group": "episode_or_conversation",
                "split_ratio": {"train": 0.6, "development": 0.2, "test": 0.2},
                "double_annotation_fraction": double_annotation_fraction,
                "required_tasks": required_tasks,
                "judgment_protocol": judgment_protocol,
                "context_policy": {
                    "previous_turns": 3,
                    "reply_target": True,
                    "next_turns": 1,
                    "anchor_only_labelable": True,
                },
            },
        )
        self.session.add_all([run, annotation_set])
        self.session.flush()
        if judgment_protocol == "blind_ab_final_v1":
            candidates, sampling_diagnostics = self._whole_snapshot_candidates(
                snapshot_id, target_size, seed
            )
            annotation_set.sampling_spec = {
                **annotation_set.sampling_spec,
                **sampling_diagnostics,
            }
        else:
            candidates = [
                (*candidate, self._strata(candidate[0], candidate[1]))
                for candidate in self._candidate_units(snapshot_id, target_size, seed)
            ]
        for ordinal, candidate in enumerate(candidates):
            message, revision, episode_message, strata = candidate
            group_id = episode_message.episode_id if episode_message else message.conversation_id
            annotation_unit = AnnotationUnit(
                id=new_id(),
                annotation_set_id=annotation_set.id,
                object_type=(
                    "anchor_message" if judgment_protocol == "blind_ab_final_v1" else "message"
                ),
                object_id=message.id,
                revision_id=revision.id,
                group_id=group_id,
                ordinal=ordinal,
                split="pending",
                strata=strata,
                status="pending",
            )
            self.session.add(annotation_unit)
        self.session.flush()
        self._rebalance_splits(annotation_set)
        self._assign_double_annotation(annotation_set)
        self._create_task_judgments(annotation_set)
        self.session.commit()
        return annotation_set

    def statistics(self, annotation_set_id: str) -> dict[str, Any]:
        annotation_set = self._set(annotation_set_id)
        if annotation_set.sampling_spec.get("judgment_protocol") == "blind_ab_final_v1":
            return self._judgment_statistics(annotation_set)
        units = list(
            self.session.scalars(
                select(AnnotationUnit)
                .where(AnnotationUnit.annotation_set_id == annotation_set.id)
                .order_by(AnnotationUnit.ordinal)
            )
        )
        links = list(
            self.session.scalars(
                select(AnnotationSetAnnotation).where(
                    AnnotationSetAnnotation.annotation_set_id == annotation_set.id
                )
            )
        )
        annotations = {
            annotation.id: annotation
            for annotation_id in {link.annotation_id for link in links}
            if (annotation := self.session.get(Annotation, annotation_id)) is not None
        }
        reviews: dict[str, AnnotationReview] = {}
        if annotations:
            for review in self.session.scalars(
                select(AnnotationReview)
                .where(AnnotationReview.annotation_id.in_(annotations))
                .order_by(
                    AnnotationReview.annotation_id,
                    AnnotationReview.reviewed_at.desc(),
                    AnnotationReview.id.desc(),
                )
            ):
                reviews.setdefault(review.annotation_id, review)
        confirmed_by_unit: dict[str, list[Annotation]] = defaultdict(list)
        coverage_by_kind: Counter[str] = Counter()
        agreement_groups: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
        for link in links:
            annotation = annotations.get(link.annotation_id)
            review = reviews.get(link.annotation_id)
            if (
                annotation is None
                or annotation.superseded_by
                or review is None
                or review.decision != "confirmed"
            ):
                continue
            confirmed_by_unit[link.unit_id].append(annotation)
            coverage_by_kind[annotation.kind] += 1
            annotator = str(annotation.provenance.get("model", "unknown"))
            agreement_groups[(link.unit_id, annotation.kind)][annotator] = json.dumps(
                annotation.value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        agreement_total = 0
        agreement_equal = 0
        for values_by_annotator in agreement_groups.values():
            if len(values_by_annotator) < 2:
                continue
            agreement_total += 1
            agreement_equal += int(len(set(values_by_annotator.values())) == 1)
        double_units = [
            unit for unit in units if bool(unit.strata.get("double_annotation_required"))
        ]
        double_completed = 0
        for unit in double_units:
            annotators = {
                str(annotation.provenance.get("model", "unknown"))
                for annotation in confirmed_by_unit.get(unit.id, [])
            }
            double_completed += int(len(annotators) >= 2)
        status_counts = Counter(unit.status for unit in units)
        split_counts = Counter(unit.split for unit in units)
        return {
            "annotation_set_id": annotation_set.id,
            "name": annotation_set.name,
            "status": annotation_set.status,
            "target_size": annotation_set.target_size,
            "total_units": len(units),
            "status_counts": dict(status_counts),
            "split_counts": dict(split_counts),
            "difficult_units": sum(bool(unit.strata.get("difficult")) for unit in units),
            "confirmed_units": len(confirmed_by_unit),
            "coverage_by_kind": dict(coverage_by_kind),
            "double_annotation": {
                "required": len(double_units),
                "completed": double_completed,
                "fraction": annotation_set.sampling_spec.get("double_annotation_fraction", 0),
            },
            "agreement": {
                "comparable_unit_kinds": agreement_total,
                "exact": agreement_equal,
                "raw_rate": agreement_equal / agreement_total if agreement_total else None,
            },
            "freeze_ready": (
                bool(units)
                and len(confirmed_by_unit) == len(units)
                and double_completed == len(double_units)
            ),
            "manifest_hash": annotation_set.manifest_hash,
        }

    def _judgment_statistics(self, annotation_set: AnnotationSet) -> dict[str, Any]:
        units = list(
            self.session.scalars(
                select(AnnotationUnit).where(AnnotationUnit.annotation_set_id == annotation_set.id)
            )
        )
        judgments = list(
            self.session.scalars(
                select(GoldTaskJudgment).where(
                    GoldTaskJudgment.annotation_set_id == annotation_set.id
                )
            )
        )
        links = (
            list(
                self.session.scalars(
                    select(GoldJudgmentAnnotation).where(
                        GoldJudgmentAnnotation.judgment_id.in_(
                            [judgment.id for judgment in judgments]
                        )
                    )
                )
            )
            if judgments
            else []
        )
        annotation_by_id = {
            annotation.id: annotation
            for annotation_id in {link.annotation_id for link in links}
            if (annotation := self.session.get(Annotation, annotation_id)) is not None
        }
        annotations_by_judgment: dict[str, list[Annotation]] = defaultdict(list)
        for link in links:
            annotation = annotation_by_id.get(link.annotation_id)
            if annotation is not None:
                annotations_by_judgment[link.judgment_id].append(annotation)
        by_unit: dict[str, list[GoldTaskJudgment]] = defaultdict(list)
        by_key: dict[tuple[str, str, str], GoldTaskJudgment] = {}
        for judgment in judgments:
            by_unit[judgment.unit_id].append(judgment)
            by_key[(judgment.unit_id, judgment.task, judgment.slot)] = judgment
        required_tasks = list(annotation_set.sampling_spec.get("required_tasks", GOLD_TASKS))
        final_completed_by_task = Counter(
            judgment.task
            for judgment in judgments
            if judgment.slot == "FINAL" and judgment.status != "NOT_ANNOTATED"
        )
        confirmed_units = sum(
            all(
                (judgment := by_key.get((unit.id, task, "FINAL"))) is not None
                and judgment.status != "NOT_ANNOTATED"
                for task in required_tasks
            )
            for unit in units
        )
        double_units = [
            unit for unit in units if bool(unit.strata.get("double_annotation_required"))
        ]
        double_completed = sum(
            all(
                (left := by_key.get((unit.id, task, "A"))) is not None
                and left.status != "NOT_ANNOTATED"
                and (right := by_key.get((unit.id, task, "B"))) is not None
                and right.status != "NOT_ANNOTATED"
                for task in required_tasks
            )
            for unit in double_units
        )
        agreement_by_task: dict[str, dict[str, Any]] = {}
        agreement_total = 0
        agreement_exact = 0
        for task in required_tasks:
            comparable = 0
            exact = 0
            for unit in double_units:
                left = by_key.get((unit.id, task, "A"))
                right = by_key.get((unit.id, task, "B"))
                if (
                    left is None
                    or right is None
                    or left.status == "NOT_ANNOTATED"
                    or right.status == "NOT_ANNOTATED"
                ):
                    continue
                comparable += 1
                exact += int(
                    self._judgment_signature(left, annotations_by_judgment[left.id])
                    == self._judgment_signature(right, annotations_by_judgment[right.id])
                )
            agreement_total += comparable
            agreement_exact += exact
            agreement_by_task[task] = {
                "comparable": comparable,
                "exact": exact,
                "raw_rate": exact / comparable if comparable else None,
            }
        status_counts = Counter(unit.status for unit in units)
        split_counts = Counter(unit.split for unit in units)
        coverage_by_kind = Counter(
            annotation.kind
            for judgment in judgments
            if judgment.slot == "FINAL" and judgment.status == "PRESENT"
            for annotation in annotations_by_judgment[judgment.id]
        )
        return {
            "annotation_set_id": annotation_set.id,
            "name": annotation_set.name,
            "status": annotation_set.status,
            "target_size": annotation_set.target_size,
            "total_units": len(units),
            "status_counts": dict(status_counts),
            "split_counts": dict(split_counts),
            "difficult_units": sum(bool(unit.strata.get("difficult")) for unit in units),
            "confirmed_units": confirmed_units,
            "coverage_by_kind": dict(coverage_by_kind),
            "task_completion": {
                task: {
                    "completed": final_completed_by_task[task],
                    "required": len(units),
                }
                for task in required_tasks
            },
            "double_annotation": {
                "required": len(double_units),
                "completed": double_completed,
                "fraction": annotation_set.sampling_spec.get("double_annotation_fraction", 0),
            },
            "agreement": {
                "comparable_unit_kinds": agreement_total,
                "exact": agreement_exact,
                "raw_rate": (agreement_exact / agreement_total if agreement_total else None),
                "by_task": agreement_by_task,
                "stage": "independent_A_vs_B_pre_adjudication",
            },
            "freeze_ready": bool(units) and confirmed_units == len(units),
            "manifest_hash": annotation_set.manifest_hash,
            "judgment_protocol": "blind_ab_final_v1",
        }

    @staticmethod
    def _judgment_signature(judgment: GoldTaskJudgment, annotations: list[Annotation]) -> str:
        payload = {
            "status": judgment.status,
            "annotations": sorted(
                (
                    {
                        "kind": annotation.kind,
                        "value": annotation.value,
                        "evidence": annotation.evidence,
                    }
                    for annotation in annotations
                ),
                key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
            ),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _candidate_units(
        self, snapshot_id: str, target_size: int, seed: str
    ) -> list[tuple[Message, MessageRevision, EpisodeMessage | None]]:
        candidate_limit = max(target_size * 6, 300)
        raw_rows = list(
            self.session.execute(
                select(Message, MessageRevision, EpisodeMessage)
                .join(SnapshotMessageRevision, SnapshotMessageRevision.message_id == Message.id)
                .join(MessageRevision, MessageRevision.id == SnapshotMessageRevision.revision_id)
                .outerjoin(EpisodeMessage, EpisodeMessage.message_id == Message.id)
                .where(SnapshotMessageRevision.snapshot_id == snapshot_id)
                .order_by(Message.id)
                .limit(candidate_limit)
            )
        )
        rows: list[tuple[Message, MessageRevision, EpisodeMessage | None]] = []
        seen_messages: set[str] = set()
        for row in raw_rows:
            if row[0].id not in seen_messages:
                rows.append(row)
                seen_messages.add(row[0].id)
        rows.sort(key=lambda row: hashlib.sha256(f"{seed}:{row[0].id}".encode()).hexdigest())
        difficult = [row for row in rows if self._is_difficult(row[0], row[1])]
        routine = [row for row in rows if not self._is_difficult(row[0], row[1])]
        selected: list[tuple[Message, MessageRevision, EpisodeMessage | None]] = []
        for bucket in (difficult, routine):
            selected.extend(bucket[: target_size // 2])
        selected_ids = {row[0].id for row in selected}
        selected.extend(row for row in rows if row[0].id not in selected_ids)
        return selected[:target_size]

    def _whole_snapshot_candidates(
        self,
        snapshot_id: str,
        target_size: int,
        seed: str,
    ) -> tuple[
        list[tuple[Message, MessageRevision, EpisodeMessage | None, dict[str, Any]]],
        dict[str, Any],
    ]:
        episode_sizes = {
            episode_id: count
            for episode_id, count in self.session.execute(
                select(EpisodeMessage.episode_id, func.count(EpisodeMessage.id)).group_by(
                    EpisodeMessage.episode_id
                )
            )
        }
        per_bucket_limit = 2
        buckets: dict[str, list[tuple[int, str, tuple[Any, ...]]]] = defaultdict(list)
        fallback: list[tuple[int, str, tuple[Any, ...]]] = []
        fallback_limit = max(target_size * 4, target_size)
        scanned = 0
        statement = (
            select(Message, MessageRevision, EpisodeMessage, Conversation)
            .join(SnapshotMessageRevision, SnapshotMessageRevision.message_id == Message.id)
            .join(MessageRevision, MessageRevision.id == SnapshotMessageRevision.revision_id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .outerjoin(EpisodeMessage, EpisodeMessage.message_id == Message.id)
            .where(SnapshotMessageRevision.snapshot_id == snapshot_id)
            .order_by(Message.id)
            .execution_options(yield_per=1000)
        )
        for message, revision, episode_message, conversation in self.session.execute(statement):
            scanned += 1
            episode_size = episode_sizes.get(
                episode_message.episode_id if episode_message else "", 0
            )
            strata = self._gold_strata(message, revision, conversation, episode_size)
            bucket_key = json.dumps(
                {
                    "time_period": strata["time_period"],
                    "conversation": strata["conversation_id"],
                    "participant": strata["participant_id"],
                    "episode_size": strata["episode_size_bucket"],
                    "reply": strata["has_explicit_reply"],
                    "length": strata["length_bucket"],
                    "question": strata["contains_question"],
                    "multi": strata["multi_proposition_cue"],
                    "rare": strata["rare_cues"][0] if strata["rare_cues"] else "none",
                    "platform": strata["platform"],
                    "goal": strata["conversation_goal"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            priority = int(
                hashlib.sha256(f"{seed}:whole-snapshot:{message.id}".encode()).hexdigest(),
                16,
            )
            candidate = (message, revision, episode_message, strata)
            self._offer_candidate(
                buckets[bucket_key], priority, message.id, candidate, per_bucket_limit
            )
            self._offer_candidate(fallback, priority, message.id, candidate, fallback_limit)
        bucket_order = sorted(
            buckets,
            key=lambda key: hashlib.sha256(f"{seed}:bucket:{key}".encode()).hexdigest(),
        )
        ordered_buckets = {
            key: [item[2] for item in sorted(buckets[key], key=lambda item: -item[0])]
            for key in bucket_order
        }
        selected: list[tuple[Message, MessageRevision, EpisodeMessage | None, dict[str, Any]]] = []
        selected_ids: set[str] = set()
        depth = 0
        while len(selected) < target_size:
            added = False
            for key in bucket_order:
                candidates = ordered_buckets[key]
                if depth >= len(candidates):
                    continue
                candidate = candidates[depth]
                if candidate[0].id in selected_ids:
                    continue
                selected.append(candidate)
                selected_ids.add(candidate[0].id)
                added = True
                if len(selected) == target_size:
                    break
            if not added:
                break
            depth += 1
        for _negative_priority, _message_id, candidate in sorted(
            fallback, key=lambda item: -item[0]
        ):
            if len(selected) == target_size:
                break
            if candidate[0].id not in selected_ids:
                selected.append(candidate)
                selected_ids.add(candidate[0].id)
        return selected, {
            "strategy": "whole-snapshot-multistrata-bottom-hash-v1",
            "sampling_scope": "complete_snapshot",
            "scanned_units": scanned,
            "candidate_buckets": len(buckets),
            "sampled_units": len(selected),
            "strata_dimensions": [
                "time_period",
                "conversation_id",
                "participant_id",
                "episode_size_bucket",
                "has_explicit_reply",
                "length_bucket",
                "contains_question",
                "multi_proposition_cue",
                "rare_cues",
                "platform",
                "conversation_goal",
            ],
        }

    @staticmethod
    def _offer_candidate(
        heap: list[tuple[int, str, tuple[Any, ...]]],
        priority: int,
        message_id: str,
        candidate: tuple[Any, ...],
        limit: int,
    ) -> None:
        item = (-priority, message_id, candidate)
        if len(heap) < limit:
            heapq.heappush(heap, item)
        elif priority < -heap[0][0]:
            heapq.heapreplace(heap, item)

    @staticmethod
    def _gold_strata(
        message: Message,
        revision: MessageRevision,
        conversation: Conversation,
        episode_size: int,
    ) -> dict[str, Any]:
        length = len(revision.text)
        sentence_count = sum(1 for _span in sentence_spans(revision.text))
        rare_cues = [name for name, pattern in RARE_CUES.items() if pattern.search(revision.text)]
        return {
            "time_period": f"{message.sent_at.year}-Q{(message.sent_at.month - 1) // 3 + 1}",
            "conversation_id": conversation.id,
            "participant_id": message.sender_id or "UNRESOLVED",
            "episode_size_bucket": (
                "small" if episode_size < 10 else "medium" if episode_size < 50 else "large"
            ),
            "has_explicit_reply": bool(message.reply_to_external_id),
            "length_bucket": "short" if length < 60 else "medium" if length < 180 else "long",
            "contains_question": "?" in revision.text,
            "multi_proposition_cue": sentence_count > 1,
            "rare_cues": rare_cues,
            "platform": conversation.platform,
            "conversation_goal": conversation.goal,
            "difficult": bool(
                message.reply_to_external_id
                or "?" in revision.text
                or length > 180
                or sentence_count > 1
                or rare_cues
            ),
        }

    def list_units(
        self, annotation_set_id: str, *, after_ordinal: int = -1, limit: int = 50
    ) -> list[dict[str, Any]]:
        annotation_set = self._set(annotation_set_id)
        rows = self.session.execute(
            select(AnnotationUnit, Message, MessageRevision)
            .join(Message, Message.id == AnnotationUnit.object_id)
            .join(MessageRevision, MessageRevision.id == AnnotationUnit.revision_id)
            .where(
                AnnotationUnit.annotation_set_id == annotation_set.id,
                AnnotationUnit.ordinal > after_ordinal,
            )
            .order_by(AnnotationUnit.ordinal)
            .limit(min(max(limit, 1), 200))
        )
        return [
            self._unit_payload(annotation_set, unit, message, revision)
            for unit, message, revision in rows
        ]

    def add_annotation(
        self,
        unit_id: str,
        *,
        kind: str,
        value: dict[str, Any],
        spans: list[dict[str, int]],
        annotator: str,
        supersedes_annotation_id: str | None = None,
    ) -> Annotation:
        unit = self.session.get(AnnotationUnit, unit_id)
        if unit is None:
            raise LookupError("annotation unit not found")
        annotation_set = self._set(unit.annotation_set_id)
        if annotation_set.status != "draft":
            raise ValueError("frozen annotation sets cannot be modified")
        revision = self.session.get(MessageRevision, unit.revision_id)
        if revision is None:
            raise RuntimeError("annotation unit revision is missing")
        evidence = self._evidence(revision, spans)
        annotation = Annotation(
            id=new_id(),
            snapshot_id=annotation_set.snapshot_id,
            run_id=annotation_set.analysis_run_id,
            object_type=unit.object_type,
            object_id=unit.object_id,
            kind=kind,
            value=value,
            evidence=evidence,
            status="provisional",
            raw_confidence=None,
            calibrated_confidence=None,
            alternatives=[],
            provenance={
                "corpus_snapshot_id": annotation_set.snapshot_id,
                "ontology_version": self.settings.ontology_version,
                "codebook_version": (
                    f"{annotation_set.codebook_key}@{annotation_set.codebook_version}"
                ),
                "codebook_artifact_hash": annotation_set.codebook_artifact_hash,
                "pipeline_version": self.settings.pipeline_version,
                "model_provider": "human",
                "model": annotator,
                "analysis_run_id": annotation_set.analysis_run_id,
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
        self.session.add(annotation)
        self.session.flush()
        role = "adjudicated" if supersedes_annotation_id else "human"
        self.session.add(
            AnnotationSetAnnotation(
                id=new_id(),
                annotation_set_id=annotation_set.id,
                unit_id=unit.id,
                annotation_id=annotation.id,
                role=role,
            )
        )
        if supersedes_annotation_id:
            superseded = self.session.get(Annotation, supersedes_annotation_id)
            if superseded is None or not self._annotation_belongs_to_unit(superseded.id, unit.id):
                raise ValueError("superseded annotation does not belong to this unit")
            superseded.superseded_by = annotation.id
        unit.status = "annotated"
        self.session.commit()
        return annotation

    def submit_task_judgment(
        self,
        unit_id: str,
        task: str,
        slot: str,
        *,
        status: str,
        annotator: str,
        annotations: list[dict[str, Any]],
    ) -> GoldTaskJudgment:
        if status not in JUDGMENT_STATUSES - {"NOT_ANNOTATED"}:
            raise ValueError("judgment status must be PRESENT, ABSENT, or ABSTAIN")
        if slot not in JUDGMENT_SLOTS:
            raise ValueError("judgment slot must be A, B, or FINAL")
        unit = self.session.get(AnnotationUnit, unit_id)
        if unit is None:
            raise LookupError("annotation unit not found")
        annotation_set = self._set(unit.annotation_set_id)
        if annotation_set.status != "draft":
            raise ValueError("frozen annotation sets cannot be modified")
        judgment = self.session.scalar(
            select(GoldTaskJudgment).where(
                GoldTaskJudgment.unit_id == unit.id,
                GoldTaskJudgment.task == task,
                GoldTaskJudgment.slot == slot,
            )
        )
        if judgment is None:
            raise LookupError("task judgment not found for this unit and slot")
        if judgment.status != "NOT_ANNOTATED":
            raise ValueError("submitted judgments are immutable")
        annotator = annotator.strip()
        if not annotator:
            raise ValueError("judgments require an explicit annotator identity")
        if status == "PRESENT" and not annotations:
            raise ValueError("PRESENT judgments require at least one annotation")
        if status != "PRESENT" and annotations:
            raise ValueError("ABSENT and ABSTAIN judgments cannot contain annotations")
        if any(annotation["kind"] != task for annotation in annotations):
            raise ValueError("judgment annotations must match the judgment task")
        self._validate_task_annotations(task, status, annotations)
        independent = list(
            self.session.scalars(
                select(GoldTaskJudgment).where(
                    GoldTaskJudgment.unit_id == unit.id,
                    GoldTaskJudgment.task == task,
                    GoldTaskJudgment.slot.in_(["A", "B"]),
                )
            )
        )
        if slot in {"A", "B"}:
            other_slot = "B" if slot == "A" else "A"
            other = next((item for item in independent if item.slot == other_slot), None)
            if other is not None and other.annotator == annotator:
                raise ValueError("independent A/B judgments require distinct annotators")
        if slot == "FINAL":
            if not independent or any(item.status == "NOT_ANNOTATED" for item in independent):
                raise ValueError("FINAL adjudication requires all independent judgments")
            if annotator in {item.annotator for item in independent}:
                raise ValueError("FINAL adjudicator must differ from independent annotators")
        revision = self.session.get(MessageRevision, unit.revision_id)
        if revision is None:
            raise RuntimeError("annotation unit revision is missing")
        role = "adjudicated" if slot == "FINAL" else f"independent_{slot.casefold()}"
        for item in annotations:
            annotation = Annotation(
                id=new_id(),
                snapshot_id=annotation_set.snapshot_id,
                run_id=annotation_set.analysis_run_id,
                object_type=unit.object_type,
                object_id=unit.object_id,
                kind=item["kind"],
                value=item["value"],
                evidence=self._evidence(revision, item["spans"]),
                status="confirmed" if slot == "FINAL" else "provisional",
                raw_confidence=None,
                calibrated_confidence=None,
                alternatives=[],
                provenance={
                    "corpus_snapshot_id": annotation_set.snapshot_id,
                    "ontology_version": self.settings.ontology_version,
                    "codebook_version": (
                        f"{annotation_set.codebook_key}@{annotation_set.codebook_version}"
                    ),
                    "codebook_artifact_hash": annotation_set.codebook_artifact_hash,
                    "pipeline_version": self.settings.pipeline_version,
                    "model_provider": "human",
                    "model": annotator,
                    "analysis_run_id": annotation_set.analysis_run_id,
                    "judgment_slot": slot,
                    "judgment_stage": judgment.stage,
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )
            self.session.add(annotation)
            self.session.flush()
            self.session.add_all(
                [
                    AnnotationSetAnnotation(
                        id=new_id(),
                        annotation_set_id=annotation_set.id,
                        unit_id=unit.id,
                        annotation_id=annotation.id,
                        role=role,
                    ),
                    GoldJudgmentAnnotation(
                        id=new_id(),
                        judgment_id=judgment.id,
                        annotation_id=annotation.id,
                    ),
                ]
            )
        judgment.status = status
        judgment.annotator = annotator
        judgment.submitted_at = datetime.now(UTC)
        judgment.provenance = {
            **judgment.provenance,
            "annotator": annotator,
            "submitted_at": judgment.submitted_at.isoformat(),
        }
        self.session.flush()
        self._refresh_unit_status(unit)
        self.session.commit()
        return judgment

    @staticmethod
    def _validate_task_annotations(
        task: str,
        status: str,
        annotations: list[dict[str, Any]],
    ) -> None:
        if status != "PRESENT":
            return
        for annotation in annotations:
            value = annotation["value"]
            if task == "stance" and not (
                value.get("holder_id")
                and (value.get("target_id") or value.get("target"))
                and value.get("position")
            ):
                raise ValueError("PRESENT stance requires holder, target, and position")
            if task == "epistemic_state" and not (
                value.get("holder_id")
                and (value.get("proposition_id") or value.get("target_id") or value.get("target"))
            ):
                raise ValueError("PRESENT epistemic state requires holder and target")
            if task == "grounding" and not (value.get("target_id") or value.get("target")):
                raise ValueError("PRESENT grounding requires an explicit target")
            if task == "argumentation" and not (
                (value.get("source_id") or value.get("source"))
                and (value.get("target_id") or value.get("target"))
                and (value.get("relation_type") or value.get("label"))
            ):
                raise ValueError(
                    "PRESENT argument relation requires source, target, and relation type"
                )

    def unit_context(self, unit_id: str, slot: str) -> dict[str, Any]:
        if slot not in JUDGMENT_SLOTS:
            raise ValueError("judgment slot must be A, B, or FINAL")
        unit = self.session.get(AnnotationUnit, unit_id)
        if unit is None:
            raise LookupError("annotation unit not found")
        annotation_set = self._set(unit.annotation_set_id)
        anchor = self.session.get(Message, unit.object_id)
        if anchor is None:
            raise RuntimeError("annotation anchor message is missing")
        episode_message = self.session.scalar(
            select(EpisodeMessage).where(EpisodeMessage.message_id == anchor.id)
        )
        context_rows: list[tuple[Message, MessageRevision, Participant | None, str]] = []
        episode_id = episode_message.episode_id if episode_message else None
        episode_size = 0
        if episode_message:
            episode_rows = list(
                self.session.execute(
                    select(Message, MessageRevision, Participant, EpisodeMessage.ordinal)
                    .join(EpisodeMessage, EpisodeMessage.message_id == Message.id)
                    .join(
                        SnapshotMessageRevision,
                        SnapshotMessageRevision.message_id == Message.id,
                    )
                    .join(
                        MessageRevision,
                        MessageRevision.id == SnapshotMessageRevision.revision_id,
                    )
                    .outerjoin(Participant, Participant.id == Message.sender_id)
                    .where(
                        EpisodeMessage.episode_id == episode_message.episode_id,
                        SnapshotMessageRevision.snapshot_id == annotation_set.snapshot_id,
                    )
                    .order_by(EpisodeMessage.ordinal)
                )
            )
            episode_size = len(episode_rows)
            anchor_index = next(
                index for index, row in enumerate(episode_rows) if row[0].id == anchor.id
            )
            start = max(0, anchor_index - 3)
            end = min(len(episode_rows), anchor_index + 2)
            for index, row in enumerate(episode_rows[start:end], start=start):
                role = (
                    "anchor"
                    if index == anchor_index
                    else "previous"
                    if index < anchor_index
                    else "next"
                )
                context_rows.append((row[0], row[1], row[2], role))
        else:
            revision = self.session.get(MessageRevision, unit.revision_id)
            participant = (
                self.session.get(Participant, anchor.sender_id) if anchor.sender_id else None
            )
            if revision is not None:
                context_rows.append((anchor, revision, participant, "anchor"))
        if anchor.reply_to_external_id:
            reply_row = self.session.execute(
                select(Message, MessageRevision, Participant)
                .join(
                    SnapshotMessageRevision,
                    SnapshotMessageRevision.message_id == Message.id,
                )
                .join(
                    MessageRevision,
                    MessageRevision.id == SnapshotMessageRevision.revision_id,
                )
                .outerjoin(Participant, Participant.id == Message.sender_id)
                .where(
                    Message.conversation_id == anchor.conversation_id,
                    Message.external_id == anchor.reply_to_external_id,
                    SnapshotMessageRevision.snapshot_id == annotation_set.snapshot_id,
                )
            ).one_or_none()
            if reply_row:
                reply_index = next(
                    (
                        index
                        for index, row in enumerate(context_rows)
                        if row[0].id == reply_row[0].id
                    ),
                    None,
                )
                if reply_index is None:
                    context_rows.insert(
                        0, (reply_row[0], reply_row[1], reply_row[2], "reply_target")
                    )
                else:
                    existing = context_rows[reply_index]
                    context_rows[reply_index] = (*existing[:3], "reply_target")
        judgments = list(
            self.session.scalars(
                select(GoldTaskJudgment)
                .where(
                    GoldTaskJudgment.unit_id == unit.id,
                    (
                        GoldTaskJudgment.slot == slot
                        if slot in {"A", "B"}
                        else GoldTaskJudgment.slot.in_(["A", "B", "FINAL"])
                    ),
                )
                .order_by(GoldTaskJudgment.task, GoldTaskJudgment.slot)
            )
        )
        if slot == "B" and not judgments:
            raise ValueError("slot B is available only for DOUBLE annotation units")
        return {
            "unit_id": unit.id,
            "annotation_set_id": annotation_set.id,
            "split": unit.split,
            "strata": unit.strata,
            "slot": slot,
            "blind": slot in {"A", "B"},
            "anchor_message_id": anchor.id,
            "anchor_revision_id": unit.revision_id,
            "episode_id": episode_id,
            "episode_size": episode_size,
            "context_policy": annotation_set.sampling_spec.get("context_policy", {}),
            "messages": [
                {
                    "message_id": message.id,
                    "sender_id": message.sender_id,
                    "sender_name": sender_display_name(message, participant),
                    "sent_at": message.sent_at.isoformat(),
                    "text": revision.text,
                    "context_role": role,
                    "labelable": role == "anchor",
                }
                for message, revision, participant, role in context_rows
            ],
            "judgments": [self._judgment_payload(judgment) for judgment in judgments],
        }

    def review(self, annotation_id: str, *, decision: str, reviewer: str) -> AnnotationReview:
        if decision not in REVIEW_DECISIONS:
            raise ValueError(f"unknown review decision: {decision}")
        annotation = self.session.get(Annotation, annotation_id)
        if annotation is None:
            raise LookupError("annotation not found")
        link = self.session.scalar(
            select(AnnotationSetAnnotation).where(
                AnnotationSetAnnotation.annotation_id == annotation_id
            )
        )
        if link is None:
            raise ValueError("annotation is not part of an annotation set")
        annotation_set = self._set(link.annotation_set_id)
        if annotation_set.status != "draft":
            raise ValueError("frozen annotation sets cannot be reviewed")
        review = AnnotationReview(
            id=new_id(),
            annotation_id=annotation_id,
            decision=decision,
            reviewer=reviewer,
            reviewed_at=datetime.now(UTC),
        )
        self.session.add(review)
        unit = self.session.get(AnnotationUnit, link.unit_id)
        if unit is not None:
            unit.status = "reviewed" if decision == "confirmed" else decision
        self.session.flush()
        total_units = (
            self.session.scalar(
                select(func.count())
                .select_from(AnnotationUnit)
                .where(AnnotationUnit.annotation_set_id == annotation_set.id)
            )
            or 0
        )
        reviewed_units = (
            self.session.scalar(
                select(func.count())
                .select_from(AnnotationUnit)
                .where(
                    AnnotationUnit.annotation_set_id == annotation_set.id,
                    AnnotationUnit.status == "reviewed",
                )
            )
            or 0
        )
        run = self.session.get(AnalysisRun, annotation_set.analysis_run_id)
        if run is not None:
            run.progress = reviewed_units / total_units if total_units else 0
        self.session.commit()
        return review

    def freeze(self, annotation_set_id: str) -> AnnotationSet:
        annotation_set = self._set(annotation_set_id)
        if annotation_set.status == "frozen":
            return annotation_set
        if annotation_set.sampling_spec.get("judgment_protocol") == "blind_ab_final_v1":
            return self._freeze_judgment_set(annotation_set)
        units = list(
            self.session.scalars(
                select(AnnotationUnit)
                .where(AnnotationUnit.annotation_set_id == annotation_set.id)
                .order_by(AnnotationUnit.ordinal)
            )
        )
        manifest: list[dict[str, Any]] = []
        missing: list[int] = []
        missing_double: list[int] = []
        for unit in units:
            confirmed = self._confirmed_annotations(annotation_set.id, unit.id)
            if not confirmed:
                missing.append(unit.ordinal)
                continue
            if unit.strata.get("double_annotation_required"):
                annotators = {
                    str(annotation.provenance.get("model", "unknown")) for annotation in confirmed
                }
                if len(annotators) < 2:
                    missing_double.append(unit.ordinal)
                    continue
            revision = self.session.get(MessageRevision, unit.revision_id)
            if revision is None:
                raise RuntimeError("annotation unit revision is missing")
            manifest.append(
                {
                    "unit_id": unit.id,
                    "ordinal": unit.ordinal,
                    "object_id": unit.object_id,
                    "revision_id": unit.revision_id,
                    "text_hash": revision.text_hash,
                    "split": unit.split,
                    "annotations": [
                        {
                            "id": annotation.id,
                            "kind": annotation.kind,
                            "value": annotation.value,
                            "evidence": annotation.evidence,
                        }
                        for annotation in confirmed
                    ],
                }
            )
        if missing:
            preview = ", ".join(str(value) for value in missing[:10])
            raise ValueError(f"all units require a confirmed annotation; missing: {preview}")
        if missing_double:
            preview = ", ".join(str(value) for value in missing_double[:10])
            raise ValueError(
                f"double-annotation units require two confirmed annotators; missing: {preview}"
            )
        encoded = json.dumps(
            manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        annotation_set.manifest_hash = hashlib.sha256(encoded).hexdigest()
        annotation_set.status = "frozen"
        annotation_set.frozen_at = datetime.now(UTC)
        run = self.session.get(AnalysisRun, annotation_set.analysis_run_id)
        if run is not None:
            run.status = RunStatus.COMPLETED
            run.progress = 1
            run.completed_at = annotation_set.frozen_at
        self.session.commit()
        return annotation_set

    def _freeze_judgment_set(self, annotation_set: AnnotationSet) -> AnnotationSet:
        units = list(
            self.session.scalars(
                select(AnnotationUnit)
                .where(AnnotationUnit.annotation_set_id == annotation_set.id)
                .order_by(AnnotationUnit.ordinal)
            )
        )
        required_tasks = list(annotation_set.sampling_spec.get("required_tasks", GOLD_TASKS))
        judgments = list(
            self.session.scalars(
                select(GoldTaskJudgment)
                .where(GoldTaskJudgment.annotation_set_id == annotation_set.id)
                .order_by(
                    GoldTaskJudgment.unit_id,
                    GoldTaskJudgment.task,
                    GoldTaskJudgment.slot,
                )
            )
        )
        by_unit: dict[str, list[GoldTaskJudgment]] = defaultdict(list)
        for judgment in judgments:
            by_unit[judgment.unit_id].append(judgment)
        missing: list[dict[str, Any]] = []
        manifest = []
        for unit in units:
            unit_judgments = by_unit[unit.id]
            final_by_task = {
                judgment.task: judgment for judgment in unit_judgments if judgment.slot == "FINAL"
            }
            missing_tasks = [
                task
                for task in required_tasks
                if task not in final_by_task or final_by_task[task].status == "NOT_ANNOTATED"
            ]
            if missing_tasks:
                missing.append({"ordinal": unit.ordinal, "tasks": missing_tasks})
                continue
            revision = self.session.get(MessageRevision, unit.revision_id)
            if revision is None:
                raise RuntimeError("annotation unit revision is missing")
            manifest.append(
                {
                    "unit_id": unit.id,
                    "ordinal": unit.ordinal,
                    "anchor_message_id": unit.object_id,
                    "revision_id": unit.revision_id,
                    "text_hash": revision.text_hash,
                    "split": unit.split,
                    "strata": unit.strata,
                    "judgments": [self._judgment_payload(judgment) for judgment in unit_judgments],
                }
            )
        if missing:
            preview = "; ".join(
                f"{item['ordinal']}: {','.join(item['tasks'])}" for item in missing[:5]
            )
            raise ValueError(
                "every required FINAL task judgment must be complete; missing "
                f"unit/task pairs: {preview}"
            )
        encoded = json.dumps(
            manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        annotation_set.manifest_hash = hashlib.sha256(encoded).hexdigest()
        annotation_set.status = "frozen"
        annotation_set.frozen_at = datetime.now(UTC)
        run = self.session.get(AnalysisRun, annotation_set.analysis_run_id)
        if run is not None:
            run.status = RunStatus.COMPLETED
            run.progress = 1
            run.completed_at = annotation_set.frozen_at
        self.session.commit()
        return annotation_set

    def export(self, annotation_set_id: str) -> dict[str, Any]:
        annotation_set = self._set(annotation_set_id)
        if annotation_set.status != "frozen":
            raise ValueError("only frozen annotation sets can be exported")
        if annotation_set.sampling_spec.get("judgment_protocol") == "blind_ab_final_v1":
            unit_ids = list(
                self.session.scalars(
                    select(AnnotationUnit.id)
                    .where(AnnotationUnit.annotation_set_id == annotation_set.id)
                    .order_by(AnnotationUnit.ordinal)
                )
            )
            units = [self.unit_context(unit_id, "FINAL") for unit_id in unit_ids]
        else:
            units = []
            cursor = -1
            while True:
                page = self.list_units(annotation_set.id, after_ordinal=cursor, limit=200)
                if not page:
                    break
                units.extend(page)
                cursor = page[-1]["ordinal"]
        return {
            "schema": "hetaira.annotation-set.v1",
            "annotation_set_id": annotation_set.id,
            "name": annotation_set.name,
            "language": annotation_set.language,
            "snapshot_id": annotation_set.snapshot_id,
            "codebook": (f"{annotation_set.codebook_key}@{annotation_set.codebook_version}"),
            "codebook_artifact_hash": annotation_set.codebook_artifact_hash,
            "manifest_hash": annotation_set.manifest_hash,
            "sampling_spec": annotation_set.sampling_spec,
            "units": units,
        }

    def _unit_payload(
        self,
        annotation_set: AnnotationSet,
        unit: AnnotationUnit,
        message: Message,
        revision: MessageRevision,
    ) -> dict[str, Any]:
        if annotation_set.sampling_spec.get("judgment_protocol") == "blind_ab_final_v1":
            judgments = list(
                self.session.scalars(
                    select(GoldTaskJudgment).where(GoldTaskJudgment.unit_id == unit.id)
                )
            )
            return {
                "id": unit.id,
                "ordinal": unit.ordinal,
                "object_type": unit.object_type,
                "object_id": unit.object_id,
                "revision_id": unit.revision_id,
                "group_id": unit.group_id,
                "split": unit.split,
                "strata": unit.strata,
                "status": unit.status,
                "sender_id": message.sender_id,
                "sent_at": message.sent_at.isoformat(),
                "text": revision.text,
                "text_hash": revision.text_hash,
                "annotations": [],
                "judgment_progress": {
                    slot: {
                        "completed": sum(
                            judgment.status != "NOT_ANNOTATED"
                            for judgment in judgments
                            if judgment.slot == slot
                        ),
                        "required": sum(judgment.slot == slot for judgment in judgments),
                    }
                    for slot in ("A", "B", "FINAL")
                    if any(judgment.slot == slot for judgment in judgments)
                },
            }
        links = list(
            self.session.scalars(
                select(AnnotationSetAnnotation).where(AnnotationSetAnnotation.unit_id == unit.id)
            )
        )
        annotations: list[dict[str, Any]] = []
        for link in links:
            annotation = self.session.get(Annotation, link.annotation_id)
            if annotation is None:
                continue
            latest_review = self.session.scalar(
                select(AnnotationReview)
                .where(AnnotationReview.annotation_id == annotation.id)
                .order_by(AnnotationReview.reviewed_at.desc(), AnnotationReview.id.desc())
            )
            annotations.append(
                {
                    "id": annotation.id,
                    "kind": annotation.kind,
                    "value": annotation.value,
                    "evidence": annotation.evidence,
                    "role": link.role,
                    "superseded_by": annotation.superseded_by,
                    "review": (
                        {
                            "decision": latest_review.decision,
                            "reviewer": latest_review.reviewer,
                            "reviewed_at": latest_review.reviewed_at.isoformat(),
                        }
                        if latest_review
                        else None
                    ),
                }
            )
        return {
            "id": unit.id,
            "ordinal": unit.ordinal,
            "object_type": unit.object_type,
            "object_id": unit.object_id,
            "revision_id": unit.revision_id,
            "group_id": unit.group_id,
            "split": unit.split,
            "strata": unit.strata,
            "status": unit.status,
            "sender_id": message.sender_id,
            "sent_at": message.sent_at.isoformat(),
            "text": revision.text,
            "text_hash": revision.text_hash,
            "annotations": annotations,
        }

    def _judgment_payload(self, judgment: GoldTaskJudgment) -> dict[str, Any]:
        links = list(
            self.session.scalars(
                select(GoldJudgmentAnnotation).where(
                    GoldJudgmentAnnotation.judgment_id == judgment.id
                )
            )
        )
        annotations = [
            annotation
            for link in links
            if (annotation := self.session.get(Annotation, link.annotation_id)) is not None
        ]
        return {
            "id": judgment.id,
            "task": judgment.task,
            "slot": judgment.slot,
            "stage": judgment.stage,
            "status": judgment.status,
            "annotator": judgment.annotator,
            "submitted_at": judgment.submitted_at.isoformat() if judgment.submitted_at else None,
            "annotations": [
                {
                    "id": annotation.id,
                    "kind": annotation.kind,
                    "value": annotation.value,
                    "evidence": annotation.evidence,
                    "status": annotation.status,
                }
                for annotation in annotations
            ],
        }

    def _refresh_unit_status(self, unit: AnnotationUnit) -> None:
        judgments = list(
            self.session.scalars(
                select(GoldTaskJudgment).where(GoldTaskJudgment.unit_id == unit.id)
            )
        )
        final = [judgment for judgment in judgments if judgment.slot == "FINAL"]
        independent = [judgment for judgment in judgments if judgment.slot in {"A", "B"}]
        if final and all(judgment.status != "NOT_ANNOTATED" for judgment in final):
            unit.status = "reviewed"
        elif any(judgment.status != "NOT_ANNOTATED" for judgment in independent):
            unit.status = "annotated"
        else:
            unit.status = "pending"

    def _confirmed_annotations(self, annotation_set_id: str, unit_id: str) -> list[Annotation]:
        links = self.session.scalars(
            select(AnnotationSetAnnotation).where(
                AnnotationSetAnnotation.annotation_set_id == annotation_set_id,
                AnnotationSetAnnotation.unit_id == unit_id,
            )
        )
        confirmed: list[Annotation] = []
        for link in links:
            annotation = self.session.get(Annotation, link.annotation_id)
            if annotation is None or annotation.superseded_by:
                continue
            latest = self.session.scalar(
                select(AnnotationReview)
                .where(AnnotationReview.annotation_id == annotation.id)
                .order_by(AnnotationReview.reviewed_at.desc(), AnnotationReview.id.desc())
            )
            if latest and latest.decision == "confirmed":
                confirmed.append(annotation)
        return confirmed

    def _annotation_belongs_to_unit(self, annotation_id: str, unit_id: str) -> bool:
        return (
            self.session.scalar(
                select(func.count())
                .select_from(AnnotationSetAnnotation)
                .where(
                    AnnotationSetAnnotation.annotation_id == annotation_id,
                    AnnotationSetAnnotation.unit_id == unit_id,
                )
            )
            or 0
        ) > 0

    def _set(self, annotation_set_id: str) -> AnnotationSet:
        annotation_set = self.session.get(AnnotationSet, annotation_set_id)
        if annotation_set is None:
            raise LookupError("annotation set not found")
        return annotation_set

    @staticmethod
    def _evidence(revision: MessageRevision, spans: list[dict[str, int]]) -> list[dict[str, Any]]:
        if not spans:
            raise ValueError("at least one evidence span is required")
        output: list[dict[str, Any]] = []
        for span in spans:
            start = span["start_codepoint"]
            end = span["end_codepoint"]
            if start < 0 or end <= start or end > len(revision.text):
                raise ValueError("evidence span is outside the source revision")
            exact = revision.text[start:end]
            output.append(
                {
                    "object_type": "revision",
                    "object_id": revision.id,
                    "revision_id": revision.id,
                    "start_codepoint": start,
                    "end_codepoint": end,
                    "exact_text_hash": text_hash(exact),
                }
            )
        return output

    def _rebalance_splits(self, annotation_set: AnnotationSet) -> None:
        units = list(
            self.session.scalars(
                select(AnnotationUnit).where(AnnotationUnit.annotation_set_id == annotation_set.id)
            )
        )
        grouped: dict[str, list[AnnotationUnit]] = defaultdict(list)
        for unit in units:
            grouped[unit.group_id].append(unit)
        total = len(units)
        targets = {
            "train": round(total * 0.6),
            "development": round(total * 0.2),
            "test": total - round(total * 0.6) - round(total * 0.2),
        }
        assigned = {split: 0 for split in targets}
        seed = str(annotation_set.sampling_spec.get("seed", "gold-ru-v0"))
        groups = sorted(
            grouped.items(),
            key=lambda item: (
                -len(item[1]),
                hashlib.sha256(f"{seed}:{item[0]}".encode()).hexdigest(),
            ),
        )
        for _group_id, members in groups:
            size = len(members)
            destination = min(
                targets,
                key=lambda split: (
                    (assigned[split] + size - targets[split]) ** 2
                    - (assigned[split] - targets[split]) ** 2,
                    split,
                ),
            )
            for unit in members:
                unit.split = destination
            assigned[destination] += size
        annotation_set.sampling_spec = {
            **annotation_set.sampling_spec,
            "split_strategy": "deterministic-group-balanced-v2",
            "actual_split_counts": assigned,
        }

    def _assign_double_annotation(self, annotation_set: AnnotationSet) -> None:
        units = list(
            self.session.scalars(
                select(AnnotationUnit).where(AnnotationUnit.annotation_set_id == annotation_set.id)
            )
        )
        fraction = float(annotation_set.sampling_spec.get("double_annotation_fraction", 0))
        required = round(len(units) * fraction)
        seed = str(annotation_set.sampling_spec.get("seed", "gold-ru-v0"))
        ranked = sorted(
            units,
            key=lambda unit: hashlib.sha256(
                f"{seed}:double-annotation:{unit.object_id}".encode()
            ).hexdigest(),
        )
        selected = {unit.id for unit in ranked[:required]}
        for unit in units:
            unit.strata = {
                **unit.strata,
                "double_annotation_required": unit.id in selected,
            }
        annotation_set.sampling_spec = {
            **annotation_set.sampling_spec,
            "double_annotation_required": required,
        }

    def _create_task_judgments(self, annotation_set: AnnotationSet) -> None:
        if annotation_set.sampling_spec.get("judgment_protocol") != "blind_ab_final_v1":
            return
        tasks = list(annotation_set.sampling_spec.get("required_tasks", GOLD_TASKS))
        units = list(
            self.session.scalars(
                select(AnnotationUnit).where(AnnotationUnit.annotation_set_id == annotation_set.id)
            )
        )
        existing = set(
            self.session.execute(
                select(
                    GoldTaskJudgment.unit_id,
                    GoldTaskJudgment.task,
                    GoldTaskJudgment.slot,
                ).where(
                    GoldTaskJudgment.annotation_set_id == annotation_set.id,
                )
            )
        )
        for unit in units:
            slots = ["A", "FINAL"]
            if unit.strata.get("double_annotation_required"):
                slots.insert(1, "B")
            for task in tasks:
                for slot in slots:
                    key = (unit.id, task, slot)
                    if key in existing:
                        continue
                    self.session.add(
                        GoldTaskJudgment(
                            id=new_id(),
                            annotation_set_id=annotation_set.id,
                            unit_id=unit.id,
                            task=task,
                            slot=slot,
                            stage="adjudicated" if slot == "FINAL" else "independent",
                            status="NOT_ANNOTATED",
                            provenance={
                                "snapshot_id": annotation_set.snapshot_id,
                                "codebook_key": annotation_set.codebook_key,
                                "codebook_version": annotation_set.codebook_version,
                                "codebook_artifact_hash": annotation_set.codebook_artifact_hash,
                                "judgment_protocol": "blind_ab_final_v1",
                            },
                        )
                    )

    @staticmethod
    def _is_difficult(message: Message, revision: MessageRevision) -> bool:
        return bool(
            message.reply_to_external_id
            or "?" in revision.text
            or len(revision.text) > 180
            or revision.text.count(".") > 1
        )

    @classmethod
    def _strata(cls, message: Message, revision: MessageRevision) -> dict[str, Any]:
        length = len(revision.text)
        return {
            "length_bucket": "short" if length < 60 else "medium" if length < 180 else "long",
            "has_explicit_reply": bool(message.reply_to_external_id),
            "contains_question": "?" in revision.text,
            "difficult": cls._is_difficult(message, revision),
        }
