from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..models import DerivationEdge, MeasurementDefinition, MeasurementResult


class MeasurementPayload(BaseModel):
    estimate: Any
    uncertainty: dict[str, Any]
    numerator: Any = None
    denominator: float | int | None = None
    sample_size: int = Field(ge=0)
    missingness: dict[str, Any] = Field(default_factory=dict)
    controls: list[str] = Field(default_factory=list)
    null_model: dict[str, Any] | None = None
    dependency_results: list[str] = Field(default_factory=list)


class MeasurementComputation(BaseModel):
    payload: MeasurementPayload
    evidence: list[tuple[str, str]] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class MeasurementContext:
    session: Session
    corpus_id: str
    snapshot_id: str
    run_id: str
    interval_start: datetime | None = None
    interval_end: datetime | None = None
    controls: tuple[str, ...] = ()


class MeasurementPlugin(ABC):
    definition_id: str
    version: str
    title: str
    unit_of_analysis: str

    @abstractmethod
    def compute(self, context: MeasurementContext) -> MeasurementComputation:
        """Return an evidence-linked result with sample size and uncertainty."""

    @abstractmethod
    def null_model(self, context: MeasurementContext) -> dict[str, Any] | None:
        """Return a null model, or None for a purely descriptive result."""


class MeasurementRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, MeasurementPlugin] = {}

    def register(self, plugin: MeasurementPlugin) -> None:
        if plugin.definition_id in self._plugins:
            raise ValueError(f"duplicate measurement definition: {plugin.definition_id}")
        self._plugins[plugin.definition_id] = plugin

    def get(self, definition_id: str) -> MeasurementPlugin:
        try:
            return self._plugins[definition_id]
        except KeyError as error:
            raise LookupError(f"unknown measurement definition: {definition_id}") from error

    def definitions(self) -> tuple[str, ...]:
        return tuple(sorted(self._plugins))

    def execute(self, definition_id: str, context: MeasurementContext) -> MeasurementResult:
        plugin = self.get(definition_id)
        if context.session.get(MeasurementDefinition, definition_id) is None:
            context.session.add(
                MeasurementDefinition(
                    id=definition_id,
                    version=plugin.version,
                    title=plugin.title,
                    description=plugin.__doc__ or plugin.title,
                    unit_of_analysis=plugin.unit_of_analysis,
                    manifest={"plugin": type(plugin).__name__, "causal": False},
                )
            )
            context.session.flush()
        computation = plugin.compute(context)
        null_model = plugin.null_model(context)
        payload = computation.payload.model_copy(update={"null_model": null_model})
        result = MeasurementResult(
            definition_id=definition_id,
            run_id=context.run_id,
            subject_type="corpus",
            subject_id=context.corpus_id,
            result={
                **payload.model_dump(mode="json"),
                "population": {"snapshot_id": context.snapshot_id},
                "unit_of_analysis": plugin.unit_of_analysis,
            },
            provenance={"snapshot_id": context.snapshot_id, "run_id": context.run_id},
        )
        context.session.add(result)
        context.session.flush()
        context.session.add_all(
            DerivationEdge(
                source_type=source_type,
                source_id=source_id,
                target_type="measurement",
                target_id=result.id,
                relation="USES_OBSERVATION",
                run_id=context.run_id,
            )
            for source_type, source_id in computation.evidence
        )
        return result
