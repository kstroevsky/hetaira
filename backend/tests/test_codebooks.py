from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from prometheus_observatory.codebooks import register_codebooks
from prometheus_observatory.models import CodebookArtifact, CodebookRelease


def test_same_codebook_release_with_different_artifact_fails(db_session: Session) -> None:
    register_codebooks(db_session)
    release = db_session.scalar(
        select(CodebookRelease).where(
            CodebookRelease.codebook_key == "foundational-conversation-ru"
        )
    )
    assert release is not None
    conflicting_hash = "0" * 64
    db_session.add(CodebookArtifact(content_hash=conflicting_hash, content="changed: true"))
    release.artifact_hash = conflicting_hash
    db_session.commit()
    with pytest.raises(RuntimeError, match="changed bytes"):
        register_codebooks(db_session)
