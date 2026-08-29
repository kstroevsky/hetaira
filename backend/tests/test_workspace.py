from pathlib import Path

from sqlalchemy.orm import Session

from prometheus_observatory.importers import ImportService
from prometheus_observatory.models import Corpus
from prometheus_observatory.object_store import ContentAddressedStore
from prometheus_observatory.workspace import WorkspaceService

FIXTURE = Path(__file__).parent / "fixtures" / "telegram.json"


def test_workspace_message_loading_is_bounded_but_total_comes_from_snapshot(
    db_session: Session, tmp_path: Path
) -> None:
    corpus = Corpus(name="Bounded workspace", language="ru")
    db_session.add(corpus)
    db_session.commit()
    with FIXTURE.open("rb") as source:
        stored = ContentAddressedStore(tmp_path / "objects").put_stream(source)
    ImportService(db_session).import_object(
        corpus, stored, FIXTURE.name, "application/json", "telegram"
    )
    service = WorkspaceService(db_session)
    assert len(service.messages(corpus.id, limit=1)) == 1
    workspace = service.workspace(corpus.id)
    assert workspace.overview["message_count"] == 2
    assert workspace.overview["loaded_message_count"] == 2
