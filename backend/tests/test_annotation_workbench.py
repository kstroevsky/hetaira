from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from prometheus_observatory.annotation_workbench import AnnotationWorkbenchService
from prometheus_observatory.codebooks import register_codebooks
from prometheus_observatory.importers import ImportService
from prometheus_observatory.models import (
    Annotation,
    AnnotationReview,
    AnnotationSetAnnotation,
    Corpus,
)
from prometheus_observatory.object_store import ContentAddressedStore

FIXTURE = Path(__file__).parent / "fixtures" / "telegram.json"


def annotation_set(session: Session, tmp_path: Path):
    register_codebooks(session)
    corpus = Corpus(name="Gold pilot", language="ru", privacy_policy="LOCAL_ONLY")
    session.add(corpus)
    session.commit()
    with FIXTURE.open("rb") as source:
        stored = ContentAddressedStore(tmp_path / "objects").put_stream(source)
    imported = ImportService(session).import_object(
        corpus, stored, FIXTURE.name, "application/json", "telegram"
    )
    created = AnnotationWorkbenchService(session).create_set(
        corpus_id=corpus.id,
        snapshot_id=imported.snapshot_id,
        name="gold-ru-v0",
        target_size=2,
        codebook_key="foundational-conversation-ru",
        codebook_version="0.1.0",
    )
    return created


def test_annotation_set_requires_review_before_cryptographic_freeze(
    db_session: Session, tmp_path: Path
) -> None:
    created = annotation_set(db_session, tmp_path)
    service = AnnotationWorkbenchService(db_session)
    units = service.list_units(created.id)
    assert len(units) == 2
    assert {unit["split"] for unit in units} <= {"train", "development", "test"}
    with pytest.raises(ValueError, match="confirmed annotation"):
        service.freeze(created.id)

    annotation_ids: list[str] = []
    for unit in units:
        annotation = service.add_annotation(
            unit["id"],
            kind="proposition",
            value={"type": "claim", "text": unit["text"]},
            spans=[{"start_codepoint": 0, "end_codepoint": len(unit["text"])}],
            annotator="annotator-a",
        )
        annotation_ids.append(annotation.id)
        service.review(annotation.id, decision="confirmed", reviewer="reviewer-b")
    frozen = service.freeze(created.id)
    assert frozen.status == "frozen"
    assert frozen.manifest_hash and len(frozen.manifest_hash) == 64
    exported = service.export(created.id)
    assert exported["manifest_hash"] == frozen.manifest_hash
    assert len(exported["units"]) == 2
    assert db_session.scalar(select(func.count()).select_from(AnnotationReview)) == 2
    assert all(
        annotation.status == "provisional"
        for annotation in db_session.scalars(
            select(Annotation).where(Annotation.id.in_(annotation_ids))
        )
    )


def test_adjudication_supersedes_without_destroying_original_annotation(
    db_session: Session, tmp_path: Path
) -> None:
    created = annotation_set(db_session, tmp_path)
    service = AnnotationWorkbenchService(db_session)
    unit = service.list_units(created.id, limit=1)[0]
    original = service.add_annotation(
        unit["id"],
        kind="dialogue_act",
        value={"label": "ASSERT"},
        spans=[{"start_codepoint": 0, "end_codepoint": len(unit["text"])}],
        annotator="annotator-a",
    )
    service.review(original.id, decision="disputed", reviewer="reviewer-b")
    replacement = service.add_annotation(
        unit["id"],
        kind="dialogue_act",
        value={"label": "AGREE"},
        spans=[{"start_codepoint": 0, "end_codepoint": len(unit["text"])}],
        annotator="adjudicator-c",
        supersedes_annotation_id=original.id,
    )
    db_session.refresh(original)
    assert original.superseded_by == replacement.id
    assert db_session.get(Annotation, original.id) is not None
    link = db_session.scalar(
        select(AnnotationSetAnnotation).where(
            AnnotationSetAnnotation.annotation_id == replacement.id
        )
    )
    assert link is not None and link.role == "adjudicated"


def test_manual_annotation_rejects_out_of_bounds_evidence(
    db_session: Session, tmp_path: Path
) -> None:
    created = annotation_set(db_session, tmp_path)
    service = AnnotationWorkbenchService(db_session)
    unit = service.list_units(created.id, limit=1)[0]
    with pytest.raises(ValueError, match="outside"):
        service.add_annotation(
            unit["id"],
            kind="stance",
            value={"position": "support"},
            spans=[{"start_codepoint": 0, "end_codepoint": len(unit["text"]) + 1}],
            annotator="annotator-a",
        )
