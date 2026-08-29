from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AnalysisRun,
    Annotation,
    AnnotationReview,
    AnnotationSet,
    AnnotationSetAnnotation,
    AnnotationUnit,
)


def annotation_label(annotation: Annotation) -> str:
    value = annotation.value
    return str(
        value.get("label")
        or value.get("position")
        or value.get("type")
        or value.get("text")
        or annotation.kind
    )


def first_span(annotation: Annotation) -> tuple[int, int] | None:
    for evidence in annotation.evidence:
        start = evidence.get("start_codepoint")
        end = evidence.get("end_codepoint")
        if isinstance(start, int) and isinstance(end, int):
            return start, end
    return None


def span_overlap_f1(left: tuple[int, int] | None, right: tuple[int, int] | None) -> float:
    if left is None or right is None:
        return 0
    overlap = max(0, min(left[1], right[1]) - max(left[0], right[0]))
    if overlap == 0:
        return 0
    precision = overlap / max(right[1] - right[0], 1)
    recall = overlap / max(left[1] - left[0], 1)
    return 2 * precision * recall / (precision + recall)


def evaluate_frozen_set(
    session: Session, annotation_set_id: str, analysis_run_id: str
) -> dict[str, Any]:
    annotation_set = session.get(AnnotationSet, annotation_set_id)
    run = session.get(AnalysisRun, analysis_run_id)
    if annotation_set is None or run is None:
        raise LookupError("annotation set or analysis run not found")
    if annotation_set.status != "frozen":
        raise ValueError("evaluation requires a frozen annotation set")
    if run.snapshot_id != annotation_set.snapshot_id:
        raise ValueError("analysis run and gold set must use the same snapshot")
    units = list(
        session.scalars(
            select(AnnotationUnit).where(AnnotationUnit.annotation_set_id == annotation_set.id)
        )
    )
    revision_by_unit = {unit.id: unit.revision_id for unit in units}
    gold: dict[tuple[str, str, str], Annotation] = {}
    links = session.scalars(
        select(AnnotationSetAnnotation).where(
            AnnotationSetAnnotation.annotation_set_id == annotation_set.id
        )
    )
    for link in links:
        annotation = session.get(Annotation, link.annotation_id)
        if annotation is None or annotation.superseded_by:
            continue
        review = session.scalar(
            select(AnnotationReview)
            .where(AnnotationReview.annotation_id == annotation.id)
            .order_by(AnnotationReview.reviewed_at.desc(), AnnotationReview.id.desc())
        )
        if review is not None and review.decision == "confirmed":
            revision_id = revision_by_unit[link.unit_id]
            gold[(revision_id, annotation.kind, annotation_label(annotation))] = annotation
    allowed_revisions = set(revision_by_unit.values())
    predicted: dict[tuple[str, str, str], Annotation] = {}
    for annotation in session.scalars(
        select(Annotation).where(
            Annotation.run_id == run.id,
            Annotation.superseded_by.is_(None),
        )
    ):
        revision_id = next(
            (
                evidence.get("revision_id")
                for evidence in annotation.evidence
                if evidence.get("revision_id") in allowed_revisions
            ),
            None,
        )
        if revision_id:
            predicted[(revision_id, annotation.kind, annotation_label(annotation))] = annotation
    kinds = sorted({key[1] for key in gold} | {key[1] for key in predicted})
    by_kind: dict[str, dict[str, Any]] = {}
    probabilities: list[tuple[float, int]] = []
    overlap_scores: list[float] = []
    exact_spans = 0
    matched = 0
    totals = defaultdict(int)
    for kind in kinds:
        gold_keys = {key for key in gold if key[1] == kind}
        predicted_keys = {key for key in predicted if key[1] == kind}
        true_positive = len(gold_keys & predicted_keys)
        false_positive = len(predicted_keys - gold_keys)
        false_negative = len(gold_keys - predicted_keys)
        precision = true_positive / (true_positive + false_positive) if predicted_keys else 0
        recall = true_positive / (true_positive + false_negative) if gold_keys else 0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
        by_kind[kind] = {
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
        totals["tp"] += true_positive
        totals["fp"] += false_positive
        totals["fn"] += false_negative
        for key in gold_keys & predicted_keys:
            gold_span = first_span(gold[key])
            predicted_span = first_span(predicted[key])
            overlap_scores.append(span_overlap_f1(gold_span, predicted_span))
            exact_spans += int(gold_span == predicted_span)
            matched += 1
    for key, annotation in predicted.items():
        if annotation.raw_confidence is not None:
            probabilities.append((annotation.raw_confidence, int(key in gold)))
    micro_precision = (
        totals["tp"] / (totals["tp"] + totals["fp"]) if totals["tp"] + totals["fp"] else 0
    )
    micro_recall = (
        totals["tp"] / (totals["tp"] + totals["fn"]) if totals["tp"] + totals["fn"] else 0
    )
    micro_f1 = (
        2 * micro_precision * micro_recall / (micro_precision + micro_recall)
        if micro_precision + micro_recall
        else 0
    )
    return {
        "schema": "hetaira.evaluation-report.v1",
        "annotation_set_id": annotation_set.id,
        "annotation_set_manifest_hash": annotation_set.manifest_hash,
        "analysis_run_id": run.id,
        "snapshot_id": run.snapshot_id,
        "gold_annotations": len(gold),
        "predicted_annotations": len(predicted),
        "macro_f1": mean(metric["f1"] for metric in by_kind.values()) if by_kind else 0,
        "micro_f1": micro_f1,
        "span_exact_match": exact_spans / matched if matched else 0,
        "span_overlap_f1": mean(overlap_scores) if overlap_scores else 0,
        "brier_score": (
            mean((probability - outcome) ** 2 for probability, outcome in probabilities)
            if probabilities
            else None
        ),
        "ece_10_bin": expected_calibration_error(probabilities),
        "by_kind": by_kind,
    }


def expected_calibration_error(values: list[tuple[float, int]]) -> float | None:
    if not values:
        return None
    error = 0.0
    for lower in range(10):
        minimum = lower / 10
        maximum = (lower + 1) / 10
        bucket = [
            (probability, outcome)
            for probability, outcome in values
            if (
                minimum <= probability <= maximum
                if lower == 9
                else minimum <= probability < maximum
            )
        ]
        if bucket:
            confidence = mean(probability for probability, _outcome in bucket)
            accuracy = mean(outcome for _probability, outcome in bucket)
            error += len(bucket) / len(values) * abs(confidence - accuracy)
    return error
