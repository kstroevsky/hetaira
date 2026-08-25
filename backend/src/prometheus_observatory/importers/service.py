from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
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
    ImportRun,
    InteractionEvent,
    Message,
    MessageRevision,
    Participant,
    ParticipantIdentity,
    ResponseRelation,
    SnapshotMessageRevision,
    SourceArtifact,
)
from ..object_store import StoredObject
from ..schemas import ImportResult
from ..text import text_hash
from .base import ConversationParser, NormalizedMessage
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
        parsed_metadata = parser.metadata(stored.path)
        source_namespace = f"{platform}:{Path(original_name).stem}"
        external_conversation_id = (
            parsed_metadata.external_id if platform == "telegram" else Path(original_name).stem
        )
        import_run = ImportRun(
            corpus_id=corpus.id,
            source_hash=stored.sha256,
            platform=platform,
            source_namespace=source_namespace,
            status="running",
        )
        self.session.add(import_run)
        self.session.commit()

        try:
            parent = self.session.scalar(
                select(CorpusSnapshot)
                .where(CorpusSnapshot.corpus_id == corpus.id)
                .order_by(CorpusSnapshot.created_at.desc(), CorpusSnapshot.id.desc())
            )
            conversation = self._conversation(
                corpus,
                platform,
                source_namespace,
                external_conversation_id,
                parsed_metadata.title,
            )
            participant_cache: dict[str, Participant] = {}
            revision_by_message = self._parent_membership(parent)
            imported_ids: set[str] = set()
            imported_count = 0
            new_participants = 0

            for imported_count, item in enumerate(parser.iter_messages(stored.path), start=1):
                participant, participant_created = self._participant(
                    corpus,
                    platform,
                    source_namespace,
                    item.sender_external_id,
                    item.sender_name,
                    participant_cache,
                )
                new_participants += int(participant_created)
                message, message_created = self._message(conversation, participant, item)
                imported_ids.add(message.id)
                revision, appended = self._revision(corpus, message, item)
                revision_by_message[message.id] = revision
                if message_created:
                    import_run.imported_messages += 1
                    self._source_children(conversation, message, participant, item)
                else:
                    import_run.reused_messages += 1
                import_run.appended_revisions += int(appended)
                if imported_count % self.settings.import_batch_size == 0:
                    self.session.flush()

            self.session.flush()
            self._responses(conversation, imported_ids)
            self._segment(conversation, imported_ids)

            manifest = sorted(
                (message_id, revision.id) for message_id, revision in revision_by_message.items()
            )
            manifest_hash = hashlib.sha256(
                json.dumps(manifest, separators=(",", ":")).encode()
            ).hexdigest()
            snapshot = CorpusSnapshot(
                corpus_id=corpus.id,
                source_hash=stored.sha256,
                parent_snapshot_id=parent.id if parent else None,
                manifest_hash=manifest_hash,
                message_count=len(manifest),
                label=f"{platform}:{original_name}",
            )
            self.session.add(snapshot)
            self.session.flush()
            self.session.add_all(
                SnapshotMessageRevision(
                    snapshot_id=snapshot.id,
                    message_id=message_id,
                    revision_id=revision_id,
                )
                for message_id, revision_id in manifest
            )
            artifact = SourceArtifact(
                snapshot_id=snapshot.id,
                sha256=stored.sha256,
                original_name=original_name,
                media_type=media_type,
                size_bytes=stored.size_bytes,
                object_path=str(stored.path),
            )
            self.session.add(artifact)
            import_run.status = "completed"
            import_run.completed_at = datetime.now(UTC)
            import_run.warnings = parsed_metadata.warnings
            self.session.commit()
            return ImportResult(
                corpus_id=corpus.id,
                snapshot_id=snapshot.id,
                artifact_id=artifact.id,
                source_hash=stored.sha256,
                imported_messages=imported_count,
                imported_participants=new_participants,
                warnings=parsed_metadata.warnings,
            )
        except Exception as error:
            self.session.rollback()
            persisted = self.session.get(ImportRun, import_run.id)
            if persisted is not None:
                persisted.status = "failed"
                persisted.error = str(error)
                persisted.completed_at = datetime.now(UTC)
                self.session.commit()
            raise

    def _conversation(
        self,
        corpus: Corpus,
        platform: str,
        source_namespace: str,
        external_id: str,
        title: str,
    ) -> Conversation:
        conversation = self.session.scalar(
            select(Conversation).where(
                Conversation.corpus_id == corpus.id,
                Conversation.platform == platform,
                Conversation.source_namespace == source_namespace,
                Conversation.external_id == external_id,
            )
        )
        if conversation is not None:
            return conversation
        conversation = Conversation(
            corpus_id=corpus.id,
            platform=platform,
            source_namespace=source_namespace,
            external_id=external_id,
            title=title,
        )
        self.session.add(conversation)
        self.session.flush()
        return conversation

    def _parent_membership(self, parent: CorpusSnapshot | None) -> dict[str, MessageRevision]:
        if parent is None:
            return {}
        rows = self.session.execute(
            select(SnapshotMessageRevision.message_id, MessageRevision)
            .join(MessageRevision, MessageRevision.id == SnapshotMessageRevision.revision_id)
            .where(SnapshotMessageRevision.snapshot_id == parent.id)
        )
        return {message_id: revision for message_id, revision in rows}

    def _participant(
        self,
        corpus: Corpus,
        platform: str,
        source_namespace: str,
        external_id: str | None,
        display_name: str,
        cache: dict[str, Participant],
    ) -> tuple[Participant | None, bool]:
        if external_id is None and display_name == "Системное сообщение":
            return None, False
        identity_key = external_id or display_name
        if identity_key in cache:
            return cache[identity_key], False
        identity = self.session.scalar(
            select(ParticipantIdentity).where(
                ParticipantIdentity.corpus_id == corpus.id,
                ParticipantIdentity.platform == platform,
                ParticipantIdentity.source_namespace == source_namespace,
                ParticipantIdentity.external_id == identity_key,
            )
        )
        if identity is not None:
            participant = self.session.get(Participant, identity.participant_id)
            if participant is None:
                raise RuntimeError("participant identity points to a missing participant")
            cache[identity_key] = participant
            return participant, False
        participant_number = (
            self.session.scalar(
                select(func.count())
                .select_from(Participant)
                .where(Participant.corpus_id == corpus.id)
            )
            or 0
        ) + 1
        participant = Participant(
            corpus_id=corpus.id,
            display_name=display_name,
            pseudonym=f"Участник {participant_number}",
        )
        self.session.add(participant)
        self.session.flush()
        self.session.add(
            ParticipantIdentity(
                participant_id=participant.id,
                corpus_id=corpus.id,
                platform=platform,
                source_namespace=source_namespace,
                external_id=identity_key,
                display_name=display_name,
            )
        )
        cache[identity_key] = participant
        return participant, True

    def _message(
        self, conversation: Conversation, participant: Participant | None, item: NormalizedMessage
    ) -> tuple[Message, bool]:
        existing = self.session.scalar(
            select(Message).where(
                Message.conversation_id == conversation.id,
                Message.external_id == item.external_id,
            )
        )
        if existing is not None:
            return existing, False
        message = Message(
            conversation_id=conversation.id,
            external_id=item.external_id,
            sender_id=participant.id if participant else None,
            sent_at=item.sent_at,
            source_local_timestamp=item.source_local_timestamp,
            source_timezone_assumption=item.source_timezone_assumption,
            resolved_timestamp=item.sent_at,
            resolution_confidence=item.resolution_confidence,
            reply_to_external_id=item.reply_to_external_id,
            message_type=item.message_type,
            source_tombstone=item.tombstone,
            raw_metadata=item.metadata,
        )
        self.session.add(message)
        self.session.flush()
        return message, True

    def _revision(
        self, corpus: Corpus, message: Message, item: NormalizedMessage
    ) -> tuple[MessageRevision, bool]:
        digest = text_hash(item.text)
        latest = self.session.scalar(
            select(MessageRevision)
            .where(MessageRevision.message_id == message.id)
            .order_by(MessageRevision.revision_number.desc())
        )
        if latest is not None and latest.text_hash == digest:
            return latest, False
        revision = MessageRevision(
            message_id=message.id,
            revision_number=(latest.revision_number + 1) if latest else 1,
            text=item.text,
            text_hash=digest,
            language=corpus.language,
            edited_at=item.edited_at,
            revision_kind="deleted" if item.tombstone else "edit" if latest else "original",
        )
        self.session.add(revision)
        self.session.flush()
        return revision, True

    def _source_children(
        self,
        conversation: Conversation,
        message: Message,
        participant: Participant | None,
        item: NormalizedMessage,
    ) -> None:
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
        self.session.add_all(
            AttachmentRef(
                message_id=message.id,
                path=attachment.path,
                media_type=attachment.media_type,
                caption=attachment.caption,
                source_metadata=attachment.metadata,
            )
            for attachment in item.attachments
        )

    def _responses(self, conversation: Conversation, imported_ids: set[str]) -> None:
        if not imported_ids:
            return
        messages = list(
            self.session.scalars(select(Message).where(Message.conversation_id == conversation.id))
        )
        by_external = {message.external_id: message for message in messages}
        existing = set(
            self.session.execute(
                select(
                    ResponseRelation.source_message_id, ResponseRelation.target_message_id
                ).where(ResponseRelation.source_message_id.in_(imported_ids))
            )
        )
        for source in messages:
            target = by_external.get(source.reply_to_external_id or "")
            if source.id in imported_ids and target and (source.id, target.id) not in existing:
                self.session.add(
                    ResponseRelation(
                        source_message_id=source.id,
                        target_message_id=target.id,
                        relation_type="REPLIES_TO",
                        confidence=1.0,
                        explicit=True,
                    )
                )

    def _segment(self, conversation: Conversation, imported_ids: set[str]) -> None:
        existing = self.session.scalar(
            select(ConversationSession.id).where(
                ConversationSession.conversation_id == conversation.id
            )
        )
        if not imported_ids or existing:
            return
        messages = list(self.session.scalars(select(Message).where(Message.id.in_(imported_ids))))

        def comparable(value: datetime) -> datetime:
            return value if value.tzinfo else value.replace(tzinfo=UTC)

        ordered = sorted(messages, key=lambda message: comparable(message.sent_at))
        if not ordered:
            return
        boundary = timedelta(hours=self.settings.default_session_gap_hours)
        groups: list[list[Message]] = [[ordered[0]]]
        for message in ordered[1:]:
            if comparable(message.sent_at) - comparable(groups[-1][-1].sent_at) > boundary:
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
            self.session.add_all(
                EpisodeMessage(episode_id=episode.id, message_id=message.id, ordinal=ordinal)
                for ordinal, message in enumerate(group)
            )
