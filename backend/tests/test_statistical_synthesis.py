import json
from pathlib import Path

from sqlalchemy.orm import Session

from prometheus_observatory.importers import ImportService
from prometheus_observatory.models import Corpus
from prometheus_observatory.object_store import ContentAddressedStore
from prometheus_observatory.statistical_synthesis import StatisticalSynthesisService


def test_statistical_synthesis_runs_nulls_and_hierarchical_reply_model(
    db_session: Session, tmp_path: Path
) -> None:
    names = [("Анна", "anna"), ("Борис", "boris"), ("Вера", "vera"), ("Глеб", "gleb")]
    messages = []
    for index in range(60):
        name, sender_id = names[index % len(names)]
        item = {
            "id": index + 1,
            "type": "message",
            "date": f"2025-01-{index // 24 + 1:02d}T{index % 24:02d}:00:00+00:00",
            "from": name,
            "from_id": sender_id,
            "text": "Почему проверяем данные?"
            if index % 4 == 0
            else "Проверяем данные перед решением.",
        }
        if index % 2 == 1:
            item["reply_to_message_id"] = index
        messages.append(item)
    payload = {"id": "stats", "name": "Stats", "messages": messages}
    path = tmp_path / "stats.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    corpus = Corpus(name="Stats", language="ru", privacy_policy="LOCAL_ONLY")
    db_session.add(corpus)
    db_session.commit()
    with path.open("rb") as source:
        stored = ContentAddressedStore(tmp_path / "objects").put_stream(source)
    ImportService(db_session).import_object(
        corpus, stored, path.name, "application/json", "telegram"
    )

    service = StatisticalSynthesisService(db_session)
    artifact = service.build(corpus.id)
    repeated = service.build(corpus.id)
    result = artifact.payload

    assert repeated.id == artifact.id
    nulls = result["null_models"]
    assert nulls["status"] == "available"
    assert nulls["unit"] == "explicit_reply_event"
    assert nulls["tests"][0]["permutations"] == 200
    model = result["hierarchical_reply_model"]
    assert model["status"] == "available"
    assert model["unit"] == "message"
    assert model["causal_status"] == "associational"
    assert set(model["fixed_effects"]) == {
        "intercept",
        "log_length_z",
        "question",
        "hour_sin",
        "hour_cos",
    }
    assert model["uncertainty"]["intervals"].startswith("unavailable")
