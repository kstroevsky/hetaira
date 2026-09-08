from pathlib import Path

from sqlalchemy.orm import Session

from prometheus_observatory.importers import ImportService
from prometheus_observatory.models import Corpus
from prometheus_observatory.network_sequence import NetworkSequenceService
from prometheus_observatory.object_store import ContentAddressedStore

FIXTURE = Path(__file__).parent / "fixtures" / "telegram.json"


def test_network_sequence_artifact_keeps_layers_nulls_and_associational_guards(
    db_session: Session, tmp_path: Path
) -> None:
    corpus = Corpus(name="Networks", language="ru", privacy_policy="LOCAL_ONLY")
    db_session.add(corpus)
    db_session.commit()
    with FIXTURE.open("rb") as source:
        stored = ContentAddressedStore(tmp_path / "objects").put_stream(source)
    ImportService(db_session).import_object(
        corpus, stored, FIXTURE.name, "application/json", "telegram"
    )

    service = NetworkSequenceService(db_session)
    artifact = service.build(corpus.id)
    repeated = service.build(corpus.id)
    result = artifact.payload

    assert repeated.id == artifact.id
    assert result["multilayer_communities"]["layers"]["interaction"]["status"] == "available"
    assert result["multilayer_communities"]["knowledge_flow"]["status"] == "unavailable"
    motifs = result["network_motifs"]
    assert motifs["permutations"] == 100
    assert motifs["method"] == "target_permutation_preserving_in_out_event_counts"
    assert result["dialogue_sequences"]["unit"] == "structural_episode"
    assert result["dialogue_sequences"]["outcome_association"]["status"] == "unavailable"
    assert result["hawkes"]["status"] == "unavailable"
    assert "do not establish influence" in result["guardrail"]
