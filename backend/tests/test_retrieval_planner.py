from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from prometheus_observatory.importers import ImportService
from prometheus_observatory.models import Corpus
from prometheus_observatory.object_store import ContentAddressedStore
from prometheus_observatory.research_planner import AnalysisPlan, PlanStep, ResearchTool
from prometheus_observatory.retrieval import HybridRetriever

FIXTURE = Path(__file__).parent / "fixtures" / "telegram.json"


def test_retrieval_returns_traceable_exact_evidence(db_session: Session, tmp_path: Path) -> None:
    corpus = Corpus(name="Поиск", language="ru")
    db_session.add(corpus)
    db_session.commit()
    with FIXTURE.open("rb") as source:
        stored = ContentAddressedStore(tmp_path / "objects").put_stream(source)
    ImportService(db_session).import_object(
        corpus, stored, FIXTURE.name, "application/json", "telegram"
    )
    trace, hits = HybridRetriever(db_session).search(corpus.id, "проверим данные")
    assert trace.strategy == "lexical-v1"
    assert trace.result_refs[0]["revision_id"]
    assert hits[0].exact_match


def test_causal_plan_requires_identification_design() -> None:
    with pytest.raises(ValidationError, match="identification_design_id"):
        AnalysisPlan(
            question="Вызвало ли сообщение изменение позиции?",
            corpus_snapshot_id="snapshot",
            causal_status="causal",
            steps=[
                PlanStep(
                    tool=ResearchTool.SEARCH_EVIDENCE,
                    purpose="Найти релевантные экспозиции",
                )
            ],
        )
