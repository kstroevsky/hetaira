from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session


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
    def compute(self, context: MeasurementContext) -> dict[str, Any]:
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
