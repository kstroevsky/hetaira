from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from prometheus_observatory.annotation_workbench import AnnotationWorkbenchService
from prometheus_observatory.codebooks import register_codebooks
from prometheus_observatory.evaluation import (
    ArgumentRelationEvaluator,
    StanceEvaluator,
    evaluate_frozen_set,
    greedy_matches,
)
from prometheus_observatory.importers import ImportService
from prometheus_observatory.models import AnalysisRun, Annotation, Corpus
from prometheus_observatory.object_store import ContentAddressedStore

FIXTURE = Path(__file__).parent / "fixtures" / "telegram.json"


def annotation(
    *,
    kind: str,
    value: dict,
    start: int = 0,
    end: int = 8,
) -> Annotation:
    return Annotation(
        snapshot_id="snapshot",
        run_id="run",
        object_type="anchor_message",
        object_id="message",
        kind=kind,
        value=value,
        evidence=[
            {
                "revision_id": "revision",
                "start_codepoint": start,
                "end_codepoint": end,
            }
        ],
        status="provisional",
        provenance={},
    )


def test_relation_evaluators_require_matching_endpoints() -> None:
    stance = StanceEvaluator()
    gold_stance = annotation(
        kind="stance",
        value={
            "position": "support",
            "holder_id": "bob",
            "target_type": "proposition",
            "target_id": "p1",
        },
    )
    wrong_target = annotation(
        kind="stance",
        value={
            "position": "support",
            "holder_id": "bob",
            "target_type": "proposition",
            "target_id": "p2",
        },
    )
    assert stance.match_score(gold_stance, wrong_target) == 0

    argument = ArgumentRelationEvaluator()
    gold_argument = annotation(
        kind="argumentation",
        value={"relation_type": "SUPPORTS", "source_id": "p3", "target_id": "p1"},
    )
    wrong_argument = annotation(
        kind="argumentation",
        value={"relation_type": "SUPPORTS", "source_id": "p3", "target_id": "p2"},
    )
    assert argument.match_score(gold_argument, wrong_argument) == 0


def test_matching_preserves_duplicate_same_label_spans() -> None:
    evaluator = StanceEvaluator()
    value = {
        "position": "support",
        "holder_id": "bob",
        "target_type": "proposition",
        "target_id": "p1",
    }
    gold = [
        annotation(kind="stance", value=value, start=0, end=4),
        annotation(kind="stance", value=value, start=5, end=9),
    ]
    predicted = [
        annotation(kind="stance", value=value, start=5, end=9),
        annotation(kind="stance", value=value, start=0, end=4),
    ]
    assert len(greedy_matches(evaluator, gold, predicted)) == 2


def test_v2_evaluation_uses_final_task_judgments_and_explicit_absence(
    db_session: Session, tmp_path: Path
) -> None:
    register_codebooks(db_session)
    corpus = Corpus(name="Evaluation v2", language="ru", privacy_policy="LOCAL_ONLY")
    db_session.add(corpus)
    db_session.commit()
    with FIXTURE.open("rb") as source:
        stored = ContentAddressedStore(tmp_path / "objects").put_stream(source)
    imported = ImportService(db_session).import_object(
        corpus, stored, FIXTURE.name, "application/json", "telegram"
    )
    service = AnnotationWorkbenchService(db_session)
    created = service.create_set(
        corpus_id=corpus.id,
        snapshot_id=imported.snapshot_id,
        name="reference-evaluation-v1",
        target_size=1,
        codebook_key="foundational-conversation-ru",
        codebook_version="0.1.0",
        seed="reference-evaluation-v1",
        judgment_protocol="blind_ab_final_v1",
    )
    unit = service.list_units(created.id, limit=1)[0]
    for task in created.sampling_spec["required_tasks"]:
        status = "PRESENT" if task == "dialogue_act" else "ABSENT"
        annotations = (
            [
                {
                    "kind": task,
                    "value": {"label": "ASSERT"},
                    "spans": [{"start_codepoint": 0, "end_codepoint": len(unit["text"])}],
                }
            ]
            if status == "PRESENT"
            else []
        )
        service.submit_task_judgment(
            unit["id"],
            task,
            "A",
            status=status,
            annotator="annotator-a",
            annotations=annotations,
        )
        service.submit_task_judgment(
            unit["id"],
            task,
            "FINAL",
            status=status,
            annotator="adjudicator-c",
            annotations=annotations,
        )
    service.freeze(created.id)
    run = AnalysisRun(
        snapshot_id=imported.snapshot_id,
        run_type="evaluation-fixture",
        status="completed",
        progress=1,
        configuration={},
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db_session.add(run)
    db_session.flush()
    predicted = Annotation(
        snapshot_id=imported.snapshot_id,
        run_id=run.id,
        object_type="anchor_message",
        object_id=unit["object_id"],
        kind="dialogue_act",
        value={"label": "ASSERT"},
        evidence=[
            {
                "revision_id": unit["revision_id"],
                "start_codepoint": 0,
                "end_codepoint": len(unit["text"]),
            }
        ],
        status="provisional",
        raw_confidence=0.9,
        provenance={},
    )
    db_session.add(predicted)
    db_session.commit()

    report = evaluate_frozen_set(db_session, created.id, run.id)

    assert report["schema"] == "hetaira.evaluation-report.v2"
    assert report["gold_source"] == "FINAL_adjudicated_task_judgments"
    assert report["by_task"]["dialogue_act"]["true_positive"] == 1
    assert report["by_task"]["dialogue_act"]["by_class"]["ASSERT"]["f1"] == 1
    assert report["by_task"]["stance"]["explicit_absent_units"] == 1
    assert report["by_task"]["stance"]["absence_accuracy"] == 1
    assert report["by_task"]["stance"]["f1"] is None
    assert report["task_macro_f1"] == 1
