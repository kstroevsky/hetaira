import json
from io import BytesIO
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
        "semantic_themes",
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
    assert first.payload["dimensions"]["semantic_themes"]["status"] in {
        "provisional_semantic_navigation",
        "insufficient_data",
    }
    assert db_session.scalar(select(func.count()).select_from(AnalyticalArtifact)) == 1
    assert db_session.scalar(select(func.count()).select_from(MeasurementResult)) == 10
    assert db_session.scalar(select(func.count()).select_from(Finding)) >= 2
    assert db_session.scalar(select(func.count()).select_from(DerivationEdge)) >= 10
    forced = builder.build(corpus.id, force=True)
    assert forced.id != first.id


def test_observatory_discovers_episode_themes_with_source_evidence(
    db_session: Session, tmp_path: Path
) -> None:
    corpus = Corpus(name="Тематический тест", language="ru", privacy_policy="LOCAL_ONLY")
    db_session.add(corpus)
    db_session.commit()
    topic_texts = (
        "психотерапия терапевтический сеанс интеграция переживание поддержка",
        "рецептор серотонин молекула фармакология исследование нейробиология",
    )
    messages = []
    message_id = 1
    for episode_index in range(8):
        day = episode_index + 1
        topic = topic_texts[episode_index % 2]
        for message_index in range(6):
            messages.append(
                {
                    "id": message_id,
                    "type": "message",
                    "date": f"2025-01-{day:02d}T{message_index:02d}:00:00+00:00",
                    "from": "Анна" if message_index % 2 == 0 else "Борис",
                    "from_id": "user-anna" if message_index % 2 == 0 else "user-boris",
                    "text": f"{topic} пример {message_index}",
                }
            )
            message_id += 1
    encoded = json.dumps(
        {"name": "Тематическая группа", "id": "theme-chat", "messages": messages},
        ensure_ascii=False,
    ).encode()
    stored = ContentAddressedStore(tmp_path / "objects").put_stream(BytesIO(encoded))
    ImportService(db_session).import_object(
        corpus, stored, "themes.json", "application/json", "telegram"
    )

    artifact = ObservatoryBuilder(db_session).build(corpus.id)
    semantic = artifact.payload["dimensions"]["semantic_themes"]

    assert semantic["status"] == "provisional_semantic_navigation"
    assert semantic["episode_count"] == 8
    assert semantic["cluster_count"] >= 2
    assert semantic["silhouette"] is not None
    assert semantic["separation_quality"] == "high"
    assert all(theme["representative_message_ids"] for theme in semantic["themes"])
    assert {
        participant["participant"]
        for theme in semantic["themes"]
        for participant in theme["top_participants"]
    } == {"Анна", "Борис"}
