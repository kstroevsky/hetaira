from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from prometheus_observatory.importers import ImportService
from prometheus_observatory.interaction_dynamics import InteractionDynamicsService
from prometheus_observatory.models import Corpus, MeasurementResult
from prometheus_observatory.object_store import ContentAddressedStore

FIXTURE = Path(__file__).parent / "fixtures" / "telegram.json"


def test_interaction_dynamics_reports_units_controls_censoring_and_missingness(
    db_session: Session, tmp_path: Path
) -> None:
    corpus = Corpus(name="Dynamics", language="ru", privacy_policy="LOCAL_ONLY")
    db_session.add(corpus)
    db_session.commit()
    with FIXTURE.open("rb") as source:
        stored = ContentAddressedStore(tmp_path / "objects").put_stream(source)
    ImportService(db_session).import_object(
        corpus, stored, FIXTURE.name, "application/json", "telegram"
    )

    service = InteractionDynamicsService(db_session)
    run = service.create(corpus.id)
    repeated = service.create(corpus.id)
    result = service.result(corpus.id, run_id=run.id)

    assert run.status == "completed"
    assert repeated.id == run.id
    coordination = result["measurements"]["directional-coordination@0.1.0"]
    assert coordination["denominator"] == 1
    assert coordination["sample_size"] == 1
    assert coordination["controls"] == [
        "responder_snapshot_baseline",
        "ordered_pair",
        "immediately_replied_message",
    ]
    survival = result["measurements"]["response-survival@0.1.0"]
    assert survival["numerator"] == 1
    assert survival["denominator"] == 2
    assert survival["estimate"]["survival_curve"]
    relational = result["measurements"]["relational-event-choice@0.1.0"]
    assert relational["causal_status"] == "associational"
    assert relational["uncertainty"]["reason"] == "fewer_than_10_informative_risk_sets"
    assert (
        len(
            list(
                db_session.scalars(
                    select(MeasurementResult).where(MeasurementResult.run_id == run.id)
                )
            )
        )
        == 3
    )
