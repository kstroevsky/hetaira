import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from prometheus_observatory.experimental_dynamics import ExperimentalDynamicsService
from prometheus_observatory.importers import ImportService
from prometheus_observatory.models import Annotation, Corpus
from prometheus_observatory.object_store import ContentAddressedStore


def test_experimental_information_and_affect_keep_epistemic_boundaries(
    db_session: Session, tmp_path: Path
) -> None:
    participants = [("Анна", "anna"), ("Борис", "boris"), ("Вера", "vera")]
    messages = []
    started = datetime(2025, 1, 6, 10, tzinfo=UTC)
    for week in range(40):
        for offset, (name, sender_id) in enumerate(participants):
            topic = "сервер релиз ошибка" if (week + offset) % 2 else "модель данные обучение"
            affect = " отлично рад" if week % 5 == 0 else " проблема риск"
            messages.append(
                {
                    "id": len(messages) + 1,
                    "type": "message",
                    "date": (started + timedelta(weeks=week, minutes=offset)).isoformat(),
                    "from": name,
                    "from_id": sender_id,
                    "text": f"{topic}{affect}.",
                }
            )
    payload = {"id": "experimental", "name": "Experimental", "messages": messages}
    path = tmp_path / "experimental.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    corpus = Corpus(name="Experimental", language="ru", privacy_policy="LOCAL_ONLY")
    db_session.add(corpus)
    db_session.commit()
    with path.open("rb") as source:
        stored = ContentAddressedStore(tmp_path / "objects").put_stream(source)
    ImportService(db_session).import_object(
        corpus, stored, path.name, "application/json", "telegram"
    )

    service = ExperimentalDynamicsService(db_session)
    artifact = service.build(corpus.id)
    repeated = service.build(corpus.id)
    result = artifact.payload

    assert repeated.id == artifact.id
    information = result["semantic_information_dynamics"]
    assert information["status"] == "available"
    assert information["causal_status"] == "predictive_association"
    assert information["bias_warning"] == "finite_sample_bias_and_discretization_sensitivity"
    assert information["transfer_entropy"]
    assert information["partial_information"]
    affect = result["linguistic_affect_dynamics"]
    assert affect["interpretation"] == "linguistic_affect_signal_not_internal_emotion"
    assert affect["messages_with_nonzero_signal"] == len(messages)
    assert db_session.scalar(
        select(func.count())
        .select_from(Annotation)
        .where(
            Annotation.run_id == artifact.run_id,
            Annotation.kind == "affect_signal",
        )
    ) == len(messages)
