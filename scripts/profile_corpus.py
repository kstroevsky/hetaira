from __future__ import annotations

import argparse
import json
import math
from collections import Counter

from prometheus_observatory.database import SessionLocal
from prometheus_observatory.models import (
    AttachmentRef,
    Conversation,
    ConversationSession,
    Corpus,
    CorpusSnapshot,
    Episode,
    Message,
    MessageRevision,
    Participant,
    ResponseRelation,
    SnapshotMessageRevision,
)
from sqlalchemy import func, select, text


def profile(corpus_id: str, terms: list[str]) -> dict:
    with SessionLocal() as session:
        corpus = session.get(Corpus, corpus_id)
        if corpus is None:
            raise SystemExit("Corpus not found")
        snapshot = session.scalar(
            select(CorpusSnapshot)
            .where(CorpusSnapshot.corpus_id == corpus.id)
            .order_by(CorpusSnapshot.created_at.desc(), CorpusSnapshot.id.desc())
        )
        if snapshot is None:
            raise SystemExit("Corpus has no snapshot")
        base = (
            select(Message, MessageRevision)
            .join(
                SnapshotMessageRevision,
                SnapshotMessageRevision.message_id == Message.id,
            )
            .join(
                MessageRevision,
                MessageRevision.id == SnapshotMessageRevision.revision_id,
            )
            .where(SnapshotMessageRevision.snapshot_id == snapshot.id)
        ).subquery()
        totals = session.execute(
            select(
                func.count().label("messages"),
                func.count(func.distinct(base.c.sender_id)).label("participants"),
                func.min(base.c.sent_at).label("first"),
                func.max(base.c.sent_at).label("last"),
                func.avg(func.length(base.c.text)).label("mean_length"),
                func.count()
                .filter(base.c.message_type == "service")
                .label("service_events"),
            ).select_from(base)
        ).one()
        participant_rows = session.execute(
            select(
                Participant.display_name,
                func.count().label("messages"),
            )
            .select_from(base)
            .join(Participant, Participant.id == base.c.sender_id)
            .group_by(Participant.id, Participant.display_name)
            .order_by(func.count().desc())
        ).all()
        participant_total = sum(row.messages for row in participant_rows)
        shares = [
            row.messages / participant_total
            for row in participant_rows
            if participant_total
        ]
        participation_entropy = -sum(
            share * math.log2(share) for share in shares if share
        )
        top_participants = [
            {
                "participant": row.display_name,
                "messages": row.messages,
                "share": row.messages / participant_total if participant_total else 0,
            }
            for row in participant_rows[:10]
        ]
        explicit_replies = (
            session.scalar(
                select(func.count())
                .select_from(ResponseRelation)
                .join(Message, Message.id == ResponseRelation.source_message_id)
                .join(
                    SnapshotMessageRevision,
                    SnapshotMessageRevision.message_id == Message.id,
                )
                .where(
                    SnapshotMessageRevision.snapshot_id == snapshot.id,
                    ResponseRelation.explicit.is_(True),
                    ResponseRelation.relation_type == "REPLIES_TO",
                )
            )
            or 0
        )
        reply_marked = (
            session.scalar(
                select(func.count())
                .select_from(base)
                .where(base.c.reply_to_external_id.is_not(None))
            )
            or 0
        )
        session_count = (
            session.scalar(
                select(func.count())
                .select_from(ConversationSession)
                .join(
                    Conversation, Conversation.id == ConversationSession.conversation_id
                )
                .where(Conversation.corpus_id == corpus.id)
            )
            or 0
        )
        episode_count = (
            session.scalar(
                select(func.count())
                .select_from(Episode)
                .join(ConversationSession, ConversationSession.id == Episode.session_id)
                .join(
                    Conversation, Conversation.id == ConversationSession.conversation_id
                )
                .where(Conversation.corpus_id == corpus.id)
            )
            or 0
        )
        attachments = session.execute(
            select(AttachmentRef.source_metadata)
            .join(Message, Message.id == AttachmentRef.message_id)
            .join(
                SnapshotMessageRevision,
                SnapshotMessageRevision.message_id == Message.id,
            )
            .where(SnapshotMessageRevision.snapshot_id == snapshot.id)
        ).scalars()
        attachment_states = Counter(
            "included" if metadata.get("included") else "not_included"
            for metadata in attachments
        )
        monthly = []
        term_counts: dict[str, int] = {}
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            monthly = [
                {"month": row.month.date().isoformat(), "messages": row.messages}
                for row in session.execute(
                    text(
                        """
                        SELECT date_trunc('month', m.sent_at) AS month, count(*) AS messages
                        FROM snapshot_message_revisions smr
                        JOIN messages m ON m.id = smr.message_id
                        WHERE smr.snapshot_id = :snapshot_id
                        GROUP BY 1 ORDER BY 1
                        """
                    ),
                    {"snapshot_id": snapshot.id},
                )
            ]
            for term in terms:
                term_counts[term] = session.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM snapshot_message_revisions smr
                        JOIN message_revisions mr ON mr.id = smr.revision_id
                        WHERE smr.snapshot_id = :snapshot_id
                          AND to_tsvector('russian'::regconfig, mr.text)
                              @@ plainto_tsquery('russian'::regconfig, :term)
                        """
                    ),
                    {"snapshot_id": snapshot.id, "term": term},
                ).scalar_one()
        return {
            "schema": "hetaira.corpus-profile.v1",
            "epistemic_status": "descriptive",
            "corpus_id": corpus.id,
            "snapshot_id": snapshot.id,
            "manifest_hash": snapshot.manifest_hash,
            "privacy_policy": corpus.privacy_policy,
            "messages": totals.messages,
            "participants": totals.participants,
            "first_timestamp": totals.first.isoformat() if totals.first else None,
            "last_timestamp": totals.last.isoformat() if totals.last else None,
            "mean_message_length": float(totals.mean_length or 0),
            "service_events": int(totals.service_events or 0),
            "reply_targets_marked": reply_marked,
            "reply_targets_resolved": explicit_replies,
            "reply_targets_missing_from_export": reply_marked - explicit_replies,
            "resolved_reply_rate": explicit_replies / totals.messages
            if totals.messages
            else 0,
            "sessions_8h": session_count,
            "episodes": episode_count,
            "participation_entropy_bits": participation_entropy,
            "top_participants": top_participants,
            "attachment_states": dict(attachment_states),
            "monthly_activity": monthly,
            "term_message_counts": term_counts,
            "warnings": [
                "Telegram HTML timezone is unspecified; temporal values use a recorded UTC placeholder.",
                "Term counts are lexical retrieval diagnostics, not prevalence or clinical measures.",
            ],
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build a source-scoped descriptive corpus profile"
    )
    parser.add_argument("corpus_id")
    parser.add_argument("--term", action="append", default=[])
    arguments = parser.parse_args()
    print(
        json.dumps(
            profile(arguments.corpus_id, arguments.term),
            ensure_ascii=False,
            indent=2,
        )
    )
