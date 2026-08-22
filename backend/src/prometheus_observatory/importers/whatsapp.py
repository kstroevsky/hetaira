from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from ..text import normalize_text
from .base import NormalizedConversation, NormalizedMessage

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

    def parse(self, path: Path) -> NormalizedConversation:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        messages: list[NormalizedMessage] = []
        warnings: list[str] = []
        current: NormalizedMessage | None = None
        for line_number, line in enumerate(lines, start=1):
            match = None
            for candidate in LINE_PATTERNS:
                match = candidate.match(line)
                if match:
                    break
            if match:
                groups = match.groupdict()
                try:
                    sent_at = _timestamp(groups["date"], groups["time"])
                except ValueError as error:
                    warnings.append(f"line {line_number}: {error}")
                    continue
                current = NormalizedMessage(
                    external_id=str(len(messages) + 1),
                    sender_external_id=groups["sender"].strip(),
                    sender_name=groups["sender"].strip(),
                    sent_at=sent_at,
                    text=normalize_text(groups["text"]),
                    metadata={"source_line": line_number},
                )
                messages.append(current)
            elif current is not None:
                current.text = normalize_text(f"{current.text}\n{line}")
            elif line.strip():
                warnings.append(f"line {line_number}: content before first message ignored")
        return NormalizedConversation(
            external_id=path.stem,
            title=path.stem.replace("_", " "),
            platform=self.platform,
            messages=messages,
            warnings=warnings,
        )
