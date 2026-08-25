from __future__ import annotations

import json
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
    assert trace.strategy == "sqlite-bounded-lexical-v1"
    assert trace.result_refs[0]["revision_id"]
    assert hits[0].exact_match


def test_retrieval_never_leaks_new_revision_into_older_snapshot(
    db_session: Session, tmp_path: Path
) -> None:
    corpus = Corpus(name="Версионный поиск", language="ru")
    db_session.add(corpus)
    db_session.commit()
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    first_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    payload["messages"][0]["text"] = "Уникальный маркер квантосфера."
    second_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    store = ContentAddressedStore(tmp_path / "objects")
    service = ImportService(db_session)
    with first_path.open("rb") as source:
        first_object = store.put_stream(source)
    first = service.import_object(
        corpus, first_object, "telegram.json", "application/json", "telegram"
    )
    with second_path.open("rb") as source:
        second_object = store.put_stream(source)
    second = service.import_object(
        corpus, second_object, "telegram.json", "application/json", "telegram"
    )
    _old_trace, old_hits = HybridRetriever(db_session).search(
        corpus.id, "квантосфера", snapshot_id=first.snapshot_id
    )
    new_trace, new_hits = HybridRetriever(db_session).search(
        corpus.id, "квантосфера", snapshot_id=second.snapshot_id
    )
    assert old_hits == []
    assert len(new_hits) == 1
    assert new_trace.filters["snapshot_id"] == second.snapshot_id


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
