from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..text import normalize_text
from .base import NormalizedAttachment, NormalizedConversation, NormalizedMessage


def _text_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            parts.append(item if isinstance(item, str) else str(item.get("text", "")))
        return "".join(parts)
    return ""


def _date(value: str | None, unix_value: str | int | None = None) -> datetime:
    if value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    if unix_value is not None:
        return datetime.fromtimestamp(int(unix_value), tz=UTC)
    raise ValueError("Telegram message is missing a timestamp")


class TelegramParser:
    platform = "telegram"

    def parse(self, path: Path) -> NormalizedConversation:
        with path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
        warnings: list[str] = []
        messages: list[NormalizedMessage] = []
        for index, raw in enumerate(payload.get("messages", [])):
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
            try:
                sent_at = _date(raw.get("date"), raw.get("date_unixtime"))
            except (TypeError, ValueError) as error:
                warnings.append(f"message {external_id}: {error}")
                continue
            edited_at = _date(raw.get("edited")) if raw.get("edited") else None
            messages.append(
                NormalizedMessage(
                    external_id=external_id,
                    sender_external_id=str(sender_external) if sender_external else None,
                    sender_name=sender_name,
                    sent_at=sent_at,
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
            )
        return NormalizedConversation(
            external_id=str(payload.get("id", payload.get("name", path.stem))),
            title=str(payload.get("name", "Telegram export")),
            platform=self.platform,
            messages=messages,
            warnings=warnings,
        )
