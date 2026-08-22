from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from prometheus_observatory.analyzer import DeterministicAnalyzer
from prometheus_observatory.importers import ImportService
from prometheus_observatory.models import (
    Annotation,
    Corpus,
    Finding,
    MeasurementResult,
    PropositionMention,
    StanceObservation,
)
from prometheus_observatory.object_store import ContentAddressedStore

FIXTURE = Path(__file__).parent / "fixtures" / "telegram.json"


def analyzed_corpus(session: Session, tmp_path: Path) -> Corpus:
    corpus = Corpus(name="Анализ", language="ru", privacy_policy="LOCAL_ONLY")
    session.add(corpus)
    session.commit()
    with FIXTURE.open("rb") as source:
        stored = ContentAddressedStore(tmp_path / "objects").put_stream(source)
    ImportService(session).import_object(
        corpus, stored, FIXTURE.name, "application/json", "telegram"
    )
    return corpus


def test_foundational_analysis_is_evidence_linked_and_idempotent(
    db_session: Session, tmp_path: Path
) -> None:
    corpus = analyzed_corpus(db_session, tmp_path)
    first = DeterministicAnalyzer(db_session).analyze(corpus.id)
    second = DeterministicAnalyzer(db_session).analyze(corpus.id)
    assert first.id == second.id
    assert db_session.scalar(select(func.count()).select_from(PropositionMention)) >= 2
    assert db_session.scalar(select(func.count()).select_from(StanceObservation)) == 1
    annotations = db_session.scalars(select(Annotation)).all()
    assert annotations
    assert all(item.evidence and item.provenance for item in annotations)
    assert db_session.scalar(select(func.count()).select_from(MeasurementResult)) == 2
    finding = db_session.scalar(select(Finding))
    assert finding is not None
    assert finding.causal_status == "descriptive"
    assert "не является мерой влияния" in finding.alternative_explanations[0]
