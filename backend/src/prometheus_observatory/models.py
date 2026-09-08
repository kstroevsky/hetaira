from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import Session as SASession

from .database import Base


def new_id() -> str:
    return str(uuid.uuid4())


def now_utc() -> datetime:
    return datetime.now(UTC)


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Corpus(Base, Timestamped):
    __tablename__ = "corpora"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(240))
    language: Mapped[str] = mapped_column(String(16), default="ru")
    source_type: Mapped[str] = mapped_column(String(32), default="mixed")
    privacy_policy: Mapped[str] = mapped_column(String(64), default="LOCAL_ONLY")
    is_validated_language: Mapped[bool] = mapped_column(Boolean, default=True)


class CorpusSnapshot(Base, Timestamped):
    __tablename__ = "corpus_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    corpus_id: Mapped[str] = mapped_column(ForeignKey("corpora.id", ondelete="CASCADE"), index=True)
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    parent_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("corpus_snapshots.id"), index=True
    )
    manifest_hash: Mapped[str] = mapped_column(String(64), index=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    label: Mapped[str] = mapped_column(String(240), default="initial")


class SourceArtifact(Base, Timestamped):
    __tablename__ = "source_artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("corpus_snapshots.id", ondelete="CASCADE"), index=True
    )
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    original_name: Mapped[str] = mapped_column(String(500))
    media_type: Mapped[str] = mapped_column(String(160), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer)
    object_path: Mapped[str] = mapped_column(Text)


