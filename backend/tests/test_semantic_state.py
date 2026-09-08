import json
from pathlib import Path

from sqlalchemy.orm import Session

from prometheus_observatory.importers import ImportService
from prometheus_observatory.models import Corpus
from prometheus_observatory.object_store import ContentAddressedStore
from prometheus_observatory.semantic_state import SemanticStateService


def test_semantic_state_challengers_expose_disagreement_and_unlabeled_states(
    db_session: Session, tmp_path: Path
) -> None:
    messages = []
    for month in range(1, 13):
        topic = "сервер релиз ошибка команда" if month <= 6 else "модель данные обучение команда"
        for index in range(2 + (month >= 7)):
            messages.append(
                {
                    "id": len(messages) + 1,
                    "type": "message",
                    "date": f"2025-{month:02d}-{index + 1:02d}T10:00:00+00:00",
                    "from": "Анна" if index % 2 == 0 else "Борис",
                    "from_id": "anna" if index % 2 == 0 else "boris",
                    "text": f"{topic} пример {index}." + (" Почему?" if index == 0 else ""),
                }
            )
    payload = {"id": "semantic-state", "name": "Semantic state", "messages": messages}
    path = tmp_path / "semantic-state.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    corpus = Corpus(name="Semantic state", language="ru", privacy_policy="LOCAL_ONLY")
    db_session.add(corpus)
    db_session.commit()
    with path.open("rb") as source:
        stored = ContentAddressedStore(tmp_path / "objects").put_stream(source)
    ImportService(db_session).import_object(
        corpus, stored, path.name, "application/json", "telegram"
    )

    service = SemanticStateService(db_session)
    artifact = service.build(corpus.id)
    repeated = service.build(corpus.id)
    result = artifact.payload

    assert repeated.id == artifact.id
    assert result["topic_challengers"]["models"]["nmf"]["status"] == "available"
    assert result["topic_challengers"]["models"]["lda"]["status"] == "available"
    assert result["topic_challengers"]["agreement"]["interpretation"] == (
        "method_disagreement_is_uncertainty"
    )
    assert {item["method"] for item in result["change_points"]["message_activity"]} == {
        "binary_segmentation_sse",
        "cusum_max_deviation",
    }
    assert result["conversation_states"]["status"] == "available"
    assert result["conversation_states"]["states_are_unlabeled"] is True
    assert result["semantic_change"]["status"] == "available"
    assert result["semantic_change"]["representation"] == "tfidf_context_fallback"


def test_semantic_state_reports_unavailable_models_for_small_corpus(
    db_session: Session, tmp_path: Path
) -> None:
    payload = {
        "id": "small",
        "name": "Small",
        "messages": [
            {
                "id": 1,
                "type": "message",
                "date": "2025-01-01T10:00:00+00:00",
                "from": "Анна",
                "from_id": "anna",
                "text": "Один документ.",
            }
        ],
    }
    path = tmp_path / "small.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    corpus = Corpus(name="Small", language="ru", privacy_policy="LOCAL_ONLY")
    db_session.add(corpus)
    db_session.commit()
    with path.open("rb") as source:
        stored = ContentAddressedStore(tmp_path / "objects").put_stream(source)
    ImportService(db_session).import_object(
        corpus, stored, path.name, "application/json", "telegram"
    )

    payload = SemanticStateService(db_session).build(corpus.id).payload

    assert payload["topic_challengers"]["models"]["nmf"]["status"] == "unavailable"
    assert payload["conversation_states"]["status"] == "unavailable"
    assert payload["change_points"]["message_activity"] == []
