from __future__ import annotations

import hashlib
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CodebookVersion

CODEBOOK_ROOT = Path(__file__).parent / "codebooks"


def load_codebook(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def register_codebooks(session: Session) -> None:
    for path in sorted(CODEBOOK_ROOT.rglob("*.yaml")):
        raw = path.read_bytes()
        payload = yaml.safe_load(raw)
        key = payload["codebook_key"]
        version = str(payload["version"])
        existing = session.scalar(
            select(CodebookVersion).where(
                CodebookVersion.codebook_key == key,
                CodebookVersion.version == version,
            )
        )
        if existing is None:
            session.add(
                CodebookVersion(
                    codebook_key=key,
                    version=version,
                    language=payload["language"],
                    content_hash=hashlib.sha256(raw).hexdigest(),
                    source_path=str(path),
                    validated=bool(payload.get("validated", False)),
                )
            )
    session.commit()
