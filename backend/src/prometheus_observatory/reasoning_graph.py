from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .analyzer import DeterministicAnalyzer
from .codebooks import release_identity
from .config import get_settings
from .conversation_graph import LEXICAL_METHOD, ConversationGraphService
from .model_gateway import (
    EvidenceItem,
    LocalPairClassificationAdapter,
    ModelPolicy,
    ModelRouter,
    TaskCapabilityRegistry,
)
from .models import (
    AnalysisRun,
    AnalysisTask,
    Annotation,
    Corpus,
    CorpusSnapshot,
    DependencyFingerprint,
    DerivationEdge,
    DiscourseRelation,
    Message,
    MessageRevision,
    PropositionMention,
    PropositionRelation,
    ResponseRelation,
    Span,
    Utterance,
    new_id,
)
from .ontology import PrivacyPolicy

ANALYSIS_VERSION = "reasoning-graph-ru@0.2.0"
PREMISE = re.compile(r"\b(потому что|так как|поскольку|ведь|поэтому|следовательно)\b", re.I)
EVIDENCE = re.compile(r"\b(по данным|исследовани\w*|показыва\w*|наблюдени\w*|согласно)\b", re.I)
SUPPORT = re.compile(r"\b(соглас\w*|верно|поддержива\w*|именно|да[, ])\b", re.I)
ATTACK = re.compile(r"\b(не соглас\w*|неверно|нет[, :]|ошиб\w*|против|однако|но )\b", re.I)


