from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    AnalysisRun,
    Annotation,
    Corpus,
    CorpusSnapshot,
    DerivationEdge,
    Finding,
    MeasurementResult,
    Message,
    MessageRevision,
    Participant,
    PropositionMention,
    SnapshotMessageRevision,
    Span,
    Utterance,
)
from .schemas import (
    AnnotationRead,
    CorpusRead,
    EvidenceStage,
    MessageListItem,
    MicroscopeResponse,
    MicroscopeSection,
    RunRead,
    WorkspaceResponse,
)
from .text import initials

SECTION_TITLES = {
    "dialogue_act": "Диалоговые акты",
    "proposition": "Пропозиции",
    "stance": "Позиция",
    "epistemic_state": "Эпистемика",
    "grounding": "Общее знание",
    "argumentation": "Аргументация",
}


def sender_display_name(message: Message, participant: Participant | None) -> str:
    if participant is not None:
        return participant.display_name
    source_name = (message.raw_metadata or {}).get("source_sender_name")
    if isinstance(source_name, str) and source_name.strip():
        return source_name
    return "Система" if message.message_type == "service" else "Неизвестный отправитель"


class WorkspaceService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def messages(
        self,
        corpus_id: str,
        snapshot_id: str | None = None,
        *,
        limit: int = 200,
    ) -> list[MessageListItem]:
        snapshot = self._snapshot(corpus_id, snapshot_id)
        rows = self.session.execute(
            select(Message, MessageRevision, Participant)
            .join(SnapshotMessageRevision, SnapshotMessageRevision.message_id == Message.id)
            .join(MessageRevision, MessageRevision.id == SnapshotMessageRevision.revision_id)
            .outerjoin(Participant, Participant.id == Message.sender_id)
            .where(SnapshotMessageRevision.snapshot_id == snapshot.id)
            .order_by(Message.sent_at)
            .limit(min(max(limit, 1), 500))
        ).all()
        external_ids = [message.external_id for message, _revision, _participant in rows]
        reply_counts = Counter(
            {
                reply_to: count
                for reply_to, count in self.session.execute(
                    select(Message.reply_to_external_id, func.count())
                    .where(
                        Message.id.in_(
                            select(SnapshotMessageRevision.message_id).where(
                                SnapshotMessageRevision.snapshot_id == snapshot.id
                            )
                        ),
                        Message.reply_to_external_id.in_(external_ids),
                    )
                    .group_by(Message.reply_to_external_id)
                )
            }
        )
        return [
            MessageListItem(
                id=message.id,
                external_id=message.external_id,
                sender_id=message.sender_id,
                sender_name=sender_display_name(message, participant),
                sender_initials=initials(sender_display_name(message, participant)),
                sent_at=message.sent_at,
                text=revision.text,
                reply_count=reply_counts[message.external_id],
            )
            for message, revision, participant in rows
        ]

    def microscope(self, message_id: str) -> MicroscopeResponse:
        membership = self.session.scalar(
            select(SnapshotMessageRevision)
            .join(CorpusSnapshot, CorpusSnapshot.id == SnapshotMessageRevision.snapshot_id)
            .where(SnapshotMessageRevision.message_id == message_id)
            .order_by(CorpusSnapshot.created_at.desc(), CorpusSnapshot.id.desc())
        )
        if membership is None:
            raise LookupError("message is not present in any snapshot")
        row = self.session.execute(
            select(Message, MessageRevision, Participant)
            .select_from(Message)
            .join(MessageRevision, MessageRevision.id == membership.revision_id)
            .outerjoin(Participant, Participant.id == Message.sender_id)
            .where(Message.id == message_id)
        ).one_or_none()
        if row is None:
            raise LookupError("message not found")
        message, revision, participant = row
        span_ids = list(
            self.session.scalars(select(Span.id).where(Span.revision_id == revision.id))
        )
        utterance_ids = list(
            self.session.scalars(select(Utterance.id).where(Utterance.revision_id == revision.id))
        )
        proposition_ids = list(
            self.session.scalars(
                select(PropositionMention.id).where(
                    PropositionMention.utterance_id.in_(utterance_ids)
                )
            )
        )
        annotations = list(
            self.session.scalars(
                select(Annotation)
                .where(
                    Annotation.snapshot_id == membership.snapshot_id,
                    Annotation.superseded_by.is_(None),
                    Annotation.object_id.in_(
                        span_ids + utterance_ids + proposition_ids + [message.id]
                    ),
                )
                .order_by(Annotation.created_at)
            )
        )
        grouped: dict[str, list[AnnotationRead]] = {key: [] for key in SECTION_TITLES}
        for annotation in annotations:
            if annotation.kind in grouped:
                grouped[annotation.kind].append(AnnotationRead.model_validate(annotation))
        sections = [
            MicroscopeSection(key=key, title=title, annotations=grouped[key])
            for key, title in SECTION_TITLES.items()
        ]
        connected = self._connected_derivations(
            membership.snapshot_id, message.id, revision.id, span_ids
        )
        measurement_rows = [
            item
            for result_id in connected.get("measurement", set())
            if (item := self.session.get(MeasurementResult, result_id)) is not None
        ]
        findings = [
            item
            for finding_id in connected.get("finding", set())
            if (item := self.session.get(Finding, finding_id)) is not None
        ]
        evidence_chain = [
            EvidenceStage(
                level="L0",
                title="Источник",
                items=[
                    {
                        "message_id": message.id,
                        "external_id": message.external_id,
                        "timestamp": message.sent_at.isoformat(),
                        "text_hash": revision.text_hash,
                    }
                ],
            ),
            EvidenceStage(
                level="L1",
                title="Наблюдение",
                items=[
                    {
                        "kind": annotation.kind,
                        "value": annotation.value,
                        "status": annotation.status,
                        "confidence": annotation.raw_confidence,
                    }
                    for annotation in annotations
                ],
            ),
        ]
        if measurement_rows:
            evidence_chain.append(
                EvidenceStage(
                    level="L2",
                    title="Измерение",
                    items=[
                        {
                            "definition_id": result.definition_id,
                            "estimate": result.result.get("estimate"),
                            "sample_size": result.result.get("sample_size"),
                        }
                        for result in measurement_rows[:3]
                    ],
                )
            )
        if findings:
            evidence_chain.append(
                EvidenceStage(
                    level="L3",
                    title="Интерпретация",
                    items=[
                        {
                            "claim": finding.claim,
                            "causal_status": finding.causal_status,
                            "warning": (finding.alternative_explanations or [None])[0],
                        }
                        for finding in findings[:2]
                    ],
                )
            )
        supporting, counterexamples = self._comparison_cases(membership.snapshot_id, annotations)
        return MicroscopeResponse(
            message=MessageListItem(
                id=message.id,
                external_id=message.external_id,
                sender_id=message.sender_id,
                sender_name=sender_display_name(message, participant),
                sender_initials=initials(sender_display_name(message, participant)),
                sent_at=message.sent_at,
                text=revision.text,
            ),
            revision_id=revision.id,
            text_hash=revision.text_hash,
            sections=sections,
            evidence_chain=evidence_chain,
            supporting_cases=supporting,
            counterexamples=counterexamples,
        )

    def workspace(self, corpus_id: str | None = None) -> WorkspaceResponse:
        corpus = (
            self.session.get(Corpus, corpus_id)
            if corpus_id
            else self.session.scalar(
                select(Corpus).where(Corpus.language == "ru").order_by(Corpus.created_at)
            )
        )
        if corpus is None:
            raise LookupError("no corpus available")
        messages = self.messages(corpus.id)
        if not messages:
            raise LookupError("corpus has no messages")
        selected = messages[min(4, len(messages) - 1)]
        selected.selected = True
        run = self.session.scalar(
            select(AnalysisRun)
            .where(AnalysisRun.snapshot_id.in_(self._snapshot_ids(corpus.id)))
            .order_by(AnalysisRun.created_at.desc())
        )
        participant_count = self.session.scalar(
            select(func.count()).select_from(Participant).where(Participant.corpus_id == corpus.id)
        )
        snapshot = self._snapshot(corpus.id, None)
        return WorkspaceResponse(
            corpus=CorpusRead.model_validate(corpus),
            messages=messages,
            selected_message_id=selected.id,
            microscope=self.microscope(selected.id),
            run=RunRead.model_validate(run) if run else None,
            overview={
                "message_count": snapshot.message_count,
                "loaded_message_count": len(messages),
                "participant_count": participant_count or 0,
                "validated_language": corpus.is_validated_language,
                "epistemic_levels": ["L0", "L1", "L2", "L3", "L4"],
                "snapshot_id": snapshot.id,
                "snapshot_manifest_hash": snapshot.manifest_hash,
            },
        )

    def _comparison_cases(
        self, snapshot_id: str, annotations: list[Annotation]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        key_labels = {
            annotation.value.get("label")
            for annotation in annotations
            if annotation.kind in {"dialogue_act", "epistemic_state"}
        }
        if not key_labels:
            return [], []
        all_annotations = list(
            self.session.scalars(
                select(Annotation)
                .where(
                    Annotation.snapshot_id == snapshot_id,
                    Annotation.superseded_by.is_(None),
                    Annotation.kind.in_(["dialogue_act", "epistemic_state"]),
                )
                .order_by(Annotation.raw_confidence.desc())
            )
        )
        supporting: list[dict[str, Any]] = []
        counter: list[dict[str, Any]] = []
        for annotation in all_annotations:
            label = annotation.value.get("label")
            evidence = annotation.evidence[0] if annotation.evidence else None
            if not evidence:
                continue
            span = self.session.get(Span, evidence.get("object_id"))
            if not span:
                continue
            item = {
                "annotation_id": annotation.id,
                "label": label,
                "text": span.exact_text,
                "confidence": annotation.raw_confidence,
            }
            if label in key_labels and len(supporting) < 3:
                supporting.append(item)
            if any(alternative.get("hard_negative") for alternative in annotation.alternatives):
                counter.append(item)
            if len(supporting) >= 3 and len(counter) >= 3:
                break
        return supporting, counter

    def _snapshot(self, corpus_id: str, snapshot_id: str | None) -> CorpusSnapshot:
        snapshot = (
            self.session.get(CorpusSnapshot, snapshot_id)
            if snapshot_id
            else self.session.scalar(
                select(CorpusSnapshot)
                .where(CorpusSnapshot.corpus_id == corpus_id)
                .order_by(CorpusSnapshot.created_at.desc(), CorpusSnapshot.id.desc())
            )
        )
        if snapshot is None or snapshot.corpus_id != corpus_id:
            raise LookupError("snapshot not found for corpus")
        return snapshot

    def _connected_derivations(
        self, snapshot_id: str, message_id: str, revision_id: str, span_ids: list[str]
    ) -> dict[str, set[str]]:
        run_ids = select(AnalysisRun.id).where(AnalysisRun.snapshot_id == snapshot_id)
        connected: dict[str, set[str]] = {
            "message": {message_id},
            "revision": {revision_id},
            "span": set(span_ids),
        }
        frontier = {(kind, item_id) for kind, ids in connected.items() for item_id in ids}
        while frontier:
            next_frontier: set[tuple[str, str]] = set()
            for source_type, source_id in frontier:
                edges = self.session.scalars(
                    select(DerivationEdge).where(
                        DerivationEdge.run_id.in_(run_ids),
                        DerivationEdge.source_type == source_type,
                        DerivationEdge.source_id == source_id,
                    )
                )
                for edge in edges:
                    known = connected.setdefault(edge.target_type, set())
                    if edge.target_id not in known:
                        known.add(edge.target_id)
                        next_frontier.add((edge.target_type, edge.target_id))
            frontier = next_frontier
        return connected

    def _conversation_ids(self, corpus_id: str):
        from .models import Conversation

        return select(Conversation.id).where(Conversation.corpus_id == corpus_id)

    def _snapshot_ids(self, corpus_id: str):
        return select(CorpusSnapshot.id).where(CorpusSnapshot.corpus_id == corpus_id)

    def _corpus_for_message(self, message: Message) -> str:
        from .models import Conversation

        corpus_id = self.session.scalar(
            select(Conversation.corpus_id).where(Conversation.id == message.conversation_id)
        )
        if corpus_id is None:
            raise LookupError("message conversation is missing")
        return corpus_id
