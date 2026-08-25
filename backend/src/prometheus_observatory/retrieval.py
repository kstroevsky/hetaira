from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .models import (
    CorpusSnapshot,
    Message,
    MessageRevision,
    Participant,
    RetrievalTrace,
    SnapshotMessageRevision,
)
from .text import initials

TOKEN_PATTERN = re.compile(r"[\wёЁ-]+", re.UNICODE)


def tokens(value: str) -> list[str]:
    return [token.casefold() for token in TOKEN_PATTERN.findall(value)]


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    message_id: str
    revision_id: str
    sender_name: str
    sender_initials: str
    sent_at: datetime
    text: str
    lexical_score: float
    exact_match: bool

    def as_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "revision_id": self.revision_id,
            "sender_name": self.sender_name,
            "sender_initials": self.sender_initials,
            "sent_at": self.sent_at.isoformat(),
            "text": self.text,
            "score": self.lexical_score,
            "exact_match": self.exact_match,
        }


class HybridRetriever:
    """Traceable retrieval seam that preserves lexical evidence and can accept dense scores."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def search(
        self,
        corpus_id: str,
        query: str,
        *,
        limit: int = 20,
        participant_id: str | None = None,
        snapshot_id: str | None = None,
    ) -> tuple[RetrievalTrace, list[RetrievalHit]]:
        query_terms = tokens(query)
        if not query_terms:
            raise ValueError("query must contain searchable terms")
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
            raise ValueError("snapshot does not belong to corpus")
        statement = (
            select(Message, MessageRevision, Participant)
            .join(SnapshotMessageRevision, SnapshotMessageRevision.message_id == Message.id)
            .join(MessageRevision, MessageRevision.id == SnapshotMessageRevision.revision_id)
            .outerjoin(Participant, Participant.id == Message.sender_id)
            .where(SnapshotMessageRevision.snapshot_id == snapshot.id)
        )
        if participant_id:
            statement = statement.where(Message.sender_id == participant_id)
        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            query_expression = func.plainto_tsquery("russian", query)
            vector = func.to_tsvector("russian", MessageRevision.text)
            statement = statement.where(vector.op("@@")(query_expression)).order_by(
                func.ts_rank(vector, query_expression).desc()
            )
        else:
            statement = statement.where(
                or_(*(MessageRevision.text.ilike(f"%{term}%") for term in query_terms))
            )
        rows = self.session.execute(statement.limit(max(limit * 20, 200))).all()
        document_frequency: Counter[str] = Counter()
        tokenized: list[tuple[Message, MessageRevision, Participant | None, Counter]] = []
        for message, revision, participant in rows:
            frequencies = Counter(tokens(revision.text))
            document_frequency.update(frequencies.keys())
            tokenized.append((message, revision, participant, frequencies))
        total_documents = max(len(tokenized), 1)
        normalized_query = query.casefold()
        hits: list[RetrievalHit] = []
        for message, revision, participant, frequencies in tokenized:
            score = 0.0
            for term in query_terms:
                if frequencies[term]:
                    inverse_document_frequency = math.log(
                        1 + total_documents / (1 + document_frequency[term])
                    )
                    score += (1 + math.log(frequencies[term])) * inverse_document_frequency
            exact = normalized_query in revision.text.casefold()
            if exact:
                score += 3.0
            if score <= 0:
                continue
            name = participant.display_name if participant else "Система"
            hits.append(
                RetrievalHit(
                    message_id=message.id,
                    revision_id=revision.id,
                    sender_name=name,
                    sender_initials=initials(name),
                    sent_at=message.sent_at,
                    text=revision.text,
                    lexical_score=score,
                    exact_match=exact,
                )
            )
        hits.sort(key=lambda hit: (-hit.lexical_score, hit.sent_at))
        selected = hits[:limit]
        trace = RetrievalTrace(
            corpus_id=corpus_id,
            snapshot_id=snapshot.id,
            query=query,
            strategy=(
                "postgres-fts-trigram-v1"
                if self.session.bind is not None and self.session.bind.dialect.name == "postgresql"
                else "sqlite-bounded-lexical-v1"
            ),
            language="ru",
            filters={
                "snapshot_id": snapshot.id,
                **({"participant_id": participant_id} if participant_id else {}),
            },
            candidate_count=len(hits),
            returned_count=len(selected),
            coverage=1.0 if hits else 0.0,
            result_refs=[
                {
                    "object_type": "message",
                    "object_id": hit.message_id,
                    "revision_id": hit.revision_id,
                    "score": hit.lexical_score,
                }
                for hit in selected
            ],
        )
        self.session.add(trace)
        self.session.commit()
        return trace, selected
