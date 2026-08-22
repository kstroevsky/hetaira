from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .ontology import CausalStatus


class ResearchTool(StrEnum):
    LOOKUP_MESSAGES = "lookup_messages"
    SEARCH_EVIDENCE = "search_evidence"
    TRAVERSE_GRAPH = "traverse_graph"
    RUN_MEASUREMENT = "run_measurement"
    COMPARE_SPECIFICATIONS = "compare_specifications"
    SAVE_HYPOTHESIS = "save_hypothesis"


class PlanStep(BaseModel):
    tool: ResearchTool
    purpose: str = Field(min_length=4, max_length=500)
    arguments: dict[str, Any] = Field(default_factory=dict)
    expected_evidence: list[str] = Field(default_factory=list)


class AnalysisPlan(BaseModel):
    question: str = Field(min_length=4, max_length=2000)
    corpus_snapshot_id: str
    causal_status: CausalStatus = CausalStatus.DESCRIPTIVE
    identification_design_id: str | None = None
    steps: list[PlanStep] = Field(min_length=1, max_length=12)
    max_tool_calls: int = Field(default=20, ge=1, le=50)
    max_cost: float = Field(default=0, ge=0)
    require_counterevidence: bool = True

    @model_validator(mode="after")
    def enforce_scientific_boundary(self) -> AnalysisPlan:
        if (
            self.causal_status in {CausalStatus.QUASI_CAUSAL, CausalStatus.CAUSAL}
            and not self.identification_design_id
        ):
            raise ValueError("quasi-causal and causal plans require an identification_design_id")
        if self.causal_status == CausalStatus.CAUSAL and not self.require_counterevidence:
            raise ValueError("causal plans cannot disable counterevidence search")
        return self


class ToolResult(BaseModel):
    step_index: int
    tool: ResearchTool
    status: str
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class BoundedPlannerRuntime:
    """Validate model-proposed plans; execution stays in registered application tools."""

    def validate(self, plan: AnalysisPlan) -> AnalysisPlan:
        if len(plan.steps) > plan.max_tool_calls:
            raise ValueError("plan contains more steps than its tool-call budget")
        return plan