class ImportRun(Base, Timestamped):
    __tablename__ = "import_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    corpus_id: Mapped[str] = mapped_column(ForeignKey("corpora.id"), index=True)
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    platform: Mapped[str] = mapped_column(String(32))
    source_namespace: Mapped[str] = mapped_column(String(240))
    original_name: Mapped[str] = mapped_column(String(500))
    media_type: Mapped[str] = mapped_column(String(160))
    object_path: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"), index=True)
    parent_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("corpus_snapshots.id"), index=True
    )
    snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("corpus_snapshots.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="running", index=True)
    processed_messages: Mapped[int] = mapped_column(Integer, default=0)
    imported_messages: Mapped[int] = mapped_column(Integer, default=0)
    imported_participants: Mapped[int] = mapped_column(Integer, default=0)
    reused_messages: Mapped[int] = mapped_column(Integer, default=0)
    appended_revisions: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class Participant(Base, Timestamped):
    __tablename__ = "participants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    corpus_id: Mapped[str] = mapped_column(ForeignKey("corpora.id", ondelete="CASCADE"), index=True)
    display_name: Mapped[str] = mapped_column(String(240))
    pseudonym: Mapped[str] = mapped_column(String(80))


class ParticipantIdentity(Base, Timestamped):
    __tablename__ = "participant_identities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("participants.id", ondelete="CASCADE"), index=True
    )
    corpus_id: Mapped[str] = mapped_column(ForeignKey("corpora.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(32))
    source_namespace: Mapped[str] = mapped_column(String(240))
    external_id: Mapped[str] = mapped_column(String(240))
    display_name: Mapped[str] = mapped_column(String(240))
    __table_args__ = (
        Index(
            "uq_identity_corpus_namespace_external",
            "corpus_id",
            "platform",
            "source_namespace",
            "external_id",
            unique=True,
        ),
    )


class Conversation(Base, Timestamped):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    corpus_id: Mapped[str] = mapped_column(ForeignKey("corpora.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(32))
    source_namespace: Mapped[str] = mapped_column(String(240))
    external_id: Mapped[str] = mapped_column(String(240))
    title: Mapped[str] = mapped_column(String(500))
    goal: Mapped[str] = mapped_column(String(64), default="informal_social")
    __table_args__ = (
        Index(
            "uq_conversation_source_identity",
            "corpus_id",
            "platform",
            "source_namespace",
            "external_id",
            unique=True,
        ),
    )


class Message(Base, Timestamped):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    external_id: Mapped[str] = mapped_column(String(240))
    sender_id: Mapped[str | None] = mapped_column(ForeignKey("participants.id"), index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_local_timestamp: Mapped[str] = mapped_column(String(80))
    source_timezone_assumption: Mapped[str | None] = mapped_column(String(120))
    resolved_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    resolution_confidence: Mapped[float] = mapped_column(Float, default=1.0)
    reply_to_external_id: Mapped[str | None] = mapped_column(String(240), index=True)
    message_type: Mapped[str] = mapped_column(String(40), default="message")
    source_tombstone: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (
        Index("uq_message_conversation_external", "conversation_id", "external_id", unique=True),
    )


class MessageRevision(Base, Timestamped):
    __tablename__ = "message_revisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, default=1)
    text: Mapped[str] = mapped_column(Text, default="")
    text_hash: Mapped[str] = mapped_column(String(64), index=True)
    language: Mapped[str] = mapped_column(String(16), default="ru")
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision_kind: Mapped[str] = mapped_column(String(24), default="original")
    __table_args__ = (Index("uq_message_revision", "message_id", "revision_number", unique=True),)


class SnapshotMessageRevision(Base, Timestamped):
    __tablename__ = "snapshot_message_revisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("corpus_snapshots.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("message_revisions.id", ondelete="CASCADE"), index=True
    )
    __table_args__ = (
        UniqueConstraint("snapshot_id", "message_id", name="uq_snapshot_message"),
        UniqueConstraint("snapshot_id", "revision_id", name="uq_snapshot_revision"),
    )


class AttachmentRef(Base, Timestamped):
    __tablename__ = "attachment_refs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str | None] = mapped_column(String(160))
    caption: Mapped[str | None] = mapped_column(Text)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class InteractionEvent(Base, Timestamped):
    __tablename__ = "interaction_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id"), index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("participants.id"), index=True)
    target_participant_id: Mapped[str | None] = mapped_column(ForeignKey("participants.id"))
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ConversationSession(Base, Timestamped):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    segmentation_version: Mapped[str] = mapped_column(String(64))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    gap_hours: Mapped[int] = mapped_column(Integer, default=8)


class Episode(Base, Timestamped):
    __tablename__ = "episodes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(500), default="Эпизод")
    status: Mapped[str] = mapped_column(String(24), default="provisional")
    confidence: Mapped[float | None] = mapped_column(Float)


class EpisodeMessage(Base, Timestamped):
    __tablename__ = "episode_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    episode_id: Mapped[str] = mapped_column(
        ForeignKey("episodes.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    __table_args__ = (Index("uq_episode_message", "episode_id", "message_id", unique=True),)


class Utterance(Base, Timestamped):
    __tablename__ = "utterances"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("message_revisions.id", ondelete="CASCADE"), index=True
    )
    start_codepoint: Mapped[int] = mapped_column(Integer)
    end_codepoint: Mapped[int] = mapped_column(Integer)
    exact_text: Mapped[str] = mapped_column(Text)
    exact_text_hash: Mapped[str] = mapped_column(String(64))
    language: Mapped[str] = mapped_column(String(16), default="ru")


class Span(Base, Timestamped):
    __tablename__ = "spans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("message_revisions.id", ondelete="CASCADE"), index=True
    )
    start_codepoint: Mapped[int] = mapped_column(Integer)
    end_codepoint: Mapped[int] = mapped_column(Integer)
    exact_text: Mapped[str] = mapped_column(Text)
    exact_text_hash: Mapped[str] = mapped_column(String(64))


class CodebookVersion(Base, Timestamped):
    __tablename__ = "codebook_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    codebook_key: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[str] = mapped_column(String(40))
    language: Mapped[str] = mapped_column(String(16))
    content_hash: Mapped[str] = mapped_column(String(64))
    source_path: Mapped[str] = mapped_column(Text)
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (Index("uq_codebook_version", "codebook_key", "version", unique=True),)


class CodebookArtifact(Base, Timestamped):
    __tablename__ = "codebook_artifacts"
    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    content: Mapped[str] = mapped_column(Text)


class CodebookRelease(Base, Timestamped):
    __tablename__ = "codebook_releases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    codebook_key: Mapped[str] = mapped_column(String(120), index=True)
    semantic_version: Mapped[str] = mapped_column(String(40))
    language: Mapped[str] = mapped_column(String(16))
    artifact_hash: Mapped[str] = mapped_column(
        ForeignKey("codebook_artifacts.content_hash"), index=True
    )
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (
        UniqueConstraint("codebook_key", "semantic_version", name="uq_codebook_release"),
    )


class AnalysisRun(Base, Timestamped):
    __tablename__ = "analysis_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("corpus_snapshots.id"), index=True)
    run_type: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    progress: Mapped[float] = mapped_column(Float, default=0)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class AnalysisTask(Base, Timestamped):
    __tablename__ = "analysis_tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )
    task_key: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(24), default="pending")
    progress: Mapped[float] = mapped_column(Float, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


class DependencyFingerprint(Base, Timestamped):
    __tablename__ = "dependency_fingerprints"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_tasks.id", ondelete="CASCADE"), index=True
    )
    dependency_type: Mapped[str] = mapped_column(String(80))
    dependency_key: Mapped[str] = mapped_column(String(240))
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)


