from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Conversation, Message, MessageRevision, Participant, RetrievalTrace
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
    ) -> tuple[RetrievalTrace, list[RetrievalHit]]:
        query_terms = tokens(query)
        if not query_terms:
            raise ValueError("query must contain searchable terms")
        statement = (
            select(Message, MessageRevision, Participant)
            .join(MessageRevision, MessageRevision.message_id == Message.id)
            .outerjoin(Participant, Participant.id == Message.sender_id)
            .where(
                Message.conversation_id.in_(
                    select(Conversation.id).where(Conversation.corpus_id == corpus_id)
                )
            )
        )
        if participant_id:
            statement = statement.where(Message.sender_id == participant_id)
        rows = self.session.execute(statement).all()
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
            query=query,
            strategy="lexical-v1",
            language="ru",
            filters={"participant_id": participant_id} if participant_id else {},
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
