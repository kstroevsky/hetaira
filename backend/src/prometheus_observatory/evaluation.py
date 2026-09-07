from __future__ import annotations

from collections import Counter, defaultdict
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
    GoldJudgmentAnnotation,
    GoldTaskJudgment,
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
    if annotation_set.sampling_spec.get("judgment_protocol") == "blind_ab_final_v1":
        return evaluate_task_judgments(session, annotation_set, run)
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


class TaskEvaluator:
    task = ""

    def class_label(self, annotation: Annotation) -> str:
        return annotation_label(annotation)

    def match_score(self, gold: Annotation, predicted: Annotation) -> float:
        if self.class_label(gold).casefold() != self.class_label(predicted).casefold():
            return 0
        return span_overlap_f1(first_span(gold), first_span(predicted))


class DialogueActEvaluator(TaskEvaluator):
    task = "dialogue_act"


class PropositionSpanEvaluator(TaskEvaluator):
    task = "proposition"

    def class_label(self, annotation: Annotation) -> str:
        return str(annotation.value.get("type", "claim"))


def endpoint(value: dict[str, Any], *keys: str) -> tuple[str, str] | None:
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, dict):
            identifier = candidate.get("id") or candidate.get("object_id")
            kind = candidate.get("type") or candidate.get("object_type") or key
            if identifier:
                return str(kind), str(identifier)
        if candidate is not None:
            if "proposition" in key:
                kind = "proposition"
            elif "message" in key:
                kind = "message"
            elif key == "holder_id":
                kind = "participant"
            elif key == "source_id":
                kind = str(value.get("source_type", "source"))
            elif key == "target_id":
                kind = str(value.get("target_type", "target"))
            else:
                kind = key
            return kind, str(candidate)
    return None


class StanceEvaluator(TaskEvaluator):
    task = "stance"

    def class_label(self, annotation: Annotation) -> str:
        return str(annotation.value.get("position", "unknown"))

    def match_score(self, gold: Annotation, predicted: Annotation) -> float:
        if self.class_label(gold).casefold() != self.class_label(predicted).casefold():
            return 0
        if endpoint(gold.value, "holder_id") != endpoint(predicted.value, "holder_id"):
            return 0
        if endpoint(
            gold.value, "target_id", "target_proposition_id", "target_message_id", "target"
        ) != endpoint(
            predicted.value,
            "target_id",
            "target_proposition_id",
            "target_message_id",
            "target",
        ):
            return 0
        return 1 + span_overlap_f1(first_span(gold), first_span(predicted))


class EpistemicEvaluator(TaskEvaluator):
    task = "epistemic_state"

    def class_label(self, annotation: Annotation) -> str:
        return str(annotation.value.get("label") or annotation.value.get("polarity") or "unknown")

    def match_score(self, gold: Annotation, predicted: Annotation) -> float:
        if self.class_label(gold).casefold() != self.class_label(predicted).casefold():
            return 0
        for keys in (("holder_id",), ("proposition_id", "target_id", "target")):
            if endpoint(gold.value, *keys) != endpoint(predicted.value, *keys):
                return 0
        return 1 + span_overlap_f1(first_span(gold), first_span(predicted))


class GroundingEvaluator(TaskEvaluator):
    task = "grounding"

    def match_score(self, gold: Annotation, predicted: Annotation) -> float:
        if self.class_label(gold).casefold() != self.class_label(predicted).casefold():
            return 0
        gold_target = endpoint(gold.value, "target_id", "target_message_id", "target")
        predicted_target = endpoint(predicted.value, "target_id", "target_message_id", "target")
        if (gold_target or predicted_target) and gold_target != predicted_target:
            return 0
        return 1 + span_overlap_f1(first_span(gold), first_span(predicted))


class ArgumentRelationEvaluator(TaskEvaluator):
    task = "argumentation"

    def class_label(self, annotation: Annotation) -> str:
        return str(
            annotation.value.get("relation_type") or annotation.value.get("label") or "unknown"
        )

    def match_score(self, gold: Annotation, predicted: Annotation) -> float:
        if self.class_label(gold).casefold() != self.class_label(predicted).casefold():
            return 0
        gold_source = endpoint(
            gold.value, "source_id", "source_proposition_id", "source_message_id", "source"
        )
        predicted_source = endpoint(
            predicted.value,
            "source_id",
            "source_proposition_id",
            "source_message_id",
            "source",
        )
        gold_target = endpoint(
            gold.value, "target_id", "target_proposition_id", "target_message_id", "target"
        )
        predicted_target = endpoint(
            predicted.value,
            "target_id",
            "target_proposition_id",
            "target_message_id",
            "target",
        )
        if gold_source != predicted_source or gold_target != predicted_target:
            return 0
        return 1 + span_overlap_f1(first_span(gold), first_span(predicted))