class Annotation(Base, Timestamped):
    __tablename__ = "annotations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("corpus_snapshots.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    object_type: Mapped[str] = mapped_column(String(40), index=True)
    object_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(80), index=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(24), default="provisional")
    raw_confidence: Mapped[float | None] = mapped_column(Float)
    calibrated_confidence: Mapped[float | None] = mapped_column(Float)
    alternatives: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON)
    superseded_by: Mapped[str | None] = mapped_column(ForeignKey("annotations.id"), index=True)


class AnnotationSet(Base, Timestamped):
    __tablename__ = "annotation_sets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    corpus_id: Mapped[str] = mapped_column(ForeignKey("corpora.id"), index=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("corpus_snapshots.id"), index=True)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    name: Mapped[str] = mapped_column(String(240))
    language: Mapped[str] = mapped_column(String(16), default="ru")
    codebook_key: Mapped[str] = mapped_column(String(120))
    codebook_version: Mapped[str] = mapped_column(String(40))
    codebook_artifact_hash: Mapped[str] = mapped_column(
        ForeignKey("codebook_artifacts.content_hash"), index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    target_size: Mapped[int] = mapped_column(Integer)
    sampling_spec: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    manifest_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("snapshot_id", "name", name="uq_annotation_set_snapshot_name"),
    )


