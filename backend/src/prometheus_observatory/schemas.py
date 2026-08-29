from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .ontology import PrivacyPolicy


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CorpusCreate(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    language: str = "ru"
    source_type: str = "mixed"
    privacy_policy: PrivacyPolicy = PrivacyPolicy.LOCAL_ONLY
    is_validated_language: bool = True


class CorpusRead(ORMModel):
    id: str
    name: str
    language: str
    source_type: str
    privacy_policy: str
    is_validated_language: bool
    created_at: datetime


class ImportResult(BaseModel):
    import_run_id: str
    corpus_id: str
    snapshot_id: str
    artifact_id: str
    source_hash: str
    imported_messages: int
    imported_participants: int
    warnings: list[str] = Field(default_factory=list)


class ImportRunRead(ORMModel):
    id: str
    corpus_id: str
    source_hash: str
    platform: str
    original_name: str
    status: str
    processed_messages: int
    imported_messages: int
    reused_messages: int
    appended_revisions: int
    checkpoint: dict[str, Any]
    snapshot_id: str | None
    error: str | None
    created_at: datetime
    completed_at: datetime | None


class AnnotationRead(ORMModel):
    id: str
    kind: str
    value: dict[str, Any]
    evidence: list[dict[str, Any]]
    status: str
    raw_confidence: float | None
    calibrated_confidence: float | None


class AnnotationSetCreate(BaseModel):
    corpus_id: str
    snapshot_id: str
    name: str = Field(min_length=1, max_length=240)
    target_size: int = Field(default=200, ge=1, le=1200)
    codebook_key: str = "foundational-conversation-ru"
    codebook_version: str = "0.1.0"
    seed: str = "gold-ru-v0"


class AnnotationSetRead(ORMModel):
    id: str
    corpus_id: str
    snapshot_id: str
    name: str
    language: str
    codebook_key: str
    codebook_version: str
    codebook_artifact_hash: str
    status: str
    target_size: int
    sampling_spec: dict[str, Any]
    manifest_hash: str | None
    frozen_at: datetime | None
    created_at: datetime


class EvidenceSpanCreate(BaseModel):
    start_codepoint: int = Field(ge=0)
    end_codepoint: int = Field(gt=0)


class ManualAnnotationCreate(BaseModel):
    kind: str = Field(min_length=1, max_length=80)
    value: dict[str, Any]
    spans: list[EvidenceSpanCreate] = Field(min_length=1)
    annotator: str = Field(min_length=1, max_length=240)
    supersedes_annotation_id: str | None = None


class AnnotationReviewCreate(BaseModel):
    decision: str
    reviewer: str = Field(min_length=1, max_length=240)


class MessageListItem(BaseModel):
    id: str
    external_id: str
    sender_id: str | None
    sender_name: str
    sender_initials: str
    sent_at: datetime
    text: str
    reply_count: int = 0
    selected: bool = False


class MicroscopeSection(BaseModel):
    key: str
    title: str
    annotations: list[AnnotationRead]


class EvidenceStage(BaseModel):
    level: str
    title: str
    items: list[dict[str, Any]]


class MicroscopeResponse(BaseModel):
    message: MessageListItem
    revision_id: str
    text_hash: str
    sections: list[MicroscopeSection]
    evidence_chain: list[EvidenceStage]
    supporting_cases: list[dict[str, Any]]
    counterexamples: list[dict[str, Any]]


class RunRead(ORMModel):
    id: str
    run_type: str
    status: str
    progress: float
    configuration: dict[str, Any]
    started_at: datetime | None
    completed_at: datetime | None
    error: str | None


class WorkspaceResponse(BaseModel):
    corpus: CorpusRead
    messages: list[MessageListItem]
    selected_message_id: str
    microscope: MicroscopeResponse
    run: RunRead | None
    overview: dict[str, Any]
