from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .analyzer import DeterministicAnalyzer
from .config import get_settings
from .importers import ImportService
from .models import AnalysisRun, Corpus, CorpusSnapshot
from .object_store import ContentAddressedStore

RUSSIAN_DEMO_MESSAGES = [
    (1, "Иван П.", "user-ivan", "Коллеги, но дедлайн: релиз переносим на следующую среду.", None),
    (2, "Мария С.", "user-maria", "Поняла. Это из-за интеграционных тестов?", 1),
    (3, "Алексей К.", "user-alex", "Да, стенд нестабилен с пятницы.", 2),
    (4, "Никита В.", "user-nikita", "Можем обойти через моки, если нужно.", 3),
    (
        5,
        "Иван П.",
        "user-ivan",
        (
            "Не уверен, что это решит корень проблемы. "
            "Давайте сначала починим стенд, потом решим про обходы."
        ),
        4,
    ),
    (6, "Мария С.", "user-maria", "Согласна, починить надёжнее.", 5),
    (7, "Алексей К.", "user-alex", "Ок, я возьму стенд, отпишусь к вечеру.", 5),
    (
        8,
        "Никита В.",
        "user-nikita",
        "Не согласен: временный обход позволит выпустить сборку сегодня.",
        5,
    ),
    (9, "Иван П.", "user-ivan", "Что именно мешает исправить стенд сегодня?", 8),
    (
        10,
        "Никита В.",
        "user-nikita",
        "Точнее, мешает очередь на инфраструктуру, а не сам стенд.",
        9,
    ),
]


def _telegram_payload(english: bool = False) -> bytes:
    base = datetime(2025, 3, 12, 9, 14, tzinfo=UTC)
    if english:
        messages = []
        names = ["Alice", "Bob", "Carol", "Dave"]
        templates = [
            "I think we should inspect the evidence before deciding.",
            "Why would that change the current plan?",
            "I agree; the previous test was incomplete.",
            "I am not sure the sample is representative.",
            "Let's rerun it with the missing cases.",
        ]
        for index in range(100):
            messages.append(
                {
                    "id": index + 1,
                    "type": "message",
                    "date": (base + timedelta(minutes=index * 2)).isoformat(),
                    "from": names[index % len(names)],
                    "from_id": f"en-{index % len(names)}",
                    "text": templates[index % len(templates)],
                    "reply_to_message_id": index if index else None,
                }
            )
        title = "UNVALIDATED ENGLISH DEMO"
    else:
        messages = [
            {
                "id": message_id,
                "type": "message",
                "date": (base + timedelta(minutes=offset * 2)).isoformat(),
                "from": sender,
                "from_id": sender_id,
                "text": text,
                "reply_to_message_id": reply_to,
            }
            for offset, (message_id, sender, sender_id, text, reply_to) in enumerate(
                RUSSIAN_DEMO_MESSAGES
            )
        ]
        title = "Архив команды · 2024–2026"
    payload = {"name": title, "id": title, "messages": messages}
    return json.dumps(payload, ensure_ascii=False).encode()


def seed_demo(session: Session) -> None:
    if session.scalar(select(func.count()).select_from(Corpus)):
        russian = session.scalar(select(Corpus).where(Corpus.language == "ru"))
        if russian is not None:
            run = session.scalar(
                select(AnalysisRun).where(
                    AnalysisRun.snapshot_id.in_(
                        select(CorpusSnapshot.id).where(CorpusSnapshot.corpus_id == russian.id)
                    )
                )
            )
            if run is None:
                DeterministicAnalyzer(session).analyze(russian.id)
        return
    settings = get_settings()
    store = ContentAddressedStore(settings.object_store)
    russian = Corpus(
        name="Архив команды · 2024–2026",
        language="ru",
        source_type="telegram",
        privacy_policy="LOCAL_ONLY",
        is_validated_language=True,
    )
    session.add(russian)
    session.commit()
    stored = store.put_stream(io.BytesIO(_telegram_payload()))
    ImportService(session).import_object(
        russian,
        stored,
        "prometheus-russian-demo.json",
        "application/json",
        "telegram",
    )
    DeterministicAnalyzer(session).analyze(russian.id)

    english = Corpus(
        name="UNVALIDATED ENGLISH DEMO",
        language="en",
        source_type="telegram",
        privacy_policy="LOCAL_ONLY",
        is_validated_language=False,
    )
    session.add(english)
    session.commit()
    stored_en = store.put_stream(io.BytesIO(_telegram_payload(english=True)))
    ImportService(session).import_object(
        english,
        stored_en,
        "prometheus-english-demo.json",
        "application/json",
        "telegram",
    )