class ReasoningGraphService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()

    def create(self, corpus_id: str, *, include_nli: bool = True) -> AnalysisRun:
        corpus = self.session.get(Corpus, corpus_id)
        if corpus is None:
            raise LookupError("corpus not found")
        snapshot = self._latest_snapshot(corpus_id)
        foundation = self._latest_run(snapshot.id, "deterministic-foundation")
        if foundation is None:
            foundation = DeterministicAnalyzer(self.session).analyze(corpus_id)
        conversation = self._latest_run(snapshot.id, "conversation-graph")
        if conversation is None:
            conversation = ConversationGraphService(self.session).create(
                corpus_id, include_encoder=False
            )
        release, codebook_hash = release_identity(self.session, "reasoning-graph-ru", "0.2.0")
        configuration = {
            "analysis_version": ANALYSIS_VERSION,
            "codebook_release": release,
            "codebook_artifact_hash": codebook_hash,
            "foundation_run_id": foundation.id,
            "conversation_graph_run_id": conversation.id,
            "include_nli": include_nli,
            "nli": {
                "base_url": self.settings.local_nli_base_url,
                "model": self.settings.local_nli_model,
                "model_revision": self.settings.local_nli_revision,
            },
            "nli_is_truth": False,
        }
        fingerprint = hashlib.sha256(
            json.dumps({"snapshot_id": snapshot.id, **configuration}, sort_keys=True).encode()
        ).hexdigest()
        existing = next(
            (
                run
                for run in self.session.scalars(
                    select(AnalysisRun).where(
                        AnalysisRun.snapshot_id == snapshot.id,
                        AnalysisRun.run_type == "reasoning-graph",
                    )
                )
                if run.configuration.get("fingerprint") == fingerprint
            ),
            None,
        )
        if existing:
            return existing
        run = AnalysisRun(
            id=new_id(),
            snapshot_id=snapshot.id,
            run_type="reasoning-graph",
            status="running",
            progress=0,
            configuration={**configuration, "fingerprint": fingerprint},
            started_at=datetime.now(UTC),
        )
        self.session.add(run)
        self.session.flush()
        for task_key in ("argument_components", "argument_relations", "nli_challenger"):
            task = AnalysisTask(
                id=new_id(),
                run_id=run.id,
                task_key=task_key,
                status="pending",
                progress=0,
                idempotency_key=f"{run.id}:{task_key}",
                checkpoint={},
            )
            self.session.add(task)
            self.session.flush()
            self.session.add(
                DependencyFingerprint(
                    id=new_id(),
                    task_id=task.id,
                    dependency_type="reasoning_graph_configuration",
                    dependency_key=task_key,
                    fingerprint=fingerprint,
                )
            )
        self.session.commit()
        try:
            propositions = self._propositions(foundation.id)
            self._components(run, propositions)
            pairs = self._candidate_pairs(conversation.id, propositions)
            self._argument_relations(run, pairs)
            try:
                self._nli(run, corpus_id, pairs)
            except Exception as nli_error:
                self.session.rollback()
                run = self._run(run.id)
                task = self._tasks(run.id)["nli_challenger"]
                task.status = "failed"
                task.error = str(nli_error)
                run.configuration = {**run.configuration, "nli_warning": str(nli_error)}
                self.session.commit()
            run.status = "completed"
            run.progress = 1
            run.completed_at = datetime.now(UTC)
            self.session.commit()
            return run
        except Exception as error:
            self.session.rollback()
            run = self.session.get(AnalysisRun, run.id)
            if run is not None:
                run.status = "failed"
                run.error = str(error)
                self.session.commit()
            raise

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

    def graph(self, corpus_id: str, *, run_id: str | None = None) -> dict[str, Any]:
        snapshot = self._latest_snapshot(corpus_id)
        run = self._run(run_id) if run_id else self._latest_run(snapshot.id, "reasoning-graph")
        if run is None:
            raise LookupError("reasoning graph run not found")
        relations = list(
            self.session.scalars(
                select(PropositionRelation)
                .where(PropositionRelation.run_id == run.id)
                .order_by(PropositionRelation.created_at, PropositionRelation.id)
            )
        )
        proposition_ids = {
            proposition_id
            for relation in relations
            for proposition_id in (
                relation.source_proposition_id,
                relation.target_proposition_id,
            )
        }
        propositions = (
            {
                item.id: item
                for item in self.session.scalars(
                    select(PropositionMention).where(PropositionMention.id.in_(proposition_ids))
                )
            }
            if proposition_ids
            else {}
        )
        annotations = list(
            self.session.scalars(
                select(Annotation)
                .where(
                    Annotation.run_id == run.id,
                    Annotation.kind.in_(
                        ["argument_component", "argument_relation_candidate", "nli_relation"]
                    ),
                )
                .order_by(Annotation.created_at, Annotation.id)
            )
        )
        return {
            "run": self.run_payload(run.id),
            "propositions": [
                {
                    "id": item.id,
                    "text": item.normalized_text,
                    "type": item.proposition_type,
                }
                for item in propositions.values()
            ],
            "relations": [
                {
                    "id": relation.id,
                    "annotation_id": relation.annotation_id,
                    "source_proposition_id": relation.source_proposition_id,
                    "target_proposition_id": relation.target_proposition_id,
                    "relation_type": relation.relation_type,
                    "method": relation.scoring_method,
                    "raw_score": relation.confidence,
                    "status": relation.status,
                }
                for relation in relations
            ],
            "argument_components": [
                {
                    "id": annotation.id,
                    "proposition_id": annotation.value["proposition_id"],
                    "component_type": annotation.value["component_type"],
                    "status": annotation.status,
                    "evidence": annotation.evidence,
                }
                for annotation in annotations
                if annotation.kind == "argument_component"
            ],
            "relation_candidates": [
                {
                    "id": annotation.id,
                    **annotation.value,
                    "status": annotation.status,
                    "evidence": annotation.evidence,
                }
                for annotation in annotations
                if annotation.kind == "argument_relation_candidate"
            ],
            "nli_challengers": [
                {
                    "id": annotation.id,
                    **annotation.value,
                    "status": annotation.status,
                    "evidence": annotation.evidence,
                    "calibrated_confidence": annotation.calibrated_confidence,
                }
                for annotation in annotations
                if annotation.kind == "nli_relation"
            ],
            "guardrail": (
                "NLI and argument links are provisional evidence channels, not truth or causality."
            ),
        }

    def _propositions(self, foundation_run_id: str) -> list[dict[str, Any]]:
        return [
            {
                "proposition": proposition,
                "annotation": annotation,
                "span": span,
                "message_id": revision.message_id,
                "text": proposition.normalized_text,
            }
            for proposition, annotation, span, utterance, revision in self.session.execute(
                select(PropositionMention, Annotation, Span, Utterance, MessageRevision)
                .join(Annotation, Annotation.id == PropositionMention.annotation_id)
                .join(Span, Span.id == PropositionMention.span_id)
                .join(Utterance, Utterance.id == PropositionMention.utterance_id)
                .join(MessageRevision, MessageRevision.id == Utterance.revision_id)
                .where(Annotation.run_id == foundation_run_id)
                .order_by(MessageRevision.message_id, Span.start_codepoint)
            )
        ]

    def _components(self, run: AnalysisRun, propositions: list[dict[str, Any]]) -> None:
        task = self._tasks(run.id)["argument_components"]
        task.status = "running"
        for index, item in enumerate(propositions, start=1):
            text = item["text"]
            component = (
                "EVIDENCE"
                if EVIDENCE.search(text)
                else "PREMISE"
                if PREMISE.search(text)
                else "CLAIM"
            )
            source = item["annotation"]
            annotation = self._annotation(
                run,
                item["proposition"].id,
                "argument_component",
                {"component_type": component, "proposition_id": item["proposition"].id},
                source.evidence,
                "argument-component-rules@0.2.0",
            )
            self.session.add(annotation)
            self.session.flush()
            self._derive(item["proposition"].id, annotation.id, run.id, "CLASSIFIES_COMPONENT")
            task.progress = index / len(propositions) if propositions else 1
        task.status = "completed"
        task.progress = 1
        self.session.commit()

    def _candidate_pairs(
        self, conversation_run_id: str, propositions: list[dict[str, Any]]
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        by_message: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for proposition in propositions:
            by_message[proposition["message_id"]].append(proposition)
        source_messages = {
            message.id: message
            for message in self.session.scalars(select(Message).where(Message.id.in_(by_message)))
        }
        message_pairs: set[tuple[str, str]] = set()
        for relation in self.session.scalars(
            select(ResponseRelation).where(
                ResponseRelation.run_id == conversation_run_id,
                ResponseRelation.scoring_method == LEXICAL_METHOD,
                ResponseRelation.rank == 1,
                ResponseRelation.confidence >= 0.15,
            )
        ):
            source = source_messages.get(relation.source_message_id)
            if source is not None and source.reply_to_external_id is None:
                message_pairs.add((relation.source_message_id, relation.target_message_id))
        self._run(conversation_run_id, expected_type="conversation-graph")
        sources = list(
            self.session.scalars(
                select(Message).where(
                    Message.id.in_(by_message), Message.reply_to_external_id.is_not(None)
                )
            )
        )
        for source in sources:
            target = self.session.scalar(
                select(Message).where(
                    Message.conversation_id == source.conversation_id,
                    Message.external_id == source.reply_to_external_id,
                )
            )
            if target and target.id in by_message:
                message_pairs.add((source.id, target.id))
        return [
            (source, target)
            for source_message_id, target_message_id in sorted(message_pairs)
            for source in by_message.get(source_message_id, [])[:5]
            for target in by_message.get(target_message_id, [])[:5]
        ]

    def _argument_relations(
        self, run: AnalysisRun, pairs: list[tuple[dict[str, Any], dict[str, Any]]]
    ) -> None:
        task = self._tasks(run.id)["argument_relations"]
        task.status = "running"
        discourse: dict[tuple[str, str], set[str]] = defaultdict(set)
        for item in self.session.scalars(
            select(DiscourseRelation).where(
                DiscourseRelation.run_id == run.configuration["conversation_graph_run_id"]
            )
        ):
            discourse[(item.source_message_id, item.target_message_id)].add(item.relation_type)
        source_propositions: dict[tuple[str, str], set[str]] = defaultdict(set)
        target_propositions: dict[tuple[str, str], set[str]] = defaultdict(set)
        for source, target in pairs:
            message_pair = (source["message_id"], target["message_id"])
            source_propositions[message_pair].add(source["proposition"].id)
            target_propositions[message_pair].add(target["proposition"].id)
        for index, (source, target) in enumerate(pairs, start=1):
            relation_type = None
            message_pair = (source["message_id"], target["message_id"])
            discourse_types = discourse.get(message_pair, set())
            ambiguous_endpoints = (
                len(source_propositions[message_pair]) > 1
                or len(target_propositions[message_pair]) > 1
            )
            if not ambiguous_endpoints and (
                ATTACK.search(source["text"])
                or discourse_types
                & {
                    "REJECTS",
                    "CORRECTS",
                    "CONTRASTS",
                }
            ):
                relation_type = "ATTACKS"
            elif not ambiguous_endpoints and (
                SUPPORT.search(source["text"])
                or PREMISE.search(source["text"])
                or discourse_types & {"ACCEPTS", "ANSWERS", "ELABORATES"}
            ):
                relation_type = "SUPPORTS"
            candidate = self._annotation(
                run,
                source["proposition"].id,
                "argument_relation_candidate",
                {
                    "source_proposition_id": source["proposition"].id,
                    "target_proposition_id": target["proposition"].id,
                    "accepted_relation": None,
                    "proposal_eligible": not ambiguous_endpoints,
                    "eligibility_reasons": (
                        ["single_proposition_endpoints"]
                        if not ambiguous_endpoints
                        else ["ambiguous_multi_proposition_endpoints"]
                    ),
                },
                source["annotation"].evidence + target["annotation"].evidence,
                "argument-pair-candidates@0.2.0",
            )
            self.session.add(candidate)
            if relation_type:
                annotation = self._annotation(
                    run,
                    source["proposition"].id,
                    "argument_relation",
                    {
                        "source_proposition_id": source["proposition"].id,
                        "target_proposition_id": target["proposition"].id,
                        "relation_type": relation_type,
                        "accepted_edge": False,
                    },
                    source["annotation"].evidence + target["annotation"].evidence,
                    "argument-relation-rules@0.2.0",
                )
                self.session.add(annotation)
                self.session.flush()
                self.session.add(
                    PropositionRelation(
                        id=new_id(),
                        snapshot_id=run.snapshot_id,
                        run_id=run.id,
                        source_proposition_id=source["proposition"].id,
                        target_proposition_id=target["proposition"].id,
                        relation_type=relation_type,
                        annotation_id=annotation.id,
                        confidence=None,
                        scoring_method="argument-relation-rules@0.2.0",
                        status="provisional",
                    )
                )
            task.progress = index / len(pairs) if pairs else 1
        task.status = "completed"
        task.progress = 1
        self.session.commit()

    def _nli(
        self,
        run: AnalysisRun,
        corpus_id: str,
        pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    ) -> None:
        task = self._tasks(run.id)["nli_challenger"]
        config = run.configuration["nli"]
        if not run.configuration["include_nli"]:
            task.status = "disabled"
            task.progress = 1
            return
        if not config.get("base_url") or config.get("model_revision") == "unversioned":
            task.status = "unavailable"
            task.progress = 1
            task.error = "pinned PROMETHEUS_LOCAL_NLI endpoint is not configured"
            return
        adapter = LocalPairClassificationAdapter(
            base_url=config["base_url"],
            model=config["model"],
            model_revision=config["model_revision"],
        )
        registry = TaskCapabilityRegistry()
        registry.register("nli_proposition_pairs", minimum_context=1024)
        router = ModelRouter(self.session, registry)
        task.status = "running"
        for start in range(0, len(pairs), 32):
            batch = pairs[start : start + 32]
            pair_payloads = [
                {
                    "pair_id": f"{source['proposition'].id}:{target['proposition'].id}",
                    "premise": target["text"],
                    "hypothesis": source["text"],
                }
                for source, target in batch
            ]
            result = router.classify_pairs(
                corpus_id=corpus_id,
                run_id=run.id,
                task="nli_proposition_pairs",
                adapter=adapter,
                items=[
                    EvidenceItem(
                        evidence_id=item["pair_id"], text=f"{item['premise']}\n{item['hypothesis']}"
                    )
                    for item in pair_payloads
                ],
                pairs=pair_payloads,
                policy=ModelPolicy(privacy_policy=PrivacyPolicy.LOCAL_ONLY, max_cost=0),
                reason="local NLI challenger over proposition pairs",
            )
            for (source, target), classification in zip(batch, result.classifications, strict=True):
                annotation = self._annotation(
                    run,
                    source["proposition"].id,
                    "nli_relation",
                    {
                        "source_proposition_id": source["proposition"].id,
                        "target_proposition_id": target["proposition"].id,
                        "label": classification["label"],
                        "scores": classification["scores"],
                        "truth_status": "not_determined",
                    },
                    source["annotation"].evidence + target["annotation"].evidence,
                    "local-nli-challenger",
                    model=adapter.model,
                    model_revision=adapter.model_revision,
                )
                self.session.add(annotation)
                self.session.flush()
                self.session.add(
                    PropositionRelation(
                        id=new_id(),
                        snapshot_id=run.snapshot_id,
                        run_id=run.id,
                        source_proposition_id=source["proposition"].id,
                        target_proposition_id=target["proposition"].id,
                        relation_type=f"NLI_{classification['label']}",
                        annotation_id=annotation.id,
                        confidence=float(classification["scores"][classification["label"]]),
                        scoring_method="local-nli-challenger",
                        status="provisional",
                    )
                )
            task.checkpoint = {"processed_pairs": min(start + 32, len(pairs)), "total": len(pairs)}
            task.progress = min(start + 32, len(pairs)) / len(pairs) if pairs else 1
            self.session.commit()
        task.status = "completed"
        task.progress = 1

    def _annotation(
        self,
        run: AnalysisRun,
        object_id: str,
        kind: str,
        value: dict[str, Any],
        evidence: list[dict[str, Any]],
        method: str,
        *,
        model: str = "rules-ru-v1",
        model_revision: str | None = None,
    ) -> Annotation:
        return Annotation(
            id=new_id(),
            snapshot_id=run.snapshot_id,
            run_id=run.id,
            object_type="proposition",
            object_id=object_id,
            kind=kind,
            value=value,
            evidence=evidence,
            status="provisional",
            raw_confidence=None,
            calibrated_confidence=None,
            alternatives=[],
            provenance={
                "corpus_snapshot_id": run.snapshot_id,
                "ontology_version": self.settings.ontology_version,
                "codebook_version": run.configuration["codebook_release"],
                "codebook_artifact_hash": run.configuration["codebook_artifact_hash"],
                "pipeline_version": ANALYSIS_VERSION,
                "model_provider": "deterministic" if model == "rules-ru-v1" else "local",
                "model": model,
                "model_revision": model_revision,
                "method": method,
                "analysis_run_id": run.id,
                "created_at": datetime.now(UTC).isoformat(),
            },
        )

    def _derive(self, proposition_id: str, annotation_id: str, run_id: str, relation: str) -> None:
        self.session.add(
            DerivationEdge(
                id=new_id(),
                source_type="proposition",
                source_id=proposition_id,
                target_type="annotation",
                target_id=annotation_id,
                relation=relation,
                run_id=run_id,
            )
        )

    def _latest_snapshot(self, corpus_id: str) -> CorpusSnapshot:
        snapshot = self.session.scalar(
            select(CorpusSnapshot)
            .where(CorpusSnapshot.corpus_id == corpus_id)
            .order_by(CorpusSnapshot.created_at.desc(), CorpusSnapshot.id.desc())
        )
        if snapshot is None:
            raise LookupError("corpus snapshot not found")
        return snapshot

    def _latest_run(self, snapshot_id: str, run_type: str) -> AnalysisRun | None:
        return self.session.scalar(
            select(AnalysisRun)
            .where(
                AnalysisRun.snapshot_id == snapshot_id,
                AnalysisRun.run_type == run_type,
                AnalysisRun.status == "completed",
            )
            .order_by(AnalysisRun.created_at.desc())
        )

    def _run(self, run_id: str, expected_type: str = "reasoning-graph") -> AnalysisRun:
        run = self.session.get(AnalysisRun, run_id)
        if run is None or run.run_type != expected_type:
            raise LookupError(f"{expected_type} run not found")
        return run

    def _tasks(self, run_id: str) -> dict[str, AnalysisTask]:
        return {
            task.task_key: task
            for task in self.session.scalars(
                select(AnalysisTask).where(AnalysisTask.run_id == run_id)
            )
        }
