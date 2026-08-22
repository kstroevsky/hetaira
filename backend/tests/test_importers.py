from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from prometheus_observatory.importers import ImportService
from prometheus_observatory.models import (
    ConversationSession,
    Corpus,
    MessageRevision,
    ResponseRelation,
)
from prometheus_observatory.object_store import ContentAddressedStore

FIXTURES = Path(__file__).parent / "fixtures"


def make_corpus(session: Session) -> Corpus:
    corpus = Corpus(name="Тест", language="ru", privacy_policy="LOCAL_ONLY")
    session.add(corpus)
    session.commit()
    return corpus


def import_fixture(session: Session, tmp_path: Path, name: str, platform: str):
    corpus = make_corpus(session)
    with (FIXTURES / name).open("rb") as source:
        stored = ContentAddressedStore(tmp_path / "objects").put_stream(source)
    result = ImportService(session).import_object(
        corpus,
        stored,
        name,
        "application/json" if platform == "telegram" else "text/plain",
        platform,
    )
    return corpus, result


def test_telegram_import_preserves_reply_and_mixed_text(
    db_session: Session, tmp_path: Path
) -> None:
    _corpus, result = import_fixture(db_session, tmp_path, "telegram.json", "telegram")
    assert result.imported_messages == 2
    assert result.imported_participants == 2
    revision = db_session.scalar(
        select(MessageRevision).where(MessageRevision.text.like("Согласен%"))
    )
    assert revision is not None
    assert revision.text == "Согласен, это надёжнее."
    assert db_session.scalar(select(func.count()).select_from(ResponseRelation)) == 1
    assert db_session.scalar(select(func.count()).select_from(ConversationSession)) == 1


def test_whatsapp_import_preserves_multiline_message(db_session: Session, tmp_path: Path) -> None:
    _corpus, result = import_fixture(db_session, tmp_path, "whatsapp.txt", "whatsapp")
    assert result.imported_messages == 3
    revision = db_session.scalar(
        select(MessageRevision).where(MessageRevision.text.like("Почему%"))
    )
    assert revision is not None
    assert "\nПоясни" in revision.text


def test_source_revision_is_immutable(db_session: Session, tmp_path: Path) -> None:
    _corpus, _result = import_fixture(db_session, tmp_path, "telegram.json", "telegram")
    revision = db_session.scalar(select(MessageRevision))
    assert revision is not None
    revision.text = "Переписано"
    with pytest.raises(ValueError, match="immutable"):
        db_session.commit()
