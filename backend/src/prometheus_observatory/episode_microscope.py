from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .analyzer import PATTERNS
from .models import (
    Corpus,
    CorpusSnapshot,
    Episode,
    EpisodeMessage,
    Message,
    MessageRevision,
    Participant,
    SnapshotMessageRevision,
)
from .text import sentence_spans
from .workspace import sender_display_name


class EpisodeMicroscopeService:
    message_limit = 40
    minimum_tail = 10
    analysis_version = "episode-microscope-rules-ru@0.1.0"

    def __init__(self, session: Session) -> None:
        self.session = session

    def inspect(self, corpus_id: str, message_id: str) -> dict[str, Any]:
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
        selected_membership = self.session.scalar(
            select(SnapshotMessageRevision).where(
                SnapshotMessageRevision.snapshot_id == snapshot.id,
                SnapshotMessageRevision.message_id == message_id,
            )
        )
        if selected_membership is None:
            raise LookupError("message is not present in the active snapshot")
        episode_id = self.session.scalar(
            select(EpisodeMessage.episode_id).where(EpisodeMessage.message_id == message_id)
        )
        if episode_id is None:
            raise LookupError("message has no structural episode")
        episode = self.session.get(Episode, episode_id)
        rows = self.session.execute(
            select(EpisodeMessage.ordinal, Message, MessageRevision, Participant)
            .join(Message, Message.id == EpisodeMessage.message_id)
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
                EpisodeMessage.episode_id == episode_id,
                SnapshotMessageRevision.snapshot_id == snapshot.id,
            )
            .order_by(EpisodeMessage.ordinal)
        ).all()
        window_rows, window_index = self._window(rows, message_id)
        messages = []
        proposition_by_message: dict[str, list[dict[str, Any]]] = {}
        message_by_external: dict[str, dict[str, Any]] = {}
        grounding_events = []
        for ordinal, message, revision, participant in window_rows:
            propositions = []
            acts: set[str] = set()
            message_grounding = []
            for start, end, exact_text in sentence_spans(revision.text):
                sentence_acts = self._dialogue_acts(exact_text)
                acts.update(sentence_acts)
                grounding = self._grounding(exact_text)
                evidence = {
                    "object_type": "message",
                    "object_id": message.id,
                    "revision_id": revision.id,
                    "start_codepoint": start,
                    "end_codepoint": end,
                    "exact_text": exact_text,
                }
                if grounding:
                    event = {
                        "label": grounding,
                        "holder_id": message.sender_id,
                        "message_id": message.id,
                        "evidence": evidence,
                    }
                    grounding_events.append(event)
                    message_grounding.append(event)
                if self._is_proposition(exact_text, sentence_acts):
                    proposition_id = hashlib.sha256(
                        f"{message.id}:{start}:{end}:{exact_text}".encode()
                    ).hexdigest()[:24]
                    propositions.append(
                        {
                            "proposition_id": proposition_id,
                            "message_id": message.id,
                            "holder_id": message.sender_id,
                            "holder": sender_display_name(message, participant),
                            "text": exact_text.rstrip(".!?…").strip(),
                            "type": "proposal" if "PROPOSE" in sentence_acts else "claim",
                            "evidence": evidence,
                            "status": "provisional_rules",
                        }
                    )
            proposition_by_message[message.id] = propositions
            output = {
                "message_id": message.id,
                "external_id": message.external_id,
                "sender_id": message.sender_id,
                "sender": sender_display_name(message, participant),
                "sent_at": message.sent_at.isoformat(),
                "text": revision.text,
                "reply_to_external_id": message.reply_to_external_id,
                "selected": message.id == message_id,
                "ordinal": ordinal,
                "dialogue_acts": sorted(acts),
                "propositions": propositions,
                "grounding": message_grounding,
            }
            messages.append(output)
            message_by_external[message.external_id] = output
        stance_edges = self._stance_edges(messages, message_by_external, proposition_by_message)
        proposition_nodes = [
            proposition
            for message_propositions in proposition_by_message.values()
            for proposition in message_propositions
        ]
        edge_counts = Counter(edge["position"] for edge in stance_edges)
        participant_positions: dict[str, dict[str, Any]] = {}
        for edge in stance_edges:
            holder_key = edge.get("holder_id") or f"unresolved:{edge['source_message_id']}"
            profile = participant_positions.setdefault(
                holder_key,
                {
                    "participant_id": edge.get("holder_id"),
                    "participant": edge["holder"],
                    "support": 0,
                    "oppose": 0,
                    "abstain": 0,
                },
            )
            profile[edge["position"].casefold()] += 1
        return {
            "analysis_version": self.analysis_version,
            "status": "provisional_rules",
            "corpus_id": corpus.id,
            "snapshot_id": snapshot.id,
            "window": {
                "episode_id": episode_id,
                "episode_title": episode.title if episode else "Эпизод",
                "window_index": window_index,
                "message_limit": self.message_limit,
                "selected_message_id": message_id,
                "message_count": len(messages),
                "start_at": messages[0]["sent_at"] if messages else None,
                "end_at": messages[-1]["sent_at"] if messages else None,
            },
            "messages": messages,
            "propositions": proposition_nodes,
            "stance_edges": stance_edges,
            "grounding_events": grounding_events,
            "agreement_structure": {
                "support": edge_counts["SUPPORT"],
                "oppose": edge_counts["OPPOSE"],
                "abstain": edge_counts["ABSTAIN"],
                "participant_positions": list(participant_positions.values()),
            },
            "guardrail": (
                "Разбор построен русскими правилами высокой точности и остаётся provisional: "
                "отсутствие метки не означает отсутствие позиции, а ABSTAIN означает "
                "неразрешённую цель, не нейтральность участника."
            ),
        }

    def _window(self, rows: list[Any], message_id: str) -> tuple[list[Any], int]:
        chunks = [
            rows[index : index + self.message_limit]
            for index in range(0, len(rows), self.message_limit)
        ]
        if len(chunks) > 1 and len(chunks[-1]) < self.minimum_tail:
            chunks[-2].extend(chunks.pop())
        for index, chunk in enumerate(chunks):
            if any(row[1].id == message_id for row in chunk):
                return chunk, index
        raise LookupError("message was not found in its structural episode")

    @staticmethod
    def _dialogue_acts(text: str) -> list[str]:
        labels = [
            label
            for label in ("QUESTION", "PROPOSE", "AGREE", "DISAGREE", "COMMIT", "ACKNOWLEDGE")
            if PATTERNS[label].search(text)
        ]
        return labels or ["ASSERT"]

    @staticmethod
    def _grounding(text: str) -> str | None:
        if PATTERNS["CLARIFICATION_REQUESTED"].search(text):
            return "CLARIFICATION_REQUESTED"
        if PATTERNS["REPAIRED"].search(text):
            return "REPAIRED"
        if PATTERNS["ACKNOWLEDGE"].search(text):
            return "ACKNOWLEDGED"
        return None

    @staticmethod
    def _is_proposition(text: str, acts: list[str]) -> bool:
        return len(text.split()) >= 3 and acts != ["ACKNOWLEDGE"] and "QUESTION" not in acts

    @staticmethod
    def _stance_edges(
        messages: list[dict[str, Any]],
        message_by_external: dict[str, dict[str, Any]],
        proposition_by_message: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        output = []
        for message in messages:
            acts = set(message["dialogue_acts"])
            if not ({"AGREE", "DISAGREE"} & acts) or not message["reply_to_external_id"]:
                continue
            target_message = message_by_external.get(message["reply_to_external_id"])
            if target_message is None:
                continue
            targets = proposition_by_message.get(target_message["message_id"], [])
            if "AGREE" in acts and "DISAGREE" not in acts:
                position = "SUPPORT"
            elif "DISAGREE" in acts and "AGREE" not in acts:
                position = "OPPOSE"
            else:
                position = "ABSTAIN"
            resolved = len(targets) == 1 and position != "ABSTAIN"
            output.append(
                {
                    "source_message_id": message["message_id"],
                    "holder_id": message["sender_id"],
                    "holder": message["sender"],
                    "target_message_id": target_message["message_id"],
                    "target_proposition_id": targets[0]["proposition_id"] if resolved else None,
                    "target_text": targets[0]["text"] if resolved else None,
                    "position": position if resolved else "ABSTAIN",
                    "resolution_status": "RESOLVED" if resolved else "ABSTAIN",
                    "alternatives": [
                        {
                            "proposition_id": target["proposition_id"],
                            "text": target["text"],
                        }
                        for target in targets
                    ],
                    "confidence": 0.86 if resolved else None,
                    "evidence": {
                        "object_type": "message",
                        "object_id": message["message_id"],
                        "exact_text": message["text"],
                    },
                }
            )
        return output
