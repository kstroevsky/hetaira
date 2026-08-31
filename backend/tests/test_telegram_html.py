from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from prometheus_observatory.importers import ImportService
from prometheus_observatory.importers.telegram_html import TelegramHTMLParser
from prometheus_observatory.models import Corpus, Message, Participant, ResponseRelation
from prometheus_observatory.object_store import ContentAddressedStore
from prometheus_observatory.workspace import WorkspaceService


def write_export(root: Path) -> None:
    root.mkdir()
    (root / "messages.html").write_text(
        """<!doctype html><html><head><title>Русский чат</title></head><body>
        <div class="message service"><div class="body details">17 June 2024</div></div>
        <div class="message default clearfix" id="message1"><div class="pull_left userpic_wrap">
        <img src="photos/author_42.jpg"></div><div class="body">
        <div class="pull_right date details" title="17 June 2024, 12:00:00">12:00</div>
        <div class="from_name">Анна</div><div class="text">Первое сообщение.</div></div></div>
        <div class="message default clearfix joined" id="message2"><div class="body">
        <div class="pull_right date details" title="17 June 2024, 12:01:00">12:01</div>
        <div class="reply_to details"><a href="#go_to_message1">this message</a></div>
        <div class="text">Продолжение<br>на новой строке.</div></div></div>
        <div class="message service" id="message3"><div class="body details">User joined</div></div>
        </body></html>""",
        encoding="utf-8",
    )
    (root / "messages2.html").write_text(
        """<!doctype html><html><head><title>Русский чат</title></head><body>
        <div class="message default clearfix" id="message4"><div class="pull_left userpic_wrap">
        <img src="photos/author_99.jpg"></div><div class="body">
        <div class="pull_right date details" title="17 June 2024, 12:02:00">12:02</div>
        <div class="from_name">Борис</div><div class="text">Ответ.</div>
        <div class="media_wrap clearfix"><div class="title bold">Photo</div>
        <div class="status details">Not included.</div></div></div></div>
        <div class="message default clearfix" id="message5"><div class="pull_left userpic_wrap">
        <div class="userpic userpic6"><div class="initials">DA</div></div></div><div class="body">
        <div class="pull_right date details" title="17 June 2024, 12:03:00">12:03</div>
        <div class="from_name">Deleted Account</div><div class="text">Первый удалённый.</div>
        </div></div>
        <div class="message default clearfix joined" id="message6"><div class="body">
        <div class="pull_right date details" title="17 June 2024, 12:04:00">12:04</div>
        <div class="text">Продолжение удалённого.</div></div></div>
        <div class="message default clearfix" id="message7"><div class="pull_left userpic_wrap">
        <div class="userpic userpic3"><div class="initials">DA</div></div></div><div class="body">
        <div class="pull_right date details" title="17 June 2024, 12:05:00">12:05</div>
        <div class="from_name">Deleted Account</div><div class="text">Другой удалённый.</div>
        </div></div>
        <div class="message default clearfix" id="message8"><div class="pull_left userpic_wrap">
        <div class="userpic userpic2"><div class="initials">SU</div></div></div><div class="body">
        <div class="pull_right date details" title="17 June 2024, 12:06:00">12:06</div>
        <div class="from_name"><a href="https://t.me/source_user">Source User</a></div>
        <div class="text">Аккаунт с логином.</div></div></div>
        <div class="message default clearfix" id="message9"><div class="pull_left userpic_wrap">
        <div class="userpic userpic4"><div class="initials">RN</div></div></div><div class="body">
        <div class="pull_right date details" title="17 June 2024, 12:07:00">12:07</div>
        <div class="from_name"><a href="https://t.me/source_user">Renamed User</a></div>
        <div class="text">Тот же логин после переименования.</div></div></div>
        </body></html>""",
        encoding="utf-8",
    )


def test_html_parser_preserves_joined_sender_reply_service_and_missing_media(
    tmp_path: Path,
) -> None:
    export = tmp_path / "export"
    write_export(export)
    parser = TelegramHTMLParser()
    metadata = parser.metadata(export)
    messages = list(parser.iter_messages(export))
    assert metadata.title == "Русский чат"
    assert [message.external_id for message in messages] == [
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
    ]
    assert messages[1].sender_external_id == messages[0].sender_external_id == "user42"
    assert messages[1].reply_to_external_id == "1"
    assert "\n" in messages[1].text
    assert messages[2].message_type == "service"
    assert messages[2].resolution_confidence == 0.1
    assert messages[3].attachments[0].metadata["included"] is False
    assert messages[4].sender_external_id is messages[5].sender_external_id is None
    assert messages[6].sender_external_id is None
    assert messages[4].sender_name == "Deleted Account"
    assert messages[4].metadata["source_sender_name"] == "Deleted Account"
    assert messages[4].metadata["sender_identity_basis"] == "unresolved_sender_run"
    assert messages[4].metadata["unresolved_sender_run_id"] == "message:5"
    assert messages[5].metadata["unresolved_sender_run_id"] == "message:5"
    assert messages[6].metadata["unresolved_sender_run_id"] == "message:7"
    assert messages[7].sender_external_id == messages[8].sender_external_id
    assert messages[7].sender_external_id == "username:source_user"
    assert messages[7].metadata["sender_identity_basis"] == "telegram_username"


def test_html_directory_is_content_addressed_and_importable(
    db_session: Session, tmp_path: Path
) -> None:
    export = tmp_path / "export"
    write_export(export)
    store = ContentAddressedStore(tmp_path / "objects")
    first = store.put_directory(export)
    second = store.put_directory(export)
    assert first.sha256 == second.sha256
    corpus = Corpus(
        name="HTML",
        language="ru",
        source_type="telegram_html",
        privacy_policy="LOCAL_ONLY",
    )
    db_session.add(corpus)
    db_session.commit()
    result = ImportService(db_session).import_object(
        corpus,
        first,
        export.name,
        "application/x-tar",
        "telegram_html",
    )
    assert result.imported_messages == 9
    assert db_session.scalar(select(func.count()).select_from(Participant)) == 3
    assert db_session.scalar(select(func.count()).select_from(Message)) == 9
    unresolved = db_session.scalar(select(Message).where(Message.external_id == "5"))
    assert unresolved is not None and unresolved.sender_id is None
    assert unresolved.raw_metadata["unresolved_sender_run_id"] == "message:5"
    rendered = {item.external_id: item for item in WorkspaceService(db_session).messages(corpus.id)}
    assert rendered["5"].sender_name == "Deleted Account"
    relation = db_session.scalar(select(ResponseRelation))
    assert relation is not None and relation.explicit is True