TASK_EVALUATORS: dict[str, TaskEvaluator] = {
    evaluator.task: evaluator
    for evaluator in (
        DialogueActEvaluator(),
        PropositionSpanEvaluator(),
        StanceEvaluator(),
        EpistemicEvaluator(),
        GroundingEvaluator(),
        ArgumentRelationEvaluator(),
    )
}


def greedy_matches(
    evaluator: TaskEvaluator,
    gold: list[Annotation],
    predicted: list[Annotation],
) -> list[tuple[int, int, float]]:
    candidates = sorted(
        (
            (gold_index, predicted_index, score)
            for gold_index, gold_annotation in enumerate(gold)
            for predicted_index, predicted_annotation in enumerate(predicted)
            if (score := evaluator.match_score(gold_annotation, predicted_annotation)) > 0
        ),
        key=lambda item: item[2],
        reverse=True,
    )
    matched_gold: set[int] = set()
    matched_predicted: set[int] = set()
    output = []
    for gold_index, predicted_index, score in candidates:
        if gold_index in matched_gold or predicted_index in matched_predicted:
            continue
        matched_gold.add(gold_index)
        matched_predicted.add(predicted_index)
        output.append((gold_index, predicted_index, score))
    return output


def evaluate_task_judgments(
    session: Session,
    annotation_set: AnnotationSet,
    run: AnalysisRun,
) -> dict[str, Any]:
    units = list(
        session.scalars(
            select(AnnotationUnit).where(AnnotationUnit.annotation_set_id == annotation_set.id)
        )
    )
    revision_by_unit = {unit.id: unit.revision_id for unit in units}
    unit_by_revision = {unit.revision_id: unit.id for unit in units}
    final_judgments = list(
        session.scalars(
            select(GoldTaskJudgment).where(
                GoldTaskJudgment.annotation_set_id == annotation_set.id,
                GoldTaskJudgment.slot == "FINAL",
            )
        )
    )
    if any(judgment.status == "NOT_ANNOTATED" for judgment in final_judgments):
        raise ValueError("frozen judgment set contains incomplete FINAL tasks")
    links = (
        list(
            session.scalars(
                select(GoldJudgmentAnnotation).where(
                    GoldJudgmentAnnotation.judgment_id.in_(
                        [judgment.id for judgment in final_judgments]
                    )
                )
            )
        )
        if final_judgments
        else []
    )
    annotations_by_judgment: dict[str, list[Annotation]] = defaultdict(list)
    for link in links:
        annotation = session.get(Annotation, link.annotation_id)
        if annotation is not None:
            annotations_by_judgment[link.judgment_id].append(annotation)
    gold_by_task_revision: dict[tuple[str, str], list[Annotation]] = defaultdict(list)
    judgment_status_by_task_revision: dict[tuple[str, str], str] = {}
    for judgment in final_judgments:
        revision_id = revision_by_unit[judgment.unit_id]
        judgment_status_by_task_revision[(judgment.task, revision_id)] = judgment.status
        gold_by_task_revision[(judgment.task, revision_id)].extend(
            annotations_by_judgment[judgment.id]
        )
    predicted_by_task_revision: dict[tuple[str, str], list[Annotation]] = defaultdict(list)
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
                if evidence.get("revision_id") in unit_by_revision
            ),
            None,
        )
        if revision_id and annotation.kind in TASK_EVALUATORS:
            predicted_by_task_revision[(annotation.kind, revision_id)].append(annotation)
    required_tasks = list(annotation_set.sampling_spec.get("required_tasks", TASK_EVALUATORS))
    task_results: dict[str, dict[str, Any]] = {}
    total_tp = total_fp = total_fn = 0
    probabilities: list[tuple[float, int]] = []
    all_overlap: list[float] = []
    exact_spans = matched_spans = 0
    for task in required_tasks:
        evaluator = TASK_EVALUATORS[task]
        task_tp = task_fp = task_fn = 0
        gold_abstain = 0
        explicit_absent = 0
        absent_correct = 0
        class_counts: dict[str, Counter[str]] = defaultdict(Counter)
        for unit in units:
            revision_id = unit.revision_id
            status = judgment_status_by_task_revision[(task, revision_id)]
            gold = gold_by_task_revision[(task, revision_id)]
            predicted = predicted_by_task_revision[(task, revision_id)]
            if status == "ABSTAIN":
                gold_abstain += 1
                continue
            if status == "ABSENT":
                explicit_absent += 1
                absent_correct += int(not predicted)
            matches = greedy_matches(evaluator, gold, predicted)
            matched_gold = {item[0] for item in matches}
            matched_predicted = {item[1] for item in matches}
            task_tp += len(matches)
            task_fn += len(gold) - len(matches)
            task_fp += len(predicted) - len(matches)
            for gold_index, predicted_index, _score in matches:
                label = evaluator.class_label(gold[gold_index])
                class_counts[label]["tp"] += 1
                overlap = span_overlap_f1(
                    first_span(gold[gold_index]), first_span(predicted[predicted_index])
                )
                all_overlap.append(overlap)
                exact_spans += int(
                    first_span(gold[gold_index]) == first_span(predicted[predicted_index])
                )
                matched_spans += 1
            for index, annotation in enumerate(gold):
                if index not in matched_gold:
                    class_counts[evaluator.class_label(annotation)]["fn"] += 1
            for index, annotation in enumerate(predicted):
                matched = index in matched_predicted
                if not matched:
                    class_counts[evaluator.class_label(annotation)]["fp"] += 1
                if annotation.raw_confidence is not None:
                    probabilities.append((annotation.raw_confidence, int(matched)))
        has_positive_evaluation = bool(task_tp + task_fp + task_fn)
        precision = task_tp / (task_tp + task_fp) if task_tp + task_fp else 0 if task_fn else None
        recall = task_tp / (task_tp + task_fn) if task_tp + task_fn else 0 if task_fp else None
        f1 = (
            2 * precision * recall / (precision + recall)
            if has_positive_evaluation
            and precision is not None
            and recall is not None
            and precision + recall
            else 0
            if has_positive_evaluation
            else None
        )
        by_class = {}
        for label, counts in class_counts.items():
            class_precision = (
                counts["tp"] / (counts["tp"] + counts["fp"]) if counts["tp"] + counts["fp"] else 0
            )
            class_recall = (
                counts["tp"] / (counts["tp"] + counts["fn"]) if counts["tp"] + counts["fn"] else 0
            )
            by_class[label] = {
                "true_positive": counts["tp"],
                "false_positive": counts["fp"],
                "false_negative": counts["fn"],
                "precision": class_precision,
                "recall": class_recall,
                "f1": 2 * class_precision * class_recall / (class_precision + class_recall)
                if class_precision + class_recall
                else 0,
            }
        task_results[task] = {
            "evaluator": type(evaluator).__name__,
            "true_positive": task_tp,
            "false_positive": task_fp,
            "false_negative": task_fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "gold_abstain_units": gold_abstain,
            "explicit_absent_units": explicit_absent,
            "absence_accuracy": (absent_correct / explicit_absent if explicit_absent else None),
            "by_class": by_class,
        }
        total_tp += task_tp
        total_fp += task_fp
        total_fn += task_fn
    micro_precision = total_tp / (total_tp + total_fp) if total_tp + total_fp else 0
    micro_recall = total_tp / (total_tp + total_fn) if total_tp + total_fn else 0
    return {
        "schema": "hetaira.evaluation-report.v2",
        "annotation_set_id": annotation_set.id,
        "annotation_set_manifest_hash": annotation_set.manifest_hash,
        "analysis_run_id": run.id,
        "snapshot_id": run.snapshot_id,
        "gold_source": "FINAL_adjudicated_task_judgments",
        "task_macro_f1": (
            mean(result["f1"] for result in task_results.values() if result["f1"] is not None)
            if any(result["f1"] is not None for result in task_results.values())
            else None
        ),
        "micro_precision": micro_precision,
        "micro_recall": micro_recall,
        "micro_f1": 2 * micro_precision * micro_recall / (micro_precision + micro_recall)
        if micro_precision + micro_recall
        else 0,
        "span_exact_match": exact_spans / matched_spans if matched_spans else 0,
        "span_overlap_f1": mean(all_overlap) if all_overlap else 0,
        "brier_score": mean((probability - outcome) ** 2 for probability, outcome in probabilities)
        if probabilities
        else None,
        "ece_10_bin": expected_calibration_error(probabilities),
        "by_task": task_results,
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
