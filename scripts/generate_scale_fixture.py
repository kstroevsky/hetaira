from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

TEMPLATES = [
    "Давайте сначала проверим исходные данные.",
    "Почему это должно изменить решение?",
    "Согласна, предыдущая проверка была неполной.",
    "Не уверен, что выборка репрезентативна.",
    "Я проверю результат и отпишусь позже.",
]
PARTICIPANTS = [("Анна", "user-anna"), ("Борис", "user-boris"), ("Вера", "user-vera")]


def generate(count: int, output: Path) -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    with output.open("w", encoding="utf-8") as handle:
        handle.write('{"name":"Scale fixture","id":"scale","messages":[')
        for index in range(count):
            name, participant_id = PARTICIPANTS[index % len(PARTICIPANTS)]
            message = {
                "id": index + 1,
                "type": "message",
                "date": (start + timedelta(seconds=index * 30)).isoformat(),
                "from": name,
                "from_id": participant_id,
                "text": TEMPLATES[index % len(TEMPLATES)],
                "reply_to_message_id": index if index and index % 3 else None,
            }
            if index:
                handle.write(",")
            json.dump(message, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate a streaming Telegram scale fixture"
    )
    parser.add_argument("--count", type=int, default=1_000_000)
    parser.add_argument("--output", type=Path, default=Path("scale-1m.json"))
    arguments = parser.parse_args()
    generate(arguments.count, arguments.output)
