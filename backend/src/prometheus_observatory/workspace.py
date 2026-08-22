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
    Finding,
    MeasurementResult,
    Message,
    MessageRevision,
    Participant,
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


class WorkspaceService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def messages(self, corpus_id: str) -> list[MessageListItem]:
        rows = self.session.execute(
            select(Message, MessageRevision, Participant)
            .join(MessageRevision, MessageRevision.message_id == Message.id)
            .outerjoin(Participant, Participant.id == Message.sender_id)
            .where(Message.conversation_id.in_(self._conversation_ids(corpus_id)))
            .order_by(Message.sent_at)
        ).all()
        reply_counts = Counter(
            reply_to
            for reply_to in self.session.scalars(
                select(Message.reply_to_external_id).where(
                    Message.conversation_id.in_(self._conversation_ids(corpus_id)),
                    Message.reply_to_external_id.is_not(None),
                )
            )
        )
        return [
            MessageListItem(
                id=message.id,
                external_id=message.external_id,
                sender_id=message.sender_id,
                sender_name=participant.display_name if participant else "Система",
                sender_initials=initials(participant.display_name if participant else "Система"),
                sent_at=message.sent_at,
                text=revision.text,
                reply_count=reply_counts[message.external_id],
            )
            for message, revision, participant in rows
        ]

    def microscope(self, message_id: str) -> MicroscopeResponse:
        row = self.session.execute(
            select(Message, MessageRevision, Participant)
            .join(MessageRevision, MessageRevision.message_id == Message.id)
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
        annotations = list(
            self.session.scalars(
                select(Annotation)
                .where(Annotation.object_id.in_(span_ids + utterance_ids + [message.id]))
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
        corpus_id = self._corpus_for_message(message)
        measurement_rows = list(
            self.session.scalars(
                select(MeasurementResult)
                .where(MeasurementResult.subject_id == corpus_id)
                .order_by(MeasurementResult.created_at.desc())
            )
        )
        findings = list(
            self.session.scalars(
                select(Finding)
                .where(
                    Finding.run_id.in_(
                        select(AnalysisRun.id).where(
                            AnalysisRun.snapshot_id.in_(self._snapshot_ids(corpus_id))
                        )
                    )
                )
                .order_by(Finding.created_at.desc())
            )
        )
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
            ),
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
            ),
        ]
        supporting, counterexamples = self._comparison_cases(annotations)
        return MicroscopeResponse(
            message=MessageListItem(
                id=message.id,
                external_id=message.external_id,
                sender_id=message.sender_id,
                sender_name=participant.display_name if participant else "Система",
                sender_initials=initials(participant.display_name if participant else "Система"),
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
        return WorkspaceResponse(
            corpus=CorpusRead.model_validate(corpus),
            messages=messages,
            selected_message_id=selected.id,
            microscope=self.microscope(selected.id),
            run=RunRead.model_validate(run) if run else None,
            overview={
                "message_count": len(messages),
                "participant_count": participant_count or 0,
                "validated_language": corpus.is_validated_language,
                "epistemic_levels": ["L0", "L1", "L2", "L3", "L4"],
            },
        )

    def _comparison_cases(
        self, annotations: list[Annotation]
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
                .where(Annotation.kind.in_(["dialogue_act", "epistemic_state"]))
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
            elif label not in key_labels and len(counter) < 3:
                counter.append(item)
            if len(supporting) >= 3 and len(counter) >= 3:
                break
        return supporting, counter

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