class AnnotationUnit(Base, Timestamped):
    __tablename__ = "annotation_units"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    annotation_set_id: Mapped[str] = mapped_column(
        ForeignKey("annotation_sets.id", ondelete="CASCADE"), index=True
    )
    object_type: Mapped[str] = mapped_column(String(40), default="message")
    object_id: Mapped[str] = mapped_column(String(36), index=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("message_revisions.id"), index=True)
    group_id: Mapped[str] = mapped_column(String(36), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    split: Mapped[str] = mapped_column(String(16), index=True)
    strata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    __table_args__ = (
        UniqueConstraint(
            "annotation_set_id",
            "object_type",
            "object_id",
            "revision_id",
            name="uq_annotation_unit_object",
        ),
    )


class AnnotationSetAnnotation(Base, Timestamped):
    __tablename__ = "annotation_set_annotations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    annotation_set_id: Mapped[str] = mapped_column(
        ForeignKey("annotation_sets.id", ondelete="CASCADE"), index=True
    )
    unit_id: Mapped[str] = mapped_column(
        ForeignKey("annotation_units.id", ondelete="CASCADE"), index=True
    )
    annotation_id: Mapped[str] = mapped_column(
        ForeignKey("annotations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(24), default="human")
    __table_args__ = (
        UniqueConstraint(
            "annotation_set_id", "unit_id", "annotation_id", name="uq_set_unit_annotation"
        ),
    )


class GoldTaskJudgment(Base, Timestamped):
    __tablename__ = "gold_task_judgments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    annotation_set_id: Mapped[str] = mapped_column(
        ForeignKey("annotation_sets.id", ondelete="CASCADE"), index=True
    )
    unit_id: Mapped[str] = mapped_column(
        ForeignKey("annotation_units.id", ondelete="CASCADE"), index=True
    )
    task: Mapped[str] = mapped_column(String(80), index=True)
    slot: Mapped[str] = mapped_column(String(16), index=True)
    stage: Mapped[str] = mapped_column(String(24), index=True)
    status: Mapped[str] = mapped_column(String(24), default="NOT_ANNOTATED", index=True)
    annotator: Mapped[str | None] = mapped_column(String(240), index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (
        UniqueConstraint("unit_id", "task", "slot", name="uq_gold_judgment_unit_task_slot"),
    )


class GoldJudgmentAnnotation(Base, Timestamped):
    __tablename__ = "gold_judgment_annotations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    judgment_id: Mapped[str] = mapped_column(
        ForeignKey("gold_task_judgments.id", ondelete="CASCADE"), index=True
    )
    annotation_id: Mapped[str] = mapped_column(
        ForeignKey("annotations.id", ondelete="CASCADE"), index=True
    )
    __table_args__ = (
        UniqueConstraint("judgment_id", "annotation_id", name="uq_gold_judgment_annotation"),
    )


class AnnotationReview(Base, Timestamped):
    __tablename__ = "annotation_reviews"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    annotation_id: Mapped[str] = mapped_column(ForeignKey("annotations.id"), index=True)
    decision: Mapped[str] = mapped_column(String(24))
    reviewer: Mapped[str] = mapped_column(String(240))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class PropositionMention(Base, Timestamped):
    __tablename__ = "proposition_mentions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    annotation_id: Mapped[str] = mapped_column(ForeignKey("annotations.id"), unique=True)
    utterance_id: Mapped[str] = mapped_column(ForeignKey("utterances.id"), index=True)
    span_id: Mapped[str] = mapped_column(ForeignKey("spans.id"), index=True)
    normalized_text: Mapped[str] = mapped_column(Text)
    proposition_type: Mapped[str] = mapped_column(String(40), default="claim")
    language: Mapped[str] = mapped_column(String(16), default="ru")


class PropositionRelation(Base, Timestamped):
    __tablename__ = "proposition_relations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("corpus_snapshots.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    source_proposition_id: Mapped[str] = mapped_column(
        ForeignKey("proposition_mentions.id"), index=True
    )
    target_proposition_id: Mapped[str] = mapped_column(
        ForeignKey("proposition_mentions.id"), index=True
    )
    relation_type: Mapped[str] = mapped_column(String(40), index=True)
    annotation_id: Mapped[str] = mapped_column(ForeignKey("annotations.id"), unique=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    scoring_method: Mapped[str] = mapped_column(String(80), default="legacy")
    status: Mapped[str] = mapped_column(String(24), default="provisional")


class StanceObservation(Base, Timestamped):
    __tablename__ = "stance_observations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    annotation_id: Mapped[str] = mapped_column(ForeignKey("annotations.id"), unique=True)
    holder_id: Mapped[str] = mapped_column(ForeignKey("participants.id"), index=True)
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str] = mapped_column(String(36), index=True)
    position: Mapped[str] = mapped_column(String(24))
    strength: Mapped[float] = mapped_column(Float)
    certainty: Mapped[float] = mapped_column(Float)
    target_weight: Mapped[float] = mapped_column(Float, default=1.0)
    resolution_status: Mapped[str] = mapped_column(String(24), default="RESOLVED")


class EpistemicObservation(Base, Timestamped):
    __tablename__ = "epistemic_observations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    annotation_id: Mapped[str] = mapped_column(ForeignKey("annotations.id"), unique=True)
    holder_id: Mapped[str] = mapped_column(ForeignKey("participants.id"), index=True)
    proposition_id: Mapped[str] = mapped_column(ForeignKey("proposition_mentions.id"), index=True)
    polarity: Mapped[str] = mapped_column(String(24))
    commitment: Mapped[float] = mapped_column(Float)
    certainty: Mapped[float] = mapped_column(Float)
    evidential_basis: Mapped[str] = mapped_column(String(80))
    attributed_source_id: Mapped[str | None] = mapped_column(
        ForeignKey("participants.id"), index=True
    )


class ResponseRelation(Base, Timestamped):
    __tablename__ = "response_relations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("corpus_snapshots.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )
    source_message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"), index=True)
    target_message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"), index=True)
    source_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("message_revisions.id"), index=True
    )
    target_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("message_revisions.id"), index=True
    )
    relation_type: Mapped[str] = mapped_column(String(40), default="RESPONDS_TO")
    annotation_id: Mapped[str | None] = mapped_column(ForeignKey("annotations.id"))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    explicit: Mapped[bool] = mapped_column(Boolean, default=False)
    scoring_method: Mapped[str] = mapped_column(String(80), default="legacy")
    rank: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="provisional")
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "source_message_id",
            "target_message_id",
            "scoring_method",
            name="uq_response_candidate_run_source_target_method",
        ),
    )


class DiscourseRelation(Base, Timestamped):
    __tablename__ = "discourse_relations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("corpus_snapshots.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )
    source_message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"), index=True)
    target_message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"), index=True)
    source_revision_id: Mapped[str] = mapped_column(ForeignKey("message_revisions.id"), index=True)
    target_revision_id: Mapped[str] = mapped_column(ForeignKey("message_revisions.id"), index=True)
    relation_type: Mapped[str] = mapped_column(String(40), index=True)
    annotation_id: Mapped[str] = mapped_column(ForeignKey("annotations.id"), index=True)
    scoring_method: Mapped[str] = mapped_column(String(80))
    raw_score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(24), default="provisional")
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "source_message_id",
            "target_message_id",
            "relation_type",
            "scoring_method",
            name="uq_discourse_relation_run_endpoints_type_method",
        ),
    )


