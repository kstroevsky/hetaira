from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from prometheus_observatory.importers import ImportService
from prometheus_observatory.importers.service import ImportInterrupted
from prometheus_observatory.models import (
    Conversation,
    ConversationSession,
    Corpus,
    CorpusSnapshot,
    EpisodeMessage,
    ImportRun,
    Message,
    MessageRevision,
    Participant,
    ResponseRelation,
    SnapshotMessageRevision,
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


def test_reimport_is_idempotent_and_snapshots_have_exact_membership(
    db_session: Session, tmp_path: Path
) -> None:
    corpus = make_corpus(db_session)
    store = ContentAddressedStore(tmp_path / "objects")
    with (FIXTURES / "telegram.json").open("rb") as source:
        stored = store.put_stream(source)
    service = ImportService(db_session)
    first = service.import_object(corpus, stored, "telegram.json", "application/json", "telegram")
    second = service.import_object(corpus, stored, "telegram.json", "application/json", "telegram")
    assert first.snapshot_id != second.snapshot_id
    assert db_session.scalar(select(func.count()).select_from(Message)) == 2
    assert db_session.scalar(select(func.count()).select_from(MessageRevision)) == 2
    snapshots = list(
        db_session.scalars(select(CorpusSnapshot).where(CorpusSnapshot.corpus_id == corpus.id))
    )
    assert len(snapshots) == 2
    assert snapshots[0].manifest_hash == snapshots[1].manifest_hash
    for snapshot in snapshots:
        memberships = list(
            db_session.scalars(
                select(SnapshotMessageRevision).where(
                    SnapshotMessageRevision.snapshot_id == snapshot.id
                )
            )
        )
        assert len(memberships) == 2
        assert len({item.message_id for item in memberships}) == 2


def test_changed_export_appends_revision_and_preserves_older_snapshot(
    db_session: Session, tmp_path: Path
) -> None:
    corpus = make_corpus(db_session)
    payload = json.loads((FIXTURES / "telegram.json").read_text(encoding="utf-8"))
    original_path = tmp_path / "first.json"
    changed_path = tmp_path / "changed.json"
    original_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    payload["messages"][0]["text"] = "Предлагаю новый, уточнённый вариант."
    changed_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    store = ContentAddressedStore(tmp_path / "objects")
    with original_path.open("rb") as source:
        first_object = store.put_stream(source)
    with changed_path.open("rb") as source:
        changed_object = store.put_stream(source)
    service = ImportService(db_session)
    first = service.import_object(
        corpus, first_object, "telegram.json", "application/json", "telegram"
    )
    second = service.import_object(
        corpus, changed_object, "telegram.json", "application/json", "telegram"
    )
    revisions = list(
        db_session.scalars(
            select(MessageRevision)
            .join(Message, Message.id == MessageRevision.message_id)
            .where(Message.external_id == "1")
            .order_by(MessageRevision.revision_number)
        )
    )
    assert [revision.revision_number for revision in revisions] == [1, 2]
    first_membership = db_session.scalar(
        select(SnapshotMessageRevision).where(
            SnapshotMessageRevision.snapshot_id == first.snapshot_id,
            SnapshotMessageRevision.message_id == revisions[0].message_id,
        )
    )
    second_membership = db_session.scalar(
        select(SnapshotMessageRevision).where(
            SnapshotMessageRevision.snapshot_id == second.snapshot_id,
            SnapshotMessageRevision.message_id == revisions[0].message_id,
        )
    )
    assert first_membership is not None and first_membership.revision_id == revisions[0].id
    assert second_membership is not None and second_membership.revision_id == revisions[1].id


def test_sqlite_foreign_keys_are_enforced(db_session: Session) -> None:
    with pytest.raises(Exception, match="FOREIGN KEY"):
        db_session.add(
            SnapshotMessageRevision(
                snapshot_id="missing",
                message_id="missing",
                revision_id="missing",
            )
        )
        db_session.commit()


def test_two_conversations_in_one_namespace_share_participant_identity(
    db_session: Session, tmp_path: Path
) -> None:
    corpus = make_corpus(db_session)
    store = ContentAddressedStore(tmp_path / "objects")
    service = ImportService(db_session)
    for conversation_id in ("chat-a", "chat-b"):
        payload = {
            "id": conversation_id,
            "name": conversation_id,
            "messages": [
                {
                    "id": 1,
                    "type": "message",
                    "date": "2026-01-01T10:00:00+00:00",
                    "from": "Анна",
                    "from_id": "user-anna",
                    "text": "Проверяем общую идентичность участника.",
                }
            ],
        }
        path = tmp_path / f"{conversation_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        with path.open("rb") as source:
            stored = store.put_stream(source)
        service.import_object(corpus, stored, "shared-export.json", "application/json", "telegram")
    assert db_session.scalar(select(func.count()).select_from(Conversation)) == 2
    assert db_session.scalar(select(func.count()).select_from(Participant)) == 1
    assert set(db_session.scalars(select(Conversation.source_namespace))) == {"telegram"}


def test_renamed_incremental_telegram_export_reuses_source_and_extends_segmentation(
    db_session: Session, tmp_path: Path
) -> None:
    corpus = make_corpus(db_session)
    store = ContentAddressedStore(tmp_path / "objects")
    with (FIXTURES / "telegram.json").open("rb") as source:
        first = store.put_stream(source)
    service = ImportService(db_session)
    service.import_object(corpus, first, "first-name.json", "application/json", "telegram")
    payload = json.loads((FIXTURES / "telegram.json").read_text(encoding="utf-8"))
    payload["messages"].append(
        {
            "id": 3,
            "type": "message",
            "date": "2025-01-01T09:30:00+00:00",
            "from": "Анна",
            "from_id": "user-anna",
            "text": "Новое сообщение из переименованного экспорта.",
        }
    )
    renamed = tmp_path / "renamed-export.json"
    renamed.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with renamed.open("rb") as source:
        second = store.put_stream(source)
    service.import_object(corpus, second, "renamed-export.json", "application/json", "telegram")

    assert db_session.scalar(select(func.count()).select_from(Conversation)) == 1
    assert db_session.scalar(select(func.count()).select_from(Message)) == 3
    assert db_session.scalar(select(func.count()).select_from(EpisodeMessage)) == 3
    assert db_session.scalar(select(func.count()).select_from(ConversationSession)) == 1
    assert set(db_session.scalars(select(ImportRun.source_namespace))) == {"telegram"}


def test_interrupted_import_resumes_from_durable_checkpoint_without_duplicates(
    db_session: Session, tmp_path: Path
) -> None:
    corpus = make_corpus(db_session)
    with (FIXTURES / "telegram.json").open("rb") as source:
        stored = ContentAddressedStore(tmp_path / "objects").put_stream(source)
    with pytest.raises(ImportInterrupted) as interruption:
        ImportService(db_session).import_object(
            corpus,
            stored,
            "telegram.json",
            "application/json",
            "telegram",
            interrupt_after=1,
        )
    run_id = interruption.value.run_id
    interrupted = db_session.get(ImportRun, run_id)
    assert interrupted is not None
    assert interrupted.status == "interrupted"
    assert interrupted.processed_messages == 1
    assert interrupted.snapshot_id is None
    assert db_session.scalar(select(func.count()).select_from(Message)) == 1

    db_session.expire_all()
    result = ImportService(db_session).resume_import(run_id)
    completed = db_session.get(ImportRun, run_id)
    assert completed is not None and completed.status == "completed"
    assert completed.processed_messages == 2
    assert result.imported_messages == 2
    assert db_session.scalar(select(func.count()).select_from(Message)) == 2
    assert db_session.scalar(select(func.count()).select_from(MessageRevision)) == 2
    assert db_session.scalar(select(func.count()).select_from(SnapshotMessageRevision)) == 2
