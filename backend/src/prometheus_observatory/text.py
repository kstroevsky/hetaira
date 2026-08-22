import hashlib
import re
import unicodedata

SENTENCE_PATTERN = re.compile(r"[^.!?…\n]+(?:[.!?…]+|$)", re.MULTILINE)


def normalize_text(value: str) -> str:
    return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))


def text_hash(value: str) -> str:
    return hashlib.sha256(normalize_text(value).encode("utf-8")).hexdigest()


def sentence_spans(value: str) -> list[tuple[int, int, str]]:
    normalized = normalize_text(value)
    spans: list[tuple[int, int, str]] = []
    for match in SENTENCE_PATTERN.finditer(normalized):
        raw = match.group(0)
        left_trim = len(raw) - len(raw.lstrip())
        right = len(raw.rstrip())
        start = match.start() + left_trim
        end = match.start() + right
        if start < end:
            spans.append((start, end, normalized[start:end]))
    return spans or ([(0, len(normalized), normalized)] if normalized else [])


def initials(name: str) -> str:
    parts = [part for part in re.split(r"\s+", name.strip()) if part]
    return "".join(part[0].upper() for part in parts[:2]) or "?"
