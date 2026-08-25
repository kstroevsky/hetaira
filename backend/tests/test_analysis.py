from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from prometheus_observatory.analyzer import DeterministicAnalyzer
from prometheus_observatory.importers import ImportService
from prometheus_observatory.models import (
    Annotation,
    Corpus,
    DependencyFingerprint,
    DerivationEdge,
    EpistemicObservation,
    Finding,
    MeasurementResult,
    Message,
    PropositionMention,
    ResponseRelation,
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
    assert db_session.scalar(select(func.count()).select_from(EpistemicObservation)) >= 2
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(Annotation)
            .where(Annotation.kind == "epistemic_state", Annotation.object_type == "span")
        )
        == 0
    )
    assert db_session.scalar(select(func.count()).select_from(DerivationEdge)) > 0
    assert db_session.scalar(select(func.count()).select_from(DependencyFingerprint)) == 6


def test_reciprocity_ignores_implicit_and_non_reply_relations(
    db_session: Session, tmp_path: Path
) -> None:
    corpus = analyzed_corpus(db_session, tmp_path)
    messages = list(db_session.scalars(select(Message).order_by(Message.sent_at)))
    db_session.add(
        ResponseRelation(
            source_message_id=messages[0].id,
            target_message_id=messages[1].id,
            relation_type="RESPONDS_TO",
            explicit=False,
        )
    )
    db_session.commit()
    run = DeterministicAnalyzer(db_session).analyze(corpus.id)
    result = db_session.scalar(
        select(MeasurementResult).where(
            MeasurementResult.run_id == run.id,
            MeasurementResult.definition_id == "reply-reciprocity@1",
        )
    )
    assert result is not None
    assert result.result["denominator"] == 1
    assert result.result["estimate"] == 0


def test_multi_proposition_reply_abstains_instead_of_selecting_first_target(
    db_session: Session, tmp_path: Path
) -> None:
    payload = {
        "id": "multi-proposition",
        "name": "multi-proposition",
        "messages": [
            {
                "id": 1,
                "type": "message",
                "date": "2026-01-01T10:00:00+00:00",
                "from": "Анна",
                "from_id": "anna",
                "text": "Релиз переносим на пятницу. Документацию обновляем сегодня.",
            },
            {
                "id": 2,
                "type": "message",
                "date": "2026-01-01T10:01:00+00:00",
                "from": "Борис",
                "from_id": "boris",
                "reply_to_message_id": 1,
                "text": "Согласен, это разумно.",
            },
        ],
    }
    export = tmp_path / "multi.json"
    export.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    corpus = Corpus(name="Несколько пропозиций", language="ru", privacy_policy="LOCAL_ONLY")
    db_session.add(corpus)
    db_session.commit()
    with export.open("rb") as source:
        stored = ContentAddressedStore(tmp_path / "objects").put_stream(source)
    ImportService(db_session).import_object(
        corpus, stored, export.name, "application/json", "telegram"
    )
    DeterministicAnalyzer(db_session).analyze(corpus.id)
    stance = db_session.scalar(select(Annotation).where(Annotation.kind == "stance"))
    assert stance is not None
    assert stance.value["resolution_status"] == "ABSTAIN"
    assert stance.status == "disputed"
    assert "target_id" not in stance.value
    assert len(stance.alternatives) == 2
