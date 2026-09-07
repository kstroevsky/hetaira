from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from prometheus_observatory.analyzer import DeterministicAnalyzer
from prometheus_observatory.annotation_workbench import AnnotationWorkbenchService
from prometheus_observatory.codebooks import register_codebooks
from prometheus_observatory.evaluation import evaluate_frozen_set
from prometheus_observatory.importers import ImportService
from prometheus_observatory.models import (
    Annotation,
    AnnotationReview,
    AnnotationSetAnnotation,
    Corpus,
)
from prometheus_observatory.object_store import ContentAddressedStore

FIXTURE = Path(__file__).parent / "fixtures" / "telegram.json"


def annotation_set(
    session: Session,
    tmp_path: Path,
    *,
    name: str = "gold-ru-v0",
    double_annotation_fraction: float = 0,
    target_size: int = 2,
    judgment_protocol: str = "legacy_review",
):
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
        name=name,
        target_size=target_size,
        codebook_key="foundational-conversation-ru",
        codebook_version="0.1.0",
        double_annotation_fraction=double_annotation_fraction,
        judgment_protocol=judgment_protocol,
    )
    return created


def test_blind_task_judgments_require_explicit_final_completion(
    db_session: Session, tmp_path: Path
) -> None:
    created = annotation_set(
        db_session,
        tmp_path,
        name="reference-ru-pilot-v1",
        double_annotation_fraction=1,
        target_size=1,
        judgment_protocol="blind_ab_final_v1",
    )
    service = AnnotationWorkbenchService(db_session)
    unit = service.list_units(created.id, limit=1)[0]
    assert unit["object_type"] == "anchor_message"
    assert unit["annotations"] == []
    assert set(unit["judgment_progress"]) == {"A", "B", "FINAL"}
    assert all(progress["completed"] == 0 for progress in unit["judgment_progress"].values())
    assert {
        judgment["slot"] for judgment in service.unit_context(unit["id"], "A")["judgments"]
    } == {"A"}
    assert {
        judgment["slot"] for judgment in service.unit_context(unit["id"], "B")["judgments"]
    } == {"B"}
    assert {
        judgment["slot"] for judgment in service.unit_context(unit["id"], "FINAL")["judgments"]
    } == {"A", "B", "FINAL"}

    with pytest.raises(ValueError, match="FINAL adjudication requires"):
        service.submit_task_judgment(
            unit["id"],
            "dialogue_act",
            "FINAL",
            status="ABSENT",
            annotator="adjudicator-c",
            annotations=[],
        )
    for task in created.sampling_spec["required_tasks"]:
        for slot, annotator in (("A", "annotator-a"), ("B", "annotator-b")):
            service.submit_task_judgment(
                unit["id"],
                task,
                slot,
                status="ABSENT",
                annotator=annotator,
                annotations=[],
            )
        service.submit_task_judgment(
            unit["id"],
            task,
            "FINAL",
            status="ABSENT",
            annotator="adjudicator-c",
            annotations=[],
        )
    statistics = service.statistics(created.id)
    assert statistics["confirmed_units"] == 1
    assert statistics["double_annotation"]["completed"] == 1
    assert statistics["agreement"]["stage"] == "independent_A_vs_B_pre_adjudication"
    assert statistics["agreement"]["comparable_unit_kinds"] == 6
    assert statistics["freeze_ready"] is True
    assert service.freeze(created.id).status == "frozen"


