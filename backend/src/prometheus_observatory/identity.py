from __future__ import annotations

import re
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Conversation,
    Message,
    MessageRevision,
    Participant,
    ParticipantIdentity,
)


class ParticipantIdentityService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def profile(self, participant_id: str) -> dict[str, Any]:
        participant = self.session.get(Participant, participant_id)
        if participant is None:
            raise LookupError("participant not found")
        identities = list(
            self.session.scalars(
                select(ParticipantIdentity)
                .where(ParticipantIdentity.participant_id == participant.id)
                .order_by(ParticipantIdentity.created_at)
            )
        )
        rows = self.session.execute(
            select(Message.id, Message.raw_metadata)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.sender_id == participant.id,
                Conversation.corpus_id == participant.corpus_id,
            )
        ).all()
        observed_names: Counter[str] = Counter()
        identity_basis: Counter[str] = Counter()
        for row in rows:
            metadata = row.raw_metadata or {}
            source_name = metadata.get("source_sender_name")
            if isinstance(source_name, str) and source_name.strip():
                observed_names[source_name] += 1
            basis = metadata.get("sender_identity_basis")
            if isinstance(basis, str) and basis:
                identity_basis[basis] += 1
        roster_aliases = self._roster_aliases(participant.corpus_id, identities)
        return {
            "participant_id": participant.id,
            "corpus_id": participant.corpus_id,
            "display_name": participant.display_name,
            "message_count": len(rows),
            "identities": [
                {
                    "platform": identity.platform,
                    "source_namespace": identity.source_namespace,
                    "external_id": identity.external_id,
                    "display_name": identity.display_name,
                }
                for identity in identities
            ],
            "observed_names": [
                {"name": name, "messages": count} for name, count in observed_names.most_common()
            ],
            "identity_basis": [
                {"basis": basis, "messages": count} for basis, count in identity_basis.most_common()
            ],
            "roster_aliases": roster_aliases,
            "status": "source_backed",
            "guardrail": (
                "Псевдонимы из roster подтверждены источником, но не доказывают, что имя "
                "использовалось участником на всём временном диапазоне."
            ),
        }

    def _roster_aliases(
        self,
        corpus_id: str,
        identities: list[ParticipantIdentity],
    ) -> list[dict[str, Any]]:
        user_ids = {
            identity.external_id.removeprefix("user")
            for identity in identities
            if identity.external_id.startswith("user")
            and identity.external_id.removeprefix("user").isdigit()
        }
        aliases: dict[tuple[str, str], dict[str, Any]] = {}
        for user_id in user_ids:
            pattern = re.compile(rf"(?:^|\n)\s*-?\s*{re.escape(user_id)}\s*:\s*([^\n]+)")
            evidence_rows = self.session.execute(
                select(Message.id, MessageRevision.text)
                .join(MessageRevision, MessageRevision.message_id == Message.id)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(
                    Conversation.corpus_id == corpus_id,
                    MessageRevision.text.contains(user_id),
                )
            ).all()
            for row in evidence_rows:
                for match in pattern.finditer(row.text):
                    alias = match.group(1).strip()
                    if not alias:
                        continue
                    key = (user_id, alias.casefold())
                    record = aliases.setdefault(
                        key,
                        {
                            "external_id": f"user{user_id}",
                            "alias": alias,
                            "evidence_message_ids": [],
                        },
                    )
                    if row.id not in record["evidence_message_ids"]:
                        record["evidence_message_ids"].append(row.id)
        return sorted(aliases.values(), key=lambda item: item["alias"].casefold())
