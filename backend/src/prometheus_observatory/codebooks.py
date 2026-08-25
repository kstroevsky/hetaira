from __future__ import annotations

import hashlib
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CodebookArtifact, CodebookRelease, CodebookVersion

CODEBOOK_ROOT = Path(__file__).parent / "codebooks"


def load_codebook(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def register_codebooks(session: Session) -> None:
    for path in sorted(CODEBOOK_ROOT.rglob("*.yaml")):
        raw = path.read_bytes()
        content_hash = hashlib.sha256(raw).hexdigest()
        payload = yaml.safe_load(raw)
        key = payload["codebook_key"]
        version = str(payload["version"])
        existing = session.scalar(
            select(CodebookRelease).where(
                CodebookRelease.codebook_key == key,
                CodebookRelease.semantic_version == version,
            )
        )
        if existing is not None and existing.artifact_hash != content_hash:
            raise RuntimeError(
                f"codebook release {key}@{version} changed bytes: "
                f"{existing.artifact_hash} != {content_hash}"
            )
        if session.get(CodebookArtifact, content_hash) is None:
            session.add(CodebookArtifact(content_hash=content_hash, content=raw.decode("utf-8")))
        if existing is None:
            session.add(
                CodebookRelease(
                    codebook_key=key,
                    semantic_version=version,
                    language=payload["language"],
                    artifact_hash=content_hash,
                    validated=bool(payload.get("validated", False)),
                )
            )
        compatibility = session.scalar(
            select(CodebookVersion).where(
                CodebookVersion.codebook_key == key,
                CodebookVersion.version == version,
            )
        )
        if compatibility is None:
            session.add(
                CodebookVersion(
                    codebook_key=key,
                    version=version,
                    language=payload["language"],
                    content_hash=content_hash,
                    source_path=str(path),
                    validated=bool(payload.get("validated", False)),
                )
            )
        elif compatibility.content_hash != content_hash:
            raise RuntimeError(f"compatibility codebook {key}@{version} changed bytes")
    session.commit()


def release_identity(session: Session, key: str, version: str) -> tuple[str, str]:
    release = session.scalar(
        select(CodebookRelease).where(
            CodebookRelease.codebook_key == key,
            CodebookRelease.semantic_version == version,
        )
    )
    if release is not None:
        return f"{key}@{version}", release.artifact_hash
    for path in CODEBOOK_ROOT.rglob("*.yaml"):
        payload = yaml.safe_load(path.read_bytes())
        if payload["codebook_key"] == key and str(payload["version"]) == version:
            return f"{key}@{version}", hashlib.sha256(path.read_bytes()).hexdigest()
    raise LookupError(f"unknown codebook release: {key}@{version}")
