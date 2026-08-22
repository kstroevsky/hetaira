from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field, model_validator


class EpistemicLevel(StrEnum):
    SOURCE = "L0_SOURCE"
    OBSERVATION = "L1_OBSERVATION"
    MEASUREMENT = "L2_MEASUREMENT"
    INTERPRETATION = "L3_INTERPRETATION"
    CAUSAL = "L4_CAUSAL"


class CausalStatus(StrEnum):
    OBSERVED = "observed"
    DESCRIPTIVE = "descriptive"
    ASSOCIATIONAL = "associational"
    PREDICTIVE = "predictive"
    QUASI_CAUSAL = "quasi_causal"
    CAUSAL = "causal"


class AnnotationStatus(StrEnum):
    PROVISIONAL = "provisional"
    CONFIRMED = "confirmed"
    DISPUTED = "disputed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class PrivacyPolicy(StrEnum):
    LOCAL_ONLY = "LOCAL_ONLY"
    API_PSEUDONYMIZED_MINIMAL = "API_PSEUDONYMIZED_MINIMAL"
    API_RAW_EVIDENCE_ONLY = "API_RAW_EVIDENCE_ONLY"
    API_SELECTED_EPISODE = "API_SELECTED_EPISODE"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EvidenceRef(BaseModel):
    object_type: str
    object_id: str
    revision_id: str | None = None
    start_codepoint: int | None = Field(default=None, ge=0)
    end_codepoint: int | None = Field(default=None, ge=0)
    exact_text_hash: str | None = None

    @model_validator(mode="after")
    def validate_span(self) -> EvidenceRef:
        if (self.start_codepoint is None) != (self.end_codepoint is None):
            raise ValueError("start_codepoint and end_codepoint must be supplied together")
        if self.start_codepoint is not None and self.end_codepoint < self.start_codepoint:
            raise ValueError("end_codepoint cannot precede start_codepoint")
        return self


class Provenance(BaseModel):
    corpus_snapshot_id: str
    ontology_version: str
    codebook_version: str
    pipeline_version: str
    prompt_version: str | None = None
    model_provider: str = "deterministic"
    model: str = "rules-ru-v1"
    model_revision: str | None = None
    quantization: str | None = None
    retrieval_trace_id: str | None = None
    analysis_run_id: str
    random_seed: int | None = None
    created_at: datetime


T = TypeVar("T")


class Alternative(BaseModel):
    value: Any
    probability: float | None = Field(default=None, ge=0, le=1)


class AnnotationEnvelope(BaseModel, Generic[T]):
    value: T
    evidence: list[EvidenceRef]
    status: AnnotationStatus = AnnotationStatus.PROVISIONAL
    raw_confidence: float | None = Field(default=None, ge=0, le=1)
    calibrated_confidence: float | None = Field(default=None, ge=0, le=1)
    alternatives: list[Alternative] = Field(default_factory=list)
    provenance: Provenance


class Uncertainty(BaseModel):
    method: str
    lower: float | None = None
    upper: float | None = None
    explanation: list[str] = Field(default_factory=list)


class MeasurementEnvelope(BaseModel):
    definition_id: str
    population: dict[str, Any]
    unit_of_analysis: str
    interval: dict[str, datetime | None]
    windowing: dict[str, Any]
    estimate: float | dict[str, float]
    uncertainty: Uncertainty
    numerator: float | None = None
    denominator: float | None = None
    sample_size: int = Field(ge=0)
    missingness: dict[str, Any] = Field(default_factory=dict)
    controls: list[str] = Field(default_factory=list)
    null_model: dict[str, Any] | None = None
    dependency_results: list[str] = Field(default_factory=list)
    provenance: Provenance


class FindingEnvelope(BaseModel):
    claim: str
    epistemic_level: EpistemicLevel
    causal_status: CausalStatus
    supporting_evidence: list[EvidenceRef]
    counterevidence: list[EvidenceRef] = Field(default_factory=list)
    alternative_explanations: list[str] = Field(default_factory=list)
    sensitivity_results: list[dict[str, Any]] = Field(default_factory=list)
    dependency_dag_root: str
    provenance: Provenance

    @model_validator(mode="after")
    def causal_claim_requires_l4(self) -> FindingEnvelope:
        if (
            self.causal_status == CausalStatus.CAUSAL
            and self.epistemic_level != EpistemicLevel.CAUSAL
        ):
            raise ValueError("causal findings must use the L4_CAUSAL epistemic level")
        return self


ObjectType = Literal[
    "message",
    "revision",
    "utterance",
    "span",
    "proposition",
    "participant",
    "episode",
    "measurement",
    "finding",
]
