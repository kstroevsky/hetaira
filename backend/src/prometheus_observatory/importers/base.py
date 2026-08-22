from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol


@dataclass(slots=True)
class NormalizedAttachment:
    path: str
    media_type: str | None = None
    caption: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class NormalizedMessage:
    external_id: str
    sender_external_id: str | None
    sender_name: str
    sent_at: datetime
    text: str
    reply_to_external_id: str | None = None
    message_type: str = "message"
    edited_at: datetime | None = None
    tombstone: bool = False
    metadata: dict = field(default_factory=dict)
    attachments: list[NormalizedAttachment] = field(default_factory=list)


@dataclass(slots=True)
class NormalizedConversation:
    external_id: str
    title: str
    platform: str
    messages: list[NormalizedMessage]
    warnings: list[str] = field(default_factory=list)


class ConversationParser(Protocol):
    def parse(self, path: Path) -> NormalizedConversation: ...