def test_present_judgment_preserves_duplicate_labels_at_different_spans(
    db_session: Session, tmp_path: Path
) -> None:
    created = annotation_set(
        db_session,
        tmp_path,
        name="reference-ru-multiplicity-v1",
        target_size=1,
        judgment_protocol="blind_ab_final_v1",
    )
    service = AnnotationWorkbenchService(db_session)
    unit = service.list_units(created.id, limit=1)[0]
    text = unit["text"]
    midpoint = max(1, len(text) // 2)
    service.submit_task_judgment(
        unit["id"],
        "dialogue_act",
        "A",
        status="PRESENT",
        annotator="annotator-a",
        annotations=[
            {
                "kind": "dialogue_act",
                "value": {"label": "ASSERT"},
                "spans": [{"start_codepoint": 0, "end_codepoint": midpoint}],
            },
            {
                "kind": "dialogue_act",
                "value": {"label": "ASSERT"},
                "spans": [{"start_codepoint": midpoint, "end_codepoint": len(text)}],
            },
        ],
    )
    context = service.unit_context(unit["id"], "A")
    judgment = next(item for item in context["judgments"] if item["task"] == "dialogue_act")
    assert judgment["status"] == "PRESENT"
    assert len(judgment["annotations"]) == 2
    assert judgment["annotations"][0]["value"] == judgment["annotations"][1]["value"]
    assert (
        judgment["annotations"][0]["evidence"][0]["start_codepoint"]
        != judgment["annotations"][1]["evidence"][0]["start_codepoint"]
    )


def test_reference_sampling_scans_snapshot_and_context_resolves_reply_target(
    db_session: Session, tmp_path: Path
) -> None:
    created = annotation_set(
        db_session,
        tmp_path,
        name="reference-ru-context-v1",
        target_size=2,
        judgment_protocol="blind_ab_final_v1",
    )
    assert created.sampling_spec["strategy"] == "whole-snapshot-multistrata-bottom-hash-v1"
    assert created.sampling_spec["sampling_scope"] == "complete_snapshot"
    assert created.sampling_spec["scanned_units"] == 2
    assert created.sampling_spec["split_strategy"] == "deterministic-group-balanced-v2"
    service = AnnotationWorkbenchService(db_session)
    reply_unit = next(
        unit for unit in service.list_units(created.id) if unit["strata"]["has_explicit_reply"]
    )
    context = service.unit_context(reply_unit["id"], "A")
    assert sum(message["labelable"] for message in context["messages"]) == 1
    assert any(
        message["context_role"] == "reply_target" and not message["labelable"]
        for message in context["messages"]
    )
    with pytest.raises(ValueError, match="slot B"):
        service.unit_context(reply_unit["id"], "B")


def test_independent_judgments_require_distinct_humans_and_abstain_has_no_labels(
    db_session: Session, tmp_path: Path
) -> None:
    created = annotation_set(
        db_session,
        tmp_path,
        name="reference-ru-independent-v1",
        target_size=1,
        double_annotation_fraction=1,
        judgment_protocol="blind_ab_final_v1",
    )
    service = AnnotationWorkbenchService(db_session)
    unit = service.list_units(created.id, limit=1)[0]
    service.submit_task_judgment(
        unit["id"],
        "dialogue_act",
        "A",
        status="ABSENT",
        annotator="annotator-a",
        annotations=[],
    )
    with pytest.raises(ValueError, match="distinct annotators"):
        service.submit_task_judgment(
            unit["id"],
            "dialogue_act",
            "B",
            status="ABSENT",
            annotator="annotator-a",
            annotations=[],
        )
    with pytest.raises(ValueError, match="cannot contain"):
        service.submit_task_judgment(
            unit["id"],
            "proposition",
            "A",
            status="ABSTAIN",
            annotator="annotator-a",
            annotations=[
                {
                    "kind": "proposition",
                    "value": {"type": "claim"},
                    "spans": [{"start_codepoint": 0, "end_codepoint": 1}],
                }
            ],
        )


def test_gold_v1_enforces_deterministic_double_annotation_cohort(
    db_session: Session, tmp_path: Path
) -> None:
    created = annotation_set(
        db_session,
        tmp_path,
        name="gold-ru-v1",
        double_annotation_fraction=0.5,
    )
    service = AnnotationWorkbenchService(db_session)
    units = service.list_units(created.id)
    double_units = [unit for unit in units if unit["strata"]["double_annotation_required"]]
    assert len(double_units) == 1
    assert created.sampling_spec["double_annotation_required"] == 1

    for unit in units:
        annotation = service.add_annotation(
            unit["id"],
            kind="proposition",
            value={"type": "claim", "text": unit["text"]},
            spans=[{"start_codepoint": 0, "end_codepoint": len(unit["text"])}],
            annotator="annotator-a",
        )
        service.review(annotation.id, decision="confirmed", reviewer="reviewer-a")
    statistics = service.statistics(created.id)
    assert statistics["total_units"] == 2
    assert statistics["confirmed_units"] == 2
    assert statistics["double_annotation"] == {
        "required": 1,
        "completed": 0,
        "fraction": 0.5,
    }
    assert statistics["freeze_ready"] is False
    with pytest.raises(ValueError, match="two confirmed annotators"):
        service.freeze(created.id)

    double_unit = double_units[0]
    second = service.add_annotation(
        double_unit["id"],
        kind="proposition",
        value={"type": "claim", "text": double_unit["text"]},
        spans=[{"start_codepoint": 0, "end_codepoint": len(double_unit["text"])}],
        annotator="annotator-b",
    )
    service.review(second.id, decision="confirmed", reviewer="reviewer-b")
    statistics = service.statistics(created.id)
    assert statistics["double_annotation"]["completed"] == 1
    assert statistics["agreement"] == {
        "comparable_unit_kinds": 1,
        "exact": 1,
        "raw_rate": 1,
    }
    assert statistics["freeze_ready"] is True
    assert service.freeze(created.id).status == "frozen"


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


def test_frozen_gold_set_evaluates_versioned_analysis_run(
    db_session: Session, tmp_path: Path
) -> None:
    register_codebooks(db_session)
    corpus = Corpus(name="Evaluation pilot", language="ru", privacy_policy="LOCAL_ONLY")
    db_session.add(corpus)
    db_session.commit()
    with FIXTURE.open("rb") as source:
        stored = ContentAddressedStore(tmp_path / "objects").put_stream(source)
    imported = ImportService(db_session).import_object(
        corpus, stored, FIXTURE.name, "application/json", "telegram"
    )
    run = DeterministicAnalyzer(db_session).analyze(corpus.id)
    service = AnnotationWorkbenchService(db_session)
    created = service.create_set(
        corpus_id=corpus.id,
        snapshot_id=imported.snapshot_id,
        name="gold-ru-evaluation-v0",
        target_size=1,
        codebook_key="foundational-conversation-ru",
        codebook_version="0.1.0",
    )
    unit = service.list_units(created.id, limit=1)[0]
    machine = next(
        annotation
        for annotation in db_session.scalars(
            select(Annotation).where(
                Annotation.run_id == run.id,
                Annotation.kind == "dialogue_act",
            )
        )
        if annotation.evidence[0]["revision_id"] == unit["revision_id"]
    )
    evidence = machine.evidence[0]
    human = service.add_annotation(
        unit["id"],
        kind="dialogue_act",
        value={"label": machine.value["label"]},
        spans=[
            {
                "start_codepoint": evidence["start_codepoint"],
                "end_codepoint": evidence["end_codepoint"],
            }
        ],
        annotator="annotator-a",
    )
    service.review(human.id, decision="confirmed", reviewer="reviewer-b")
    service.freeze(created.id)
    report = evaluate_frozen_set(db_session, created.id, run.id)
    assert report["annotation_set_manifest_hash"]
    assert report["by_kind"]["dialogue_act"]["true_positive"] >= 1
    assert report["span_exact_match"] == 1
