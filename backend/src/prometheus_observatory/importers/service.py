from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    AttachmentRef,
    Conversation,
    ConversationSession,
    Corpus,
    CorpusSnapshot,
    Episode,
    EpisodeMessage,
    InteractionEvent,
    Message,
    MessageRevision,
    Participant,
    ParticipantIdentity,
    ResponseRelation,
    SourceArtifact,
)
from ..object_store import StoredObject
from ..schemas import ImportResult
from ..text import text_hash
from .base import ConversationParser
from .telegram import TelegramParser
from .whatsapp import WhatsAppParser

PARSERS: dict[str, ConversationParser] = {
    "telegram": TelegramParser(),
    "whatsapp": WhatsAppParser(),
}


class ImportService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()

    def import_object(
        self,
        corpus: Corpus,
        stored: StoredObject,
        original_name: str,
        media_type: str,
        platform: str,
    ) -> ImportResult:
        parser = PARSERS[platform]
        normalized = parser.parse(stored.path)
        snapshot = CorpusSnapshot(
            corpus_id=corpus.id,
            source_hash=stored.sha256,
            label=f"{platform}:{original_name}",
        )
        self.session.add(snapshot)
        self.session.flush()
        artifact = SourceArtifact(
            snapshot_id=snapshot.id,
            sha256=stored.sha256,
            original_name=original_name,
            media_type=media_type,
            size_bytes=stored.size_bytes,
            object_path=str(stored.path),
        )
        self.session.add(artifact)
        conversation = Conversation(
            corpus_id=corpus.id,
            platform=platform,
            external_id=normalized.external_id,
            title=normalized.title,
        )
        self.session.add(conversation)
        self.session.flush()
        participant_cache: dict[str, Participant] = {}
        message_by_external: dict[str, Message] = {}
        for item in sorted(normalized.messages, key=lambda message: message.sent_at):
            participant = self._participant(
                corpus,
                platform,
                item.sender_external_id,
                item.sender_name,
                participant_cache,
            )
            message = Message(
                conversation_id=conversation.id,
                external_id=item.external_id,
                sender_id=participant.id if participant else None,
                sent_at=item.sent_at,
                reply_to_external_id=item.reply_to_external_id,
                message_type=item.message_type,
                source_tombstone=item.tombstone,
                raw_metadata=item.metadata,
            )
            self.session.add(message)
            self.session.flush()
            message_by_external[item.external_id] = message
            revision = MessageRevision(
                message_id=message.id,
                revision_number=1,
                text=item.text,
                text_hash=text_hash(item.text),
                language=corpus.language,
                edited_at=item.edited_at,
                revision_kind="deleted" if item.tombstone else "original",
            )
            self.session.add(revision)
            self.session.add(
                InteractionEvent(
                    conversation_id=conversation.id,
                    message_id=message.id,
                    actor_id=participant.id if participant else None,
                    event_type="SEND",
                    occurred_at=item.sent_at,
                    payload={"external_id": item.external_id},
                )
            )
            for attachment in item.attachments:
                self.session.add(
                    AttachmentRef(
                        message_id=message.id,
                        path=attachment.path,
                        media_type=attachment.media_type,
                        caption=attachment.caption,
                        source_metadata=attachment.metadata,
                    )
                )
        self.session.flush()
        for item in normalized.messages:
            if not item.reply_to_external_id:
                continue
            source = message_by_external.get(item.external_id)
            target = message_by_external.get(item.reply_to_external_id)
            if source and target:
                self.session.add(
                    ResponseRelation(
                        source_message_id=source.id,
                        target_message_id=target.id,
                        relation_type="REPLIES_TO",
                        confidence=1.0,
                        explicit=True,
                    )
                )
        self._segment(conversation, list(message_by_external.values()))
        snapshot.message_count = len(message_by_external)
        self.session.commit()
        return ImportResult(
            corpus_id=corpus.id,
            snapshot_id=snapshot.id,
            artifact_id=artifact.id,
            source_hash=stored.sha256,
            imported_messages=len(message_by_external),
            imported_participants=len(participant_cache),
            warnings=normalized.warnings,
        )

    def _participant(
        self,
        corpus: Corpus,
        platform: str,
        external_id: str | None,
        display_name: str,
        cache: dict[str, Participant],
    ) -> Participant | None:
        if external_id is None and display_name == "Системное сообщение":
            return None
        identity_key = f"{corpus.id}:{external_id or display_name}"
        if identity_key in cache:
            return cache[identity_key]
        participant = Participant(
            corpus_id=corpus.id,
            display_name=display_name,
            pseudonym=f"Участник {len(cache) + 1}",
        )
        self.session.add(participant)
        self.session.flush()
        self.session.add(
            ParticipantIdentity(
                participant_id=participant.id,
                platform=platform,
                external_id=identity_key,
                display_name=display_name,
            )
        )
        cache[identity_key] = participant
        return participant

    def _segment(self, conversation: Conversation, messages: list[Message]) -> None:
        ordered = sorted(messages, key=lambda message: message.sent_at)
        if not ordered:
            return
        boundary = timedelta(hours=self.settings.default_session_gap_hours)
        groups: list[list[Message]] = [[ordered[0]]]
        for message in ordered[1:]:
            if message.sent_at - groups[-1][-1].sent_at > boundary:
                groups.append([message])
            else:
                groups[-1].append(message)
        for group_index, group in enumerate(groups, start=1):
            conversation_session = ConversationSession(
                conversation_id=conversation.id,
                segmentation_version=f"gap-{self.settings.default_session_gap_hours}h-v1",
                start_at=group[0].sent_at,
                end_at=group[-1].sent_at,
                gap_hours=self.settings.default_session_gap_hours,
            )
            self.session.add(conversation_session)
            self.session.flush()
            episode = Episode(
                session_id=conversation_session.id,
                title=f"Эпизод {group_index}",
                status="provisional",
                confidence=1.0,
            )
            self.session.add(episode)
            self.session.flush()
            for ordinal, message in enumerate(group):
                self.session.add(
                    EpisodeMessage(episode_id=episode.id, message_id=message.id, ordinal=ordinal)
                )
