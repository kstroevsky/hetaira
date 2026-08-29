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
    new_id,
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


class ImportInterrupted(RuntimeError):
    def __init__(self, run_id: str) -> None:
        super().__init__(f"import interrupted after a durable checkpoint: {run_id}")
        self.run_id = run_id


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
        *,
        interrupt_after: int | None = None,
    ) -> ImportResult:
        parser = PARSERS[platform]
        parsed_metadata = parser.metadata(stored.path)
        source_namespace = f"{platform}:{Path(original_name).stem}"
        parent = self._latest_snapshot(corpus.id)
        import_run = ImportRun(
            corpus_id=corpus.id,
            source_hash=stored.sha256,
            platform=platform,
            source_namespace=source_namespace,
            original_name=original_name,
            media_type=media_type,
            object_path=str(stored.path),
            size_bytes=stored.size_bytes,
            parent_snapshot_id=parent.id if parent else None,
            status="running",
            warnings=parsed_metadata.warnings,
            checkpoint={"processed_messages": 0},
        )
        self.session.add(import_run)
        self.session.commit()
        return self._execute(import_run, interrupt_after=interrupt_after)

    def resume_import(
        self, import_run_id: str, *, interrupt_after: int | None = None
    ) -> ImportResult:
        import_run = self.session.get(ImportRun, import_run_id)
        if import_run is None:
            raise LookupError("import run not found")
        if import_run.status == "completed":
            if not import_run.snapshot_id:
                raise RuntimeError("completed import is missing its snapshot")
            return self._result(import_run)
        if import_run.status not in {"running", "interrupted", "failed"}:
            raise ValueError(f"import run cannot resume from status {import_run.status}")
        artifact_path = Path(import_run.object_path)
        if not artifact_path.is_file():
            raise FileNotFoundError("content-addressed source artifact is missing")
        import_run.status = "running"
        import_run.error = None
        import_run.completed_at = None
        self.session.commit()
        return self._execute(import_run, interrupt_after=interrupt_after)

    def _execute(self, import_run: ImportRun, *, interrupt_after: int | None) -> ImportResult:
        corpus = self.session.get(Corpus, import_run.corpus_id)
        if corpus is None:
            raise LookupError("import corpus not found")
        parser = PARSERS[import_run.platform]
        stored_path = Path(import_run.object_path)
        parsed_metadata = parser.metadata(stored_path)
        external_conversation_id = (
            parsed_metadata.external_id
            if import_run.platform == "telegram"
            else Path(import_run.original_name).stem
        )
        try:
            conversation = self._conversation(
                corpus,
                import_run.platform,
                import_run.source_namespace,
                external_conversation_id,
                parsed_metadata.title,
            )
            import_run.conversation_id = conversation.id
            self.session.commit()
            participant_cache: dict[str, Participant] = {}
            participant_sequence = [
                self.session.scalar(
                    select(func.count())
                    .select_from(Participant)
                    .where(Participant.corpus_id == corpus.id)
                )
                or 0
            ]
            processed = import_run.processed_messages
            batch: list[NormalizedMessage] = []
            last_ordinal = processed
            for ordinal, item in enumerate(parser.iter_messages(stored_path), start=1):
                if ordinal <= processed:
                    continue
                last_ordinal = ordinal
                batch.append(item)
                checkpoint_due = len(batch) >= self.settings.import_batch_size
                interrupt_due = interrupt_after is not None and ordinal >= interrupt_after
                if checkpoint_due or interrupt_due:
                    self._commit_batch(
                        import_run,
                        corpus,
                        conversation,
                        participant_cache,
                        participant_sequence,
                        batch,
                        ordinal,
                    )
                    batch = []
                    if interrupt_due:
                        import_run.status = "interrupted"
                        import_run.error = "test/user interruption after durable checkpoint"
                        self.session.commit()
                        raise ImportInterrupted(import_run.id)
            if batch:
                self._commit_batch(
                    import_run,
                    corpus,
                    conversation,
                    participant_cache,
                    participant_sequence,
                    batch,
                    last_ordinal,
                )
            self._segment_streaming(conversation)
            self._finalize_snapshot(import_run, corpus, conversation)
            self.session.commit()
            return self._result(import_run)
        except ImportInterrupted:
            raise
        except Exception as error:
            self.session.rollback()
            persisted = self.session.get(ImportRun, import_run.id)
            if persisted is not None:
                persisted.status = "failed"
                persisted.error = str(error)
                persisted.completed_at = datetime.now(UTC)
                self.session.commit()
            raise

    def _commit_batch(
        self,
        import_run: ImportRun,
        corpus: Corpus,
        conversation: Conversation,
        participant_cache: dict[str, Participant],
        participant_sequence: list[int],
        items: list[NormalizedMessage],
        processed_ordinal: int,
    ) -> None:
        external_ids = [item.external_id for item in items]
        message_cache = {
            message.external_id: message
            for message in self.session.scalars(
                select(Message).where(
                    Message.conversation_id == conversation.id,
                    Message.external_id.in_(external_ids),
                )
            )
        }
        latest_revision: dict[str, MessageRevision] = {}
        if message_cache:
            revisions = self.session.scalars(
                select(MessageRevision)
                .where(
                    MessageRevision.message_id.in_(
                        [message.id for message in message_cache.values()]
                    )
                )
                .order_by(
                    MessageRevision.message_id,
                    MessageRevision.revision_number.desc(),
                )
            )
            for revision in revisions:
                latest_revision.setdefault(revision.message_id, revision)
        batch_messages: list[Message] = []
        resolved_participants: list[Participant | None] = []
        with self.session.no_autoflush:
            for item in items:
                participant, participant_created = self._participant(
                    corpus,
                    import_run.platform,
                    import_run.source_namespace,
                    item.sender_external_id,
                    item.sender_name,
                    participant_cache,
                    participant_sequence,
                )
                import_run.imported_participants += int(participant_created)
                resolved_participants.append(participant)
        self.session.flush()
        new_sources: list[tuple[Message, Participant | None, NormalizedMessage]] = []
        for item, participant in zip(items, resolved_participants, strict=True):
            message = message_cache.get(item.external_id)
            if message is None:
                message = self._new_message(conversation, participant, item)
                message_cache[item.external_id] = message
                self.session.add(message)
                new_sources.append((message, participant, item))
                import_run.imported_messages += 1
            else:
                import_run.reused_messages += 1
            revision, appended = self._revision(
                corpus, message, item, latest_revision.get(message.id)
            )
            latest_revision[message.id] = revision
            import_run.appended_revisions += int(appended)
            batch_messages.append(message)
        self.session.flush()
        for message, participant, item in new_sources:
            self._source_children(conversation, message, participant, item)
        self.session.flush()
        self._responses_batch(conversation, batch_messages)
        import_run.processed_messages = processed_ordinal
        import_run.checkpoint = {
            "processed_messages": processed_ordinal,
            "last_external_id": items[-1].external_id,
            "source_hash": import_run.source_hash,
        }
        self.session.commit()

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
            id=new_id(),
            corpus_id=corpus.id,
            platform=platform,
            source_namespace=source_namespace,
            external_id=external_id,
            title=title,
        )
        self.session.add(conversation)
        self.session.flush()
        return conversation

    def _participant(
        self,
        corpus: Corpus,
        platform: str,
        source_namespace: str,
        external_id: str | None,
        display_name: str,
        cache: dict[str, Participant],
        participant_sequence: list[int],
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
        participant_sequence[0] += 1
        participant = Participant(
            id=new_id(),
            corpus_id=corpus.id,
            display_name=display_name,
            pseudonym=f"Участник {participant_sequence[0]}",
        )
        self.session.add(participant)
        self.session.add(
            ParticipantIdentity(
                id=new_id(),
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

    def _new_message(
        self, conversation: Conversation, participant: Participant | None, item: NormalizedMessage
    ) -> Message:
        return Message(
            id=new_id(),
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

    def _revision(
        self,
        corpus: Corpus,
        message: Message,
        item: NormalizedMessage,
        latest: MessageRevision | None,
    ) -> tuple[MessageRevision, bool]:
        digest = text_hash(item.text)
        if latest is not None and latest.text_hash == digest:
            return latest, False
        revision = MessageRevision(
            id=new_id(),
            message_id=message.id,
            revision_number=(latest.revision_number + 1) if latest else 1,
            text=item.text,
            text_hash=digest,
            language=corpus.language,
            edited_at=item.edited_at,
            revision_kind="deleted" if item.tombstone else "edit" if latest else "original",
        )
        self.session.add(revision)
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
                id=new_id(),
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
                id=new_id(),
                message_id=message.id,
                path=attachment.path,
                media_type=attachment.media_type,
                caption=attachment.caption,
                source_metadata=attachment.metadata,
            )
            for attachment in item.attachments
        )

    def _responses_batch(self, conversation: Conversation, batch_messages: list[Message]) -> None:
        sources = [message for message in batch_messages if message.reply_to_external_id]
        if not sources:
            return
        target_ids = {message.reply_to_external_id for message in sources}
        targets = {
            message.external_id: message
            for message in self.session.scalars(
                select(Message).where(
                    Message.conversation_id == conversation.id,
                    Message.external_id.in_(target_ids),
                )
            )
        }
        existing_sources = set(
            self.session.scalars(
                select(ResponseRelation.source_message_id).where(
                    ResponseRelation.source_message_id.in_([message.id for message in sources]),
                    ResponseRelation.explicit.is_(True),
                    ResponseRelation.relation_type == "REPLIES_TO",
                )
            )
        )
        self.session.add_all(
            ResponseRelation(
                id=new_id(),
                source_message_id=source.id,
                target_message_id=targets[source.reply_to_external_id].id,
                relation_type="REPLIES_TO",
                confidence=1.0,
                explicit=True,
            )
            for source in sources
            if source.id not in existing_sources and source.reply_to_external_id in targets
        )

    def _segment_streaming(self, conversation: Conversation) -> None:
        if self.session.scalar(
            select(ConversationSession.id).where(
                ConversationSession.conversation_id == conversation.id
            )
        ):
            return
        boundary = timedelta(hours=self.settings.default_session_gap_hours)
        current_session: ConversationSession | None = None
        current_episode: Episode | None = None
        previous_at: datetime | None = None
        ordinal = 0
        group_index = 0
        statement = (
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.sent_at, Message.id)
            .execution_options(yield_per=self.settings.import_batch_size)
        )
        for message in self.session.scalars(statement):
            sent_at = self._aware(message.sent_at)
            if previous_at is None or sent_at - previous_at > boundary:
                group_index += 1
                ordinal = 0
                current_session = ConversationSession(
                    id=new_id(),
                    conversation_id=conversation.id,
                    segmentation_version=f"gap-{self.settings.default_session_gap_hours}h-v1",
                    start_at=message.sent_at,
                    end_at=message.sent_at,
                    gap_hours=self.settings.default_session_gap_hours,
                )
                current_episode = Episode(
                    id=new_id(),
                    session_id=current_session.id,
                    title=f"Эпизод {group_index}",
                    status="provisional",
                    confidence=1.0,
                )
                self.session.add_all([current_session, current_episode])
            if current_session is None or current_episode is None:
                raise RuntimeError("segmentation state was not initialized")
            current_session.end_at = message.sent_at
            self.session.add(
                EpisodeMessage(
                    id=new_id(),
                    episode_id=current_episode.id,
                    message_id=message.id,
                    ordinal=ordinal,
                )
            )
            ordinal += 1
            previous_at = sent_at
            if ordinal % self.settings.import_batch_size == 0:
                self.session.flush()

    def _finalize_snapshot(
        self, import_run: ImportRun, corpus: Corpus, conversation: Conversation
    ) -> None:
        snapshot = CorpusSnapshot(
            id=new_id(),
            corpus_id=corpus.id,
            source_hash=import_run.source_hash,
            parent_snapshot_id=import_run.parent_snapshot_id,
            manifest_hash="pending",
            message_count=0,
            label=f"{import_run.platform}:{import_run.original_name}",
        )
        self.session.add(snapshot)
        self.session.flush()
        parent = (
            self.session.get(CorpusSnapshot, import_run.parent_snapshot_id)
            if import_run.parent_snapshot_id
            else None
        )
        if parent is not None:
            statement = (
                select(
                    SnapshotMessageRevision.message_id,
                    SnapshotMessageRevision.revision_id,
                )
                .join(Message, Message.id == SnapshotMessageRevision.message_id)
                .where(
                    SnapshotMessageRevision.snapshot_id == parent.id,
                    Message.conversation_id != conversation.id,
                )
                .order_by(SnapshotMessageRevision.message_id)
                .execution_options(yield_per=self.settings.import_batch_size)
            )
            self._copy_memberships(snapshot.id, self.session.execute(statement))
        latest_number = (
            select(
                MessageRevision.message_id.label("message_id"),
                func.max(MessageRevision.revision_number).label("revision_number"),
            )
            .group_by(MessageRevision.message_id)
            .subquery()
        )
        current_statement = (
            select(Message.id, MessageRevision.id)
            .join(latest_number, latest_number.c.message_id == Message.id)
            .join(
                MessageRevision,
                (MessageRevision.message_id == latest_number.c.message_id)
                & (MessageRevision.revision_number == latest_number.c.revision_number),
            )
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.id)
            .execution_options(yield_per=self.settings.import_batch_size)
        )
        self._copy_memberships(snapshot.id, self.session.execute(current_statement))
        self.session.flush()
        digest = hashlib.sha256()
        count = 0
        manifest_rows = self.session.execute(
            select(
                SnapshotMessageRevision.message_id,
                SnapshotMessageRevision.revision_id,
            )
            .where(SnapshotMessageRevision.snapshot_id == snapshot.id)
            .order_by(SnapshotMessageRevision.message_id)
            .execution_options(yield_per=self.settings.import_batch_size)
        )
        for message_id, revision_id in manifest_rows:
            digest.update(json.dumps([message_id, revision_id], separators=(",", ":")).encode())
            count += 1
        snapshot.manifest_hash = digest.hexdigest()
        snapshot.message_count = count
        artifact = SourceArtifact(
            id=new_id(),
            snapshot_id=snapshot.id,
            sha256=import_run.source_hash,
            original_name=import_run.original_name,
            media_type=import_run.media_type,
            size_bytes=import_run.size_bytes,
            object_path=import_run.object_path,
        )
        self.session.add(artifact)
        import_run.snapshot_id = snapshot.id
        import_run.status = "completed"
        import_run.completed_at = datetime.now(UTC)
        import_run.error = None
        import_run.checkpoint = {
            **import_run.checkpoint,
            "snapshot_id": snapshot.id,
            "manifest_hash": snapshot.manifest_hash,
        }

    def _copy_memberships(self, snapshot_id: str, rows) -> None:
        pending = 0
        for message_id, revision_id in rows:
            self.session.add(
                SnapshotMessageRevision(
                    id=new_id(),
                    snapshot_id=snapshot_id,
                    message_id=message_id,
                    revision_id=revision_id,
                )
            )
            pending += 1
            if pending >= self.settings.import_batch_size:
                self.session.flush()
                pending = 0

    def _result(self, import_run: ImportRun) -> ImportResult:
        if not import_run.snapshot_id:
            raise RuntimeError("import has not produced a snapshot")
        artifact = self.session.scalar(
            select(SourceArtifact).where(SourceArtifact.snapshot_id == import_run.snapshot_id)
        )
        if artifact is None:
            raise RuntimeError("import snapshot is missing its source artifact")
        return ImportResult(
            import_run_id=import_run.id,
            corpus_id=import_run.corpus_id,
            snapshot_id=import_run.snapshot_id,
            artifact_id=artifact.id,
            source_hash=import_run.source_hash,
            imported_messages=import_run.processed_messages,
            imported_participants=import_run.imported_participants,
            warnings=import_run.warnings,
        )

    def _latest_snapshot(self, corpus_id: str) -> CorpusSnapshot | None:
        return self.session.scalar(
            select(CorpusSnapshot)
            .where(CorpusSnapshot.corpus_id == corpus_id)
            .order_by(CorpusSnapshot.created_at.desc(), CorpusSnapshot.id.desc())
        )

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=UTC)
