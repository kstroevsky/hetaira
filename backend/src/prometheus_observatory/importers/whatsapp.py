from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from ..text import normalize_text
from .base import ConversationMetadata, NormalizedMessage

LINE_PATTERNS = [
    re.compile(
        r"^\[(?P<date>\d{1,2}[./]\d{1,2}[./]\d{2,4}),\s+"
        r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\]\s+"
        r"(?P<sender>[^:]+):\s?(?P<text>.*)$"
    ),
    re.compile(
        r"^(?P<date>\d{1,2}[./]\d{1,2}[./]\d{2,4}),\s+"
        r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\s+-\s+"
        r"(?P<sender>[^:]+):\s?(?P<text>.*)$"
    ),
]


def _timestamp(date_value: str, time_value: str) -> datetime:
    clean = f"{date_value.replace('.', '/')} {time_value}"
    formats = (
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%y %H:%M:%S",
        "%d/%m/%y %H:%M",
    )
    for fmt in formats:
        try:
            return datetime.strptime(clean, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    raise ValueError(f"unsupported WhatsApp timestamp: {clean}")


class WhatsAppParser:
    platform = "whatsapp"

    def metadata(self, path: Path) -> ConversationMetadata:
        return ConversationMetadata(
            external_id=path.stem,
            title=path.stem.replace("_", " "),
            platform=self.platform,
            source_namespace=f"whatsapp:{path.stem}",
        )

    def iter_messages(self, path: Path) -> Iterator[NormalizedMessage]:
        current: NormalizedMessage | None = None
        message_number = 0
        with path.open("r", encoding="utf-8-sig") as lines:
            for line_number, raw_line in enumerate(lines, start=1):
                line = raw_line.rstrip("\r\n")
                match = None
                for candidate in LINE_PATTERNS:
                    match = candidate.match(line)
                    if match:
                        break
                if match:
                    if current is not None:
                        yield current
                    groups = match.groupdict()
                    sent_at = _timestamp(groups["date"], groups["time"])
                    message_number += 1
                    source_local_timestamp = f"{groups['date']} {groups['time']}"
                    current = NormalizedMessage(
                        external_id=str(message_number),
                        sender_external_id=groups["sender"].strip(),
                        sender_name=groups["sender"].strip(),
                        sent_at=sent_at,
                        source_local_timestamp=source_local_timestamp,
                        source_timezone_assumption="UTC_ASSUMED_WHATSAPP_EXPORT",
                        resolution_confidence=0.4,
                        text=normalize_text(groups["text"]),
                        metadata={"source_line": line_number},
                    )
                elif current is not None:
                    current.text = normalize_text(f"{current.text}\n{line}")
        if current is not None:
            yield current
