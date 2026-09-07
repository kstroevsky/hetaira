from __future__ import annotations

import hashlib
import re
import tarfile
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from lxml import html as lxml_html

from ..text import normalize_text
from .base import ConversationMetadata, NormalizedAttachment, NormalizedMessage

PAGE_PATTERN = re.compile(r"^messages(?P<number>\d*)\.html$")
MESSAGE_ID_PATTERN = re.compile(r"(?:message|go_to_message)(\d+)")
DIRECTORY_LINE_PATTERN = re.compile(r"(?:^|\n)\s*-?\s*(?P<user_id>\d{5,})\s*:\s*(?P<name>[^\n]+)")


def page_order(name: str) -> int:
    match = PAGE_PATTERN.match(Path(name).name)
    if not match:
        return 10**9
    return int(match.group("number") or "1")


def compact_text(value: str) -> str:
    return normalize_text("\n".join(line.strip() for line in value.splitlines() if line.strip()))


class TelegramHTMLParser:
    platform = "telegram_html"

    def metadata(self, path: Path) -> ConversationMetadata:
        names = self._page_names(path)
        if not names:
            raise ValueError("Telegram HTML export does not contain message pages")
        with self._page_stream(path, names[0]) as first_page:
            root = self._parse(first_page)
        titles = root.xpath("//title/text()")
        title = compact_text(titles[0]) if titles else path.stem
        return ConversationMetadata(
            external_id=f"telegram-html:{hashlib.sha256(title.encode()).hexdigest()[:24]}",
            title=title,
            platform=self.platform,
            source_namespace="telegram-html",
            warnings=[
                "Telegram HTML timestamps do not include a timezone; "
                "UTC is a reversible placeholder."
            ],
        )

    def iter_messages(self, path: Path) -> Iterator[NormalizedMessage]:
        source_directory = self._source_identity_directory(path)
        last_sender_name = "Системное сообщение"
        last_sender_id: str | None = None
        last_sender_source_name = "Системное сообщение"
        last_sender_identity_basis = "system"
        last_sender_run_id: str | None = None
        last_timestamp: datetime | None = None
        current_date: datetime | None = None
        source_index = 0
        for page_name, page in self._pages(path):
            root = self._parse(page)
            message_nodes = root.xpath(
                "//div[contains(concat(' ', normalize-space(@class), ' '), ' message ')]"
            )
            for node in message_nodes:
                classes = set((node.get("class") or "").split())
                raw_id = node.get("id") or ""
                identifier = MESSAGE_ID_PATTERN.search(raw_id)
                if "service" in classes and not identifier:
                    date_text = compact_text(node.text_content())
                    parsed_date = self._parse_date_heading(date_text)
                    if parsed_date:
                        current_date = parsed_date
                    continue
                if not identifier:
                    continue
                source_index += 1
                external_id = identifier.group(1)
                if "service" in classes:
                    text = compact_text(node.text_content())
                    timestamp = last_timestamp or current_date
                    if timestamp is None:
                        continue
                    yield NormalizedMessage(
                        external_id=external_id,
                        sender_external_id=None,
                        sender_name="Системное сообщение",
                        sent_at=timestamp,
                        source_local_timestamp="missing in Telegram HTML service event",
                        source_timezone_assumption="UTC_PLACEHOLDER_TIME_MISSING",
                        resolution_confidence=0.1,
                        text=text,
                        message_type="service",
                        metadata={"html_file": page_name, "source_index": source_index},
                    )
                    continue
                date_titles = node.xpath(
                    ".//div[contains(concat(' ', normalize-space(@class), ' '), "
                    "' date ') and contains(concat(' ', normalize-space(@class), ' '), "
                    "' details ')]/@title"
                )
                if not date_titles:
                    continue
                timestamp = datetime.strptime(date_titles[0], "%d %B %Y, %H:%M:%S").replace(
                    tzinfo=UTC
                )
                last_timestamp = timestamp
                name_nodes = node.xpath(
                    ".//div[contains(concat(' ', normalize-space(@class), ' '), ' from_name ')]"
                )
                if name_nodes:
                    last_sender_source_name = compact_text(name_nodes[0].text_content())
                    photo_sources = node.xpath(
                        ".//div[contains(concat(' ', normalize-space(@class), ' '), "
                        "' userpic_wrap ')]//img/@src"
                    )
                    profile_links = name_nodes[0].xpath(".//a/@href")
                    last_sender_id, last_sender_identity_basis = self._sender_identity(
                        last_sender_source_name,
                        photo_sources,
                        profile_links,
                        source_directory,
                    )
                    last_sender_name = last_sender_source_name
                    last_sender_run_id = (
                        f"message:{external_id}"
                        if last_sender_identity_basis == "unresolved_sender_run"
                        else None
                    )
                text_nodes = node.xpath(
                    ".//div[contains(concat(' ', normalize-space(@class), ' '), ' text ')]"
                )
                text = self._node_text(text_nodes[0]) if text_nodes else ""
                reply_links = node.xpath(
                    ".//div[contains(concat(' ', normalize-space(@class), ' '), "
                    "' reply_to ')]//a/@href"
                )
                reply_to = self._reply_target(reply_links[0]) if reply_links else None
                reactions = [
                    {
                        "emoji": compact_text(reaction.text_content()),
                        "count": self._reaction_count(reaction),
                    }
                    for reaction in node.xpath(
                        ".//span[contains(concat(' ', normalize-space(@class), ' '), ' reaction ')]"
                    )
                ]
                media, attachments = self._media(node, external_id)
                forwarded = node.xpath(
                    ".//div[contains(concat(' ', normalize-space(@class), ' '), "
                    "' forwarded_from ')]"
                )
                links = text_nodes[0].xpath(".//a/@href") if text_nodes else []
                yield NormalizedMessage(
                    external_id=external_id,
                    sender_external_id=last_sender_id,
                    sender_name=last_sender_name,
                    sent_at=timestamp,
                    source_local_timestamp=date_titles[0],
                    source_timezone_assumption="UTC_PLACEHOLDER_TIMEZONE_UNSPECIFIED",
                    resolution_confidence=0.5,
                    text=text,
                    reply_to_external_id=reply_to,
                    message_type="message",
                    metadata={
                        "html_file": page_name,
                        "source_index": source_index,
                        "source_sender_name": last_sender_source_name,
                        "sender_identity_basis": last_sender_identity_basis,
                        "unresolved_sender_run_id": last_sender_run_id,
                        "joined_sender_inherited": "joined" in classes,
                        "reactions": reactions,
                        "forwarded_from": (
                            compact_text(forwarded[0].text_content()) if forwarded else None
                        ),
                        "links": links,
                        "media": media,
                    },
                    attachments=attachments,
                )

    @contextmanager
    def _page_stream(self, path: Path, name: str) -> Iterator[BinaryIO]:
        if path.is_dir():
            with (path / name).open("rb") as stream:
                yield stream
            return
        with tarfile.open(path, mode="r") as archive:
            member = archive.getmember(name)
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ValueError(f"cannot read Telegram HTML member: {name}")
            with extracted:
                yield extracted

    def _pages(self, path: Path) -> Iterator[tuple[str, BinaryIO]]:
        for name in self._page_names(path):
            with self._page_stream(path, name) as stream:
                yield name, stream

    @staticmethod
    def _parse(stream: BinaryIO):
        return lxml_html.parse(stream, parser=lxml_html.HTMLParser(encoding="utf-8")).getroot()

    @staticmethod
    def _node_text(node) -> str:
        for line_break in node.xpath(".//br"):
            line_break.tail = f"\n{line_break.tail or ''}"
        return compact_text(node.text_content())

    @staticmethod
    def _page_names(path: Path) -> list[str]:
        if path.is_dir():
            names = [candidate.name for candidate in path.glob("messages*.html")]
        elif tarfile.is_tarfile(path):
            with tarfile.open(path, mode="r") as archive:
                names = [
                    member.name
                    for member in archive.getmembers()
                    if member.isfile() and PAGE_PATTERN.match(Path(member.name).name)
                ]
        else:
            raise ValueError("Telegram HTML import requires an export directory or tar archive")
        return sorted(names, key=page_order)

    @staticmethod
    def _parse_date_heading(value: str) -> datetime | None:
        try:
            return datetime.strptime(value, "%d %B %Y").replace(tzinfo=UTC)
        except ValueError:
            return None

    @staticmethod
    def _sender_identity(
        name: str,
        photo_sources: list[str],
        profile_links: list[str],
        source_directory: dict[str, str],
    ) -> tuple[str | None, str]:
        if photo_sources:
            match = re.search(r"author_(\d+)", photo_sources[0])
            if match:
                return f"user{match.group(1)}", "telegram_user_id"
        for link in profile_links:
            match = re.match(r"https?://t\.me/([A-Za-z0-9_]{5,})/?$", link)
            if match:
                return f"username:{match.group(1).casefold()}", "telegram_username"
        mapped_id = source_directory.get(name.casefold())
        if mapped_id is not None:
            return f"user{mapped_id}", "source_directory_mapping"
        return None, "unresolved_sender_run"

    def _source_identity_directory(self, path: Path) -> dict[str, str]:
        candidates: defaultdict[str, set[str]] = defaultdict(set)
        for _page_name, page in self._pages(path):
            root = self._parse(page)
            text_nodes = root.xpath(
                "//div[contains(concat(' ', normalize-space(@class), ' '), ' text ') "
                "and count(.//code) >= 3]"
            )
            for node in text_nodes:
                numeric_codes = [
                    compact_text(code.text_content())
                    for code in node.xpath(".//code")
                    if compact_text(code.text_content()).isdigit()
                ]
                if len(numeric_codes) < 3:
                    continue
                for match in DIRECTORY_LINE_PATTERN.finditer(self._node_text(node)):
                    name = compact_text(match.group("name"))
                    if name:
                        candidates[name.casefold()].add(match.group("user_id"))
        return {
            name: next(iter(user_ids))
            for name, user_ids in candidates.items()
            if len(user_ids) == 1
        }

    @staticmethod
    def _reply_target(value: str) -> str | None:
        match = MESSAGE_ID_PATTERN.search(value)
        return match.group(1) if match else None

    @staticmethod
    def _reaction_count(node) -> int:
        counts = node.xpath(
            ".//span[contains(concat(' ', normalize-space(@class), ' '), ' count ')]/text()"
        )
        try:
            return int(compact_text(counts[0])) if counts else 1
        except ValueError:
            return 1

    @staticmethod
    def _media(node, external_id: str) -> tuple[list[dict], list[NormalizedAttachment]]:
        media: list[dict] = []
        attachments: list[NormalizedAttachment] = []
        for media_node in node.xpath(
            ".//div[contains(concat(' ', normalize-space(@class), ' '), ' media_wrap ')]"
        ):
            titles = media_node.xpath(
                ".//div[contains(concat(' ', normalize-space(@class), ' '), ' title ')]"
            )
            statuses = media_node.xpath(
                ".//div[contains(concat(' ', normalize-space(@class), ' '), ' status ')]"
            )
            hrefs = media_node.xpath(".//a/@href")
            title = compact_text(titles[0].text_content()) if titles else "Attachment"
            status = compact_text(statuses[0].text_content()) if statuses else None
            included = bool(hrefs)
            record = {
                "title": title,
                "status": status,
                "included": included,
                "path": hrefs[0] if included else None,
            }
            media.append(record)
            attachments.append(
                NormalizedAttachment(
                    path=(
                        hrefs[0]
                        if included
                        else f"telegram-html://not-included/{external_id}/{title}"
                    ),
                    caption=None,
                    metadata=record,
                )
            )
        return media, attachments
