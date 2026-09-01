from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from prometheus_observatory.episode_microscope import EpisodeMicroscopeService
from prometheus_observatory.importers import ImportService
from prometheus_observatory.models import Corpus, Message
from prometheus_observatory.object_store import ContentAddressedStore

FIXTURE = Path(__file__).parent / "fixtures" / "telegram.json"


def test_episode_microscope_exposes_propositions_stance_and_source_evidence(
    db_session: Session,
    tmp_path: Path,
) -> None:
    corpus = Corpus(name="Episode microscope", language="ru", privacy_policy="LOCAL_ONLY")
    db_session.add(corpus)
    db_session.commit()
    with FIXTURE.open("rb") as source:
        stored = ContentAddressedStore(tmp_path / "objects").put_stream(source)
    ImportService(db_session).import_object(
        corpus,
        stored,
        FIXTURE.name,
        "application/json",
        "telegram",
    )
    selected = db_session.scalar(select(Message).where(Message.external_id == "2"))
    assert selected is not None

    result = EpisodeMicroscopeService(db_session).inspect(corpus.id, selected.id)

    assert result["status"] == "provisional_rules"
    assert result["window"]["message_count"] == 2
    assert result["window"]["selected_message_id"] == selected.id
    assert len(result["propositions"]) >= 2
    assert len(result["stance_edges"]) == 1
    edge = result["stance_edges"][0]
    assert edge["holder"] == "Борис"
    assert edge["position"] == "SUPPORT"
    assert edge["resolution_status"] == "RESOLVED"
    assert edge["target_proposition_id"]
    assert edge["evidence"]["object_id"] == selected.id
    assert result["agreement_structure"]["support"] == 1
    assert all(proposition["evidence"]["exact_text"] for proposition in result["propositions"])