class MessageFeature(Base, Timestamped):
    __tablename__ = "message_features"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("corpus_snapshots.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"), index=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("message_revisions.id"), index=True)
    feature_type: Mapped[str] = mapped_column(String(80), index=True)
    producer_hash: Mapped[str] = mapped_column(String(64), index=True)
    dimensions: Mapped[int] = mapped_column(Integer)
    values: Mapped[list[float]] = mapped_column(JSON)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "revision_id",
            "feature_type",
            "producer_hash",
            name="uq_message_feature_snapshot_revision_producer",
        ),
    )


class ModelInvocation(Base, Timestamped):
    __tablename__ = "model_invocations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    provider: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(160))
    task: Mapped[str] = mapped_column(String(120))
    privacy_policy: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24))
    error: Mapped[str | None] = mapped_column(Text)


class RetrievalTrace(Base, Timestamped):
    __tablename__ = "retrieval_traces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    corpus_id: Mapped[str] = mapped_column(ForeignKey("corpora.id"), index=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("corpus_snapshots.id"), index=True)
    query: Mapped[str] = mapped_column(Text)
    strategy: Mapped[str] = mapped_column(String(80))
    language: Mapped[str] = mapped_column(String(16), default="ru")
    filters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    returned_count: Mapped[int] = mapped_column(Integer, default=0)
    coverage: Mapped[float] = mapped_column(Float, default=0)
    result_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class MeasurementDefinition(Base, Timestamped):
    __tablename__ = "measurement_definitions"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    version: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text)
    unit_of_analysis: Mapped[str] = mapped_column(String(80))
    epistemic_level: Mapped[str] = mapped_column(String(40), default="L2_MEASUREMENT")
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class MeasurementResult(Base, Timestamped):
    __tablename__ = "measurement_results"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    definition_id: Mapped[str] = mapped_column(ForeignKey("measurement_definitions.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    subject_type: Mapped[str] = mapped_column(String(40), index=True)
    subject_id: Mapped[str] = mapped_column(String(36), index=True)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    superseded_by: Mapped[str | None] = mapped_column(
        ForeignKey("measurement_results.id"), index=True
    )


class Hypothesis(Base, Timestamped):
    __tablename__ = "hypotheses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    corpus_id: Mapped[str] = mapped_column(ForeignKey("corpora.id"), index=True)
    claim: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="candidate")
    causal_status: Mapped[str] = mapped_column(String(24), default="associational")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Finding(Base, Timestamped):
    __tablename__ = "findings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    hypothesis_id: Mapped[str | None] = mapped_column(ForeignKey("hypotheses.id"), index=True)
    claim: Mapped[str] = mapped_column(Text)
    epistemic_level: Mapped[str] = mapped_column(String(40))
    causal_status: Mapped[str] = mapped_column(String(24))
    supporting_evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    counterevidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    alternative_explanations: Mapped[list[str]] = mapped_column(JSON, default=list)
    sensitivity_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    dependency_dag_root: Mapped[str] = mapped_column(String(240))
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON)
    superseded_by: Mapped[str | None] = mapped_column(ForeignKey("findings.id"), index=True)


class DerivationEdge(Base, Timestamped):
    __tablename__ = "derivation_edges"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_type: Mapped[str] = mapped_column(String(40), index=True)
    source_id: Mapped[str] = mapped_column(String(36), index=True)
    target_type: Mapped[str] = mapped_column(String(40), index=True)
    target_id: Mapped[str] = mapped_column(String(36), index=True)
    relation: Mapped[str] = mapped_column(String(40), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    __table_args__ = (
        UniqueConstraint(
            "source_type",
            "source_id",
            "target_type",
            "target_id",
            "relation",
            "run_id",
            name="uq_derivation_edge",
        ),
    )


class AnalyticalArtifact(Base, Timestamped):
    __tablename__ = "analytical_artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    corpus_id: Mapped[str] = mapped_column(ForeignKey("corpora.id"), index=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("corpus_snapshots.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    artifact_type: Mapped[str] = mapped_column(String(120), index=True)
    analysis_version: Mapped[str] = mapped_column(String(40))
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


IMMUTABLE_MODELS = (SourceArtifact, Message, MessageRevision)


@event.listens_for(SASession, "before_flush")
def prevent_source_mutation(session: SASession, _flush_context: object, _instances: object) -> None:
    for item in session.dirty:
        if isinstance(item, IMMUTABLE_MODELS) and session.is_modified(
            item, include_collections=False
        ):
            raise ValueError(
                f"{type(item).__name__} is immutable; create a derived revision instead"
            )
    for item in session.deleted:
        if isinstance(item, IMMUTABLE_MODELS):
            raise ValueError(f"{type(item).__name__} is immutable and cannot be deleted")
