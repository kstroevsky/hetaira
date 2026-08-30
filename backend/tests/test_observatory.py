from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from prometheus_observatory.importers import ImportService
from prometheus_observatory.models import (
    AnalyticalArtifact,
    Corpus,
    DerivationEdge,
    Finding,
    MeasurementResult,
)
from prometheus_observatory.object_store import ContentAddressedStore
from prometheus_observatory.observatory import ObservatoryBuilder

FIXTURE = Path(__file__).parent / "fixtures" / "telegram.json"


def test_observatory_persists_multidimensional_snapshot_and_reuses_fingerprint(
    db_session: Session, tmp_path: Path
) -> None:
    corpus = Corpus(name="Observatory", language="ru", privacy_policy="LOCAL_ONLY")
    db_session.add(corpus)
    db_session.commit()
    with FIXTURE.open("rb") as source:
        stored = ContentAddressedStore(tmp_path / "objects").put_stream(source)
    imported = ImportService(db_session).import_object(
        corpus, stored, FIXTURE.name, "application/json", "telegram"
    )
    builder = ObservatoryBuilder(db_session)
    first = builder.build(corpus.id)
    second = builder.build(corpus.id)
    assert first.id == second.id
    assert first.snapshot_id == imported.snapshot_id
    assert first.content_hash and len(first.content_hash) == 64
    assert set(first.payload["dimensions"]) == {
        "source",
        "temporal",
        "participation",
        "reply_structure",
        "network",
        "roles",
        "lexical_evolution",
        "health_primitives",
        "data_quality",
    }
    assert first.payload["epistemic_status"] == "descriptive_provisional"
    assert first.payload["dimensions"]["health_primitives"]["aggregate_score"] is None
    displayed_names = {
        item["participant"]
        for item in first.payload["dimensions"]["participation"]["top_participants"]
    }
    assert displayed_names <= {"Анна", "Борис"}
    assert not any(name.startswith("Участник ") for name in displayed_names)
    assert db_session.scalar(select(func.count()).select_from(AnalyticalArtifact)) == 1
    assert db_session.scalar(select(func.count()).select_from(MeasurementResult)) == 9
    assert db_session.scalar(select(func.count()).select_from(Finding)) >= 2
    assert db_session.scalar(select(func.count()).select_from(DerivationEdge)) >= 9
