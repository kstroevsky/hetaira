from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ijson

from ..text import normalize_text
from .base import ConversationMetadata, NormalizedAttachment, NormalizedMessage


def _text_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            parts.append(item if isinstance(item, str) else str(item.get("text", "")))
        return "".join(parts)
    return ""


def _date(
    value: str | None, unix_value: str | int | None = None
) -> tuple[datetime, str, str | None, float]:
    if value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo:
            return parsed, value, None, 1.0
        return parsed.replace(tzinfo=UTC), value, "UTC_ASSUMED_FROM_TELEGRAM_EXPORT", 0.5
    if unix_value is not None:
        return datetime.fromtimestamp(int(unix_value), tz=UTC), str(unix_value), "UNIX_UTC", 1.0
    raise ValueError("Telegram message is missing a timestamp")


class TelegramParser:
    platform = "telegram"

    def metadata(self, path: Path) -> ConversationMetadata:
        values: dict[str, str] = {}
        with path.open("rb") as handle:
            for prefix, event, value in ijson.parse(handle):
                if prefix == "messages" and event == "start_array":
                    break
                if prefix in {"id", "name"} and event in {"string", "number"}:
                    values[prefix] = str(value)
        return ConversationMetadata(
            external_id=values.get("id", values.get("name", path.stem)),
            title=values.get("name", "Telegram export"),
            platform=self.platform,
            source_namespace=f"telegram:{path.stem}",
        )

    def iter_messages(self, path: Path) -> Iterator[NormalizedMessage]:
        with path.open("rb") as handle:
            for index, raw in enumerate(ijson.items(handle, "messages.item")):
                yield self._message(raw, index)

    def _message(self, raw: dict[str, Any], index: int) -> NormalizedMessage:
        external_id = str(raw.get("id", index + 1))
        sender_name = str(raw.get("from") or raw.get("actor") or "Системное сообщение")
        sender_external = raw.get("from_id") or raw.get("actor_id")
        message_type = str(raw.get("type", "message"))
        text = normalize_text(_text_value(raw.get("text", "")))
        if not text and raw.get("caption"):
            text = normalize_text(str(raw["caption"]))
        attachments: list[NormalizedAttachment] = []
        attachment_path = raw.get("file") or raw.get("photo") or raw.get("thumbnail")
        if attachment_path:
            attachments.append(
                NormalizedAttachment(
                    path=str(attachment_path),
                    media_type=raw.get("mime_type"),
                    caption=text or None,
                    metadata={"width": raw.get("width"), "height": raw.get("height")},
                )
            )
        sent_at, local_timestamp, timezone_assumption, confidence = _date(
            raw.get("date"), raw.get("date_unixtime")
        )
        edited_at = _date(raw.get("edited"))[0] if raw.get("edited") else None
        return NormalizedMessage(
            external_id=external_id,
            sender_external_id=str(sender_external) if sender_external else None,
            sender_name=sender_name,
            sent_at=sent_at,
            source_local_timestamp=local_timestamp,
            source_timezone_assumption=timezone_assumption,
            resolution_confidence=confidence,
            text=text,
            reply_to_external_id=(
                str(raw["reply_to_message_id"]) if raw.get("reply_to_message_id") else None
            ),
            message_type=message_type,
            edited_at=edited_at,
            tombstone=message_type == "deleted_message",
            metadata={
                "reactions": raw.get("reactions", []),
                "forwarded_from": raw.get("forwarded_from"),
                "source": raw,
            },
            attachments=attachments,
        )
