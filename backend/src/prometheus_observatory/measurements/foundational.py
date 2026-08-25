from __future__ import annotations

import math
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import aliased

from ..models import Message, ResponseRelation, SnapshotMessageRevision
from .base import MeasurementComputation, MeasurementContext, MeasurementPayload, MeasurementPlugin


class ParticipationShare(MeasurementPlugin):
    """Descriptive participation distribution; never a proxy for influence or power."""

    definition_id = "participation-share@1"
    version = "1"
    title = "Распределение участия"
    unit_of_analysis = "participant"

    def compute(self, context: MeasurementContext) -> MeasurementComputation:
        rows = list(
            context.session.execute(
                select(Message.id, Message.sender_id)
                .join(SnapshotMessageRevision, SnapshotMessageRevision.message_id == Message.id)
                .where(SnapshotMessageRevision.snapshot_id == context.snapshot_id)
            )
        )
        counts = Counter(sender_id for _message_id, sender_id in rows if sender_id)
        total = sum(counts.values())
        shares = (
            {participant_id: count / total for participant_id, count in counts.items()}
            if total
            else {}
        )
        entropy = -sum(value * math.log(value, 2) for value in shares.values() if value)
        return MeasurementComputation(
            payload=MeasurementPayload(
                estimate=shares,
                numerator=dict(counts),
                denominator=total,
                sample_size=total,
                uncertainty={
                    "method": "descriptive",
                    "explanation": [],
                    "entropy_bits": entropy,
                },
                missingness={
                    "messages_without_sender": sum(sender_id is None for _, sender_id in rows)
                },
            ),
            evidence=[("message", message_id) for message_id, _sender_id in rows],
        )

    def null_model(self, context: MeasurementContext) -> dict | None:
        return None


class ExplicitReplyReciprocity(MeasurementPlugin):
    """Dyadic reciprocity over explicit REPLIES_TO relations in one exact snapshot."""

    definition_id = "reply-reciprocity@1"
    version = "1"
    title = "Взаимность явных ответов"
    unit_of_analysis = "dyad"

    def compute(self, context: MeasurementContext) -> MeasurementComputation:
        source_membership = aliased(SnapshotMessageRevision)
        target_membership = aliased(SnapshotMessageRevision)
        target_message = aliased(Message)
        rows = list(
            context.session.execute(
                select(
                    ResponseRelation.id,
                    Message.sender_id,
                    target_message.sender_id,
                )
                .join(Message, Message.id == ResponseRelation.source_message_id)
                .join(target_message, target_message.id == ResponseRelation.target_message_id)
                .join(source_membership, source_membership.message_id == Message.id)
                .join(target_membership, target_membership.message_id == target_message.id)
                .where(
                    source_membership.snapshot_id == context.snapshot_id,
                    target_membership.snapshot_id == context.snapshot_id,
                    ResponseRelation.explicit.is_(True),
                    ResponseRelation.relation_type == "REPLIES_TO",
                )
            )
        )
        directed = Counter(
            (source, target)
            for _relation_id, source, target in rows
            if source and target and source != target
        )
        reciprocated = sum(
            min(count, directed.get((target, source), 0))
            for (source, target), count in directed.items()
        )
        total = sum(directed.values())
        return MeasurementComputation(
            payload=MeasurementPayload(
                estimate=reciprocated / total if total else 0,
                numerator=reciprocated,
                denominator=total,
                sample_size=total,
                uncertainty={
                    "method": "descriptive",
                    "explanation": ["Только explicit=true и relation_type=REPLIES_TO"],
                },
            ),
            evidence=[("response_relation", relation_id) for relation_id, _, _ in rows],
        )

    def null_model(self, context: MeasurementContext) -> dict | None:
        return None


def foundational_registry():
    from .base import MeasurementRegistry

    registry = MeasurementRegistry()
    registry.register(ParticipationShare())
    registry.register(ExplicitReplyReciprocity())
    return registry
