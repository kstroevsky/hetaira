from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .codebooks import register_codebooks, release_identity
from .config import get_settings
from .models import (
    AnalysisRun,
    Annotation,
    AnnotationReview,
    AnnotationSet,
    AnnotationSetAnnotation,
    AnnotationUnit,
    CodebookArtifact,
    Corpus,
    CorpusSnapshot,
    EpisodeMessage,
    Message,
    MessageRevision,
    SnapshotMessageRevision,
    new_id,
)
from .ontology import RunStatus
from .text import text_hash

REVIEW_DECISIONS = {"confirmed", "disputed", "rejected"}


class AnnotationWorkbenchService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()

    def create_set(
        self,
        *,
        corpus_id: str,
        snapshot_id: str,
        name: str,
        target_size: int,
        codebook_key: str,
        codebook_version: str,
        seed: str = "gold-ru-v0",
        double_annotation_fraction: float = 0,
    ) -> AnnotationSet:
        corpus = self.session.get(Corpus, corpus_id)
        snapshot = self.session.get(CorpusSnapshot, snapshot_id)
        if corpus is None or snapshot is None or snapshot.corpus_id != corpus_id:
            raise LookupError("corpus or snapshot not found")
        if corpus.language != "ru":
            raise ValueError("gold pilot currently accepts Russian corpora only")
        if not 1 <= target_size <= 1_200:
            raise ValueError("target_size must be between 1 and 1200")
        existing = self.session.scalar(
            select(AnnotationSet).where(
                AnnotationSet.snapshot_id == snapshot_id,
                AnnotationSet.name == name,
            )
        )
        if existing is not None:
            if existing.status == "draft":
                self._rebalance_splits(existing)
                self._assign_double_annotation(existing)
                self.session.commit()
            return existing
        release, artifact_hash = release_identity(self.session, codebook_key, codebook_version)
        if "@" not in release:
            raise RuntimeError("invalid codebook release identity")
        if self.session.get(CodebookArtifact, artifact_hash) is None:
            register_codebooks(self.session)
        run = AnalysisRun(
            id=new_id(),
            snapshot_id=snapshot_id,
            run_type="human-annotation",
            status=RunStatus.RUNNING,
            progress=0,
            configuration={
                "annotation_set": name,
                "codebook_release": release,
                "codebook_artifact_hash": artifact_hash,
            },
            started_at=datetime.now(UTC),
        )
        annotation_set = AnnotationSet(
            id=new_id(),
            corpus_id=corpus_id,
            snapshot_id=snapshot_id,
            analysis_run_id=run.id,
            name=name,
            language="ru",
            codebook_key=codebook_key,
            codebook_version=codebook_version,
            codebook_artifact_hash=artifact_hash,
            status="draft",
            target_size=target_size,
            sampling_spec={
                "strategy": "deterministic-stratified-group-balanced-v2",
                "seed": seed,
                "target_size": target_size,
                "split_group": "episode_or_conversation",
                "split_ratio": {"train": 0.6, "development": 0.2, "test": 0.2},
                "double_annotation_fraction": double_annotation_fraction,
            },
        )
        self.session.add_all([run, annotation_set])
        self.session.flush()
        candidates = self._candidate_units(snapshot_id, target_size, seed)
        for ordinal, candidate in enumerate(candidates):
            message, revision, episode_message = candidate
            group_id = episode_message.episode_id if episode_message else message.conversation_id
            annotation_unit = AnnotationUnit(
                id=new_id(),
                annotation_set_id=annotation_set.id,
                object_type="message",
                object_id=message.id,
                revision_id=revision.id,
                group_id=group_id,
                ordinal=ordinal,
                split="pending",
                strata=self._strata(message, revision),
                status="pending",
            )
            self.session.add(annotation_unit)
        self.session.flush()
        self._rebalance_splits(annotation_set)
        self._assign_double_annotation(annotation_set)
        self.session.commit()
        return annotation_set

    def statistics(self, annotation_set_id: str) -> dict[str, Any]:
        annotation_set = self._set(annotation_set_id)
        units = list(
            self.session.scalars(
                select(AnnotationUnit)
                .where(AnnotationUnit.annotation_set_id == annotation_set.id)
                .order_by(AnnotationUnit.ordinal)
            )
        )
        links = list(
            self.session.scalars(
                select(AnnotationSetAnnotation).where(
                    AnnotationSetAnnotation.annotation_set_id == annotation_set.id
                )
            )
        )
        annotations = {
            annotation.id: annotation
            for annotation_id in {link.annotation_id for link in links}
            if (annotation := self.session.get(Annotation, annotation_id)) is not None
        }
        reviews: dict[str, AnnotationReview] = {}
        if annotations:
            for review in self.session.scalars(
                select(AnnotationReview)
                .where(AnnotationReview.annotation_id.in_(annotations))
                .order_by(
                    AnnotationReview.annotation_id,
                    AnnotationReview.reviewed_at.desc(),
                    AnnotationReview.id.desc(),
                )
            ):
                reviews.setdefault(review.annotation_id, review)
        confirmed_by_unit: dict[str, list[Annotation]] = defaultdict(list)
        coverage_by_kind: Counter[str] = Counter()
        agreement_groups: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
        for link in links:
            annotation = annotations.get(link.annotation_id)
            review = reviews.get(link.annotation_id)
            if (
                annotation is None
                or annotation.superseded_by
                or review is None
                or review.decision != "confirmed"
            ):
                continue
            confirmed_by_unit[link.unit_id].append(annotation)
            coverage_by_kind[annotation.kind] += 1
            annotator = str(annotation.provenance.get("model", "unknown"))
            agreement_groups[(link.unit_id, annotation.kind)][annotator] = json.dumps(
                annotation.value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        agreement_total = 0
        agreement_equal = 0
        for values_by_annotator in agreement_groups.values():
            if len(values_by_annotator) < 2:
                continue
            agreement_total += 1
            agreement_equal += int(len(set(values_by_annotator.values())) == 1)
        double_units = [
            unit for unit in units if bool(unit.strata.get("double_annotation_required"))
        ]
        double_completed = 0
        for unit in double_units:
            annotators = {
                str(annotation.provenance.get("model", "unknown"))
                for annotation in confirmed_by_unit.get(unit.id, [])
            }
            double_completed += int(len(annotators) >= 2)
        status_counts = Counter(unit.status for unit in units)
        split_counts = Counter(unit.split for unit in units)
        return {
            "annotation_set_id": annotation_set.id,
            "name": annotation_set.name,
            "status": annotation_set.status,
            "target_size": annotation_set.target_size,
            "total_units": len(units),
            "status_counts": dict(status_counts),
            "split_counts": dict(split_counts),
            "difficult_units": sum(bool(unit.strata.get("difficult")) for unit in units),
            "confirmed_units": len(confirmed_by_unit),
            "coverage_by_kind": dict(coverage_by_kind),
            "double_annotation": {
                "required": len(double_units),
                "completed": double_completed,
                "fraction": annotation_set.sampling_spec.get("double_annotation_fraction", 0),
            },
            "agreement": {
                "comparable_unit_kinds": agreement_total,
                "exact": agreement_equal,
                "raw_rate": agreement_equal / agreement_total if agreement_total else None,
            },
            "freeze_ready": (
                bool(units)
                and len(confirmed_by_unit) == len(units)
                and double_completed == len(double_units)
            ),
            "manifest_hash": annotation_set.manifest_hash,
        }

    def _candidate_units(
        self, snapshot_id: str, target_size: int, seed: str
    ) -> list[tuple[Message, MessageRevision, EpisodeMessage | None]]:
        candidate_limit = max(target_size * 6, 300)
        raw_rows = list(
            self.session.execute(
                select(Message, MessageRevision, EpisodeMessage)
                .join(SnapshotMessageRevision, SnapshotMessageRevision.message_id == Message.id)
                .join(MessageRevision, MessageRevision.id == SnapshotMessageRevision.revision_id)
                .outerjoin(EpisodeMessage, EpisodeMessage.message_id == Message.id)
                .where(SnapshotMessageRevision.snapshot_id == snapshot_id)
                .order_by(Message.id)
                .limit(candidate_limit)
            )
        )
        rows: list[tuple[Message, MessageRevision, EpisodeMessage | None]] = []
        seen_messages: set[str] = set()
        for row in raw_rows:
            if row[0].id not in seen_messages:
                rows.append(row)
                seen_messages.add(row[0].id)
        rows.sort(key=lambda row: hashlib.sha256(f"{seed}:{row[0].id}".encode()).hexdigest())
        difficult = [row for row in rows if self._is_difficult(row[0], row[1])]
        routine = [row for row in rows if not self._is_difficult(row[0], row[1])]
        selected: list[tuple[Message, MessageRevision, EpisodeMessage | None]] = []
        for bucket in (difficult, routine):
            selected.extend(bucket[: target_size // 2])
        selected_ids = {row[0].id for row in selected}
        selected.extend(row for row in rows if row[0].id not in selected_ids)
        return selected[:target_size]

    def list_units(
        self, annotation_set_id: str, *, after_ordinal: int = -1, limit: int = 50
    ) -> list[dict[str, Any]]:
        annotation_set = self._set(annotation_set_id)
        rows = self.session.execute(
            select(AnnotationUnit, Message, MessageRevision)
            .join(Message, Message.id == AnnotationUnit.object_id)
            .join(MessageRevision, MessageRevision.id == AnnotationUnit.revision_id)
            .where(
                AnnotationUnit.annotation_set_id == annotation_set.id,
                AnnotationUnit.ordinal > after_ordinal,
            )
            .order_by(AnnotationUnit.ordinal)
            .limit(min(max(limit, 1), 200))
        )
        return [self._unit_payload(unit, message, revision) for unit, message, revision in rows]

    def add_annotation(
        self,
        unit_id: str,
        *,
        kind: str,
        value: dict[str, Any],
        spans: list[dict[str, int]],
        annotator: str,
        supersedes_annotation_id: str | None = None,
    ) -> Annotation:
        unit = self.session.get(AnnotationUnit, unit_id)
        if unit is None:
            raise LookupError("annotation unit not found")
        annotation_set = self._set(unit.annotation_set_id)
        if annotation_set.status != "draft":
            raise ValueError("frozen annotation sets cannot be modified")
        revision = self.session.get(MessageRevision, unit.revision_id)
        if revision is None:
            raise RuntimeError("annotation unit revision is missing")
        evidence = self._evidence(revision, spans)
        annotation = Annotation(
            id=new_id(),
            snapshot_id=annotation_set.snapshot_id,
            run_id=annotation_set.analysis_run_id,
            object_type=unit.object_type,
            object_id=unit.object_id,
            kind=kind,
            value=value,
            evidence=evidence,
            status="provisional",
            raw_confidence=None,
            calibrated_confidence=None,
            alternatives=[],
            provenance={
                "corpus_snapshot_id": annotation_set.snapshot_id,
                "ontology_version": self.settings.ontology_version,
                "codebook_version": (
                    f"{annotation_set.codebook_key}@{annotation_set.codebook_version}"
                ),
                "codebook_artifact_hash": annotation_set.codebook_artifact_hash,
                "pipeline_version": self.settings.pipeline_version,
                "model_provider": "human",
                "model": annotator,
                "analysis_run_id": annotation_set.analysis_run_id,
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
        self.session.add(annotation)
        self.session.flush()
        role = "adjudicated" if supersedes_annotation_id else "human"
        self.session.add(
            AnnotationSetAnnotation(
                id=new_id(),
                annotation_set_id=annotation_set.id,
                unit_id=unit.id,
                annotation_id=annotation.id,
                role=role,
            )
        )
        if supersedes_annotation_id:
            superseded = self.session.get(Annotation, supersedes_annotation_id)
            if superseded is None or not self._annotation_belongs_to_unit(superseded.id, unit.id):
                raise ValueError("superseded annotation does not belong to this unit")
            superseded.superseded_by = annotation.id
        unit.status = "annotated"
        self.session.commit()
        return annotation

    def review(self, annotation_id: str, *, decision: str, reviewer: str) -> AnnotationReview:
        if decision not in REVIEW_DECISIONS:
            raise ValueError(f"unknown review decision: {decision}")
        annotation = self.session.get(Annotation, annotation_id)
        if annotation is None:
            raise LookupError("annotation not found")
        link = self.session.scalar(
            select(AnnotationSetAnnotation).where(
                AnnotationSetAnnotation.annotation_id == annotation_id
            )
        )
        if link is None:
            raise ValueError("annotation is not part of an annotation set")
        annotation_set = self._set(link.annotation_set_id)
        if annotation_set.status != "draft":
            raise ValueError("frozen annotation sets cannot be reviewed")
        review = AnnotationReview(
            id=new_id(),
            annotation_id=annotation_id,
            decision=decision,
            reviewer=reviewer,
            reviewed_at=datetime.now(UTC),
        )
        self.session.add(review)
        unit = self.session.get(AnnotationUnit, link.unit_id)
        if unit is not None:
            unit.status = "reviewed" if decision == "confirmed" else decision
        self.session.flush()
        total_units = (
            self.session.scalar(
                select(func.count())
                .select_from(AnnotationUnit)
                .where(AnnotationUnit.annotation_set_id == annotation_set.id)
            )
            or 0
        )
        reviewed_units = (
            self.session.scalar(
                select(func.count())
                .select_from(AnnotationUnit)
                .where(
                    AnnotationUnit.annotation_set_id == annotation_set.id,
                    AnnotationUnit.status == "reviewed",
                )
            )
            or 0
        )
        run = self.session.get(AnalysisRun, annotation_set.analysis_run_id)
        if run is not None:
            run.progress = reviewed_units / total_units if total_units else 0
        self.session.commit()
        return review

    def freeze(self, annotation_set_id: str) -> AnnotationSet:
        annotation_set = self._set(annotation_set_id)
        if annotation_set.status == "frozen":
            return annotation_set
        units = list(
            self.session.scalars(
                select(AnnotationUnit)
                .where(AnnotationUnit.annotation_set_id == annotation_set.id)
                .order_by(AnnotationUnit.ordinal)
            )
        )
        manifest: list[dict[str, Any]] = []
        missing: list[int] = []
        missing_double: list[int] = []
        for unit in units:
            confirmed = self._confirmed_annotations(annotation_set.id, unit.id)
            if not confirmed:
                missing.append(unit.ordinal)
                continue
            if unit.strata.get("double_annotation_required"):
                annotators = {
                    str(annotation.provenance.get("model", "unknown")) for annotation in confirmed
                }
                if len(annotators) < 2:
                    missing_double.append(unit.ordinal)
                    continue
            revision = self.session.get(MessageRevision, unit.revision_id)
            if revision is None:
                raise RuntimeError("annotation unit revision is missing")
            manifest.append(
                {
                    "unit_id": unit.id,
                    "ordinal": unit.ordinal,
                    "object_id": unit.object_id,
                    "revision_id": unit.revision_id,
                    "text_hash": revision.text_hash,
                    "split": unit.split,
                    "annotations": [
                        {
                            "id": annotation.id,
                            "kind": annotation.kind,
                            "value": annotation.value,
                            "evidence": annotation.evidence,
                        }
                        for annotation in confirmed
                    ],
                }
            )
        if missing:
            preview = ", ".join(str(value) for value in missing[:10])
            raise ValueError(f"all units require a confirmed annotation; missing: {preview}")
        if missing_double:
            preview = ", ".join(str(value) for value in missing_double[:10])
            raise ValueError(
                f"double-annotation units require two confirmed annotators; missing: {preview}"
            )
        encoded = json.dumps(
            manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        annotation_set.manifest_hash = hashlib.sha256(encoded).hexdigest()
        annotation_set.status = "frozen"
        annotation_set.frozen_at = datetime.now(UTC)
        run = self.session.get(AnalysisRun, annotation_set.analysis_run_id)
        if run is not None:
            run.status = RunStatus.COMPLETED
            run.progress = 1
            run.completed_at = annotation_set.frozen_at
        self.session.commit()
        return annotation_set

    def export(self, annotation_set_id: str) -> dict[str, Any]:
        annotation_set = self._set(annotation_set_id)
        if annotation_set.status != "frozen":
            raise ValueError("only frozen annotation sets can be exported")
        units: list[dict[str, Any]] = []
        cursor = -1
        while True:
            page = self.list_units(annotation_set.id, after_ordinal=cursor, limit=200)
            if not page:
                break
            units.extend(page)
            cursor = page[-1]["ordinal"]
        return {
            "schema": "hetaira.annotation-set.v1",
            "annotation_set_id": annotation_set.id,
            "name": annotation_set.name,
            "language": annotation_set.language,
            "snapshot_id": annotation_set.snapshot_id,
            "codebook": (f"{annotation_set.codebook_key}@{annotation_set.codebook_version}"),
            "codebook_artifact_hash": annotation_set.codebook_artifact_hash,
            "manifest_hash": annotation_set.manifest_hash,
            "sampling_spec": annotation_set.sampling_spec,
            "units": units,
        }

    def _unit_payload(
        self, unit: AnnotationUnit, message: Message, revision: MessageRevision
    ) -> dict[str, Any]:
        links = list(
            self.session.scalars(
                select(AnnotationSetAnnotation).where(AnnotationSetAnnotation.unit_id == unit.id)
            )
        )
        annotations: list[dict[str, Any]] = []
        for link in links:
            annotation = self.session.get(Annotation, link.annotation_id)
            if annotation is None:
                continue
            latest_review = self.session.scalar(
                select(AnnotationReview)
                .where(AnnotationReview.annotation_id == annotation.id)
                .order_by(AnnotationReview.reviewed_at.desc(), AnnotationReview.id.desc())
            )
            annotations.append(
                {
                    "id": annotation.id,
                    "kind": annotation.kind,
                    "value": annotation.value,
                    "evidence": annotation.evidence,
                    "role": link.role,
                    "superseded_by": annotation.superseded_by,
                    "review": (
                        {
                            "decision": latest_review.decision,
                            "reviewer": latest_review.reviewer,
                            "reviewed_at": latest_review.reviewed_at.isoformat(),
                        }
                        if latest_review
                        else None
                    ),
                }
            )
        return {
            "id": unit.id,
            "ordinal": unit.ordinal,
            "object_type": unit.object_type,
            "object_id": unit.object_id,
            "revision_id": unit.revision_id,
            "group_id": unit.group_id,
            "split": unit.split,
            "strata": unit.strata,
            "status": unit.status,
            "sender_id": message.sender_id,
            "sent_at": message.sent_at.isoformat(),
            "text": revision.text,
            "text_hash": revision.text_hash,
            "annotations": annotations,
        }

    def _confirmed_annotations(self, annotation_set_id: str, unit_id: str) -> list[Annotation]:
        links = self.session.scalars(
            select(AnnotationSetAnnotation).where(
                AnnotationSetAnnotation.annotation_set_id == annotation_set_id,
                AnnotationSetAnnotation.unit_id == unit_id,
            )
        )
        confirmed: list[Annotation] = []
        for link in links:
            annotation = self.session.get(Annotation, link.annotation_id)
            if annotation is None or annotation.superseded_by:
                continue
            latest = self.session.scalar(
                select(AnnotationReview)
                .where(AnnotationReview.annotation_id == annotation.id)
                .order_by(AnnotationReview.reviewed_at.desc(), AnnotationReview.id.desc())
            )
            if latest and latest.decision == "confirmed":
                confirmed.append(annotation)
        return confirmed

    def _annotation_belongs_to_unit(self, annotation_id: str, unit_id: str) -> bool:
        return (
            self.session.scalar(
                select(func.count())
                .select_from(AnnotationSetAnnotation)
                .where(
                    AnnotationSetAnnotation.annotation_id == annotation_id,
                    AnnotationSetAnnotation.unit_id == unit_id,
                )
            )
            or 0
        ) > 0

    def _set(self, annotation_set_id: str) -> AnnotationSet:
        annotation_set = self.session.get(AnnotationSet, annotation_set_id)
        if annotation_set is None:
            raise LookupError("annotation set not found")
        return annotation_set

    @staticmethod
    def _evidence(revision: MessageRevision, spans: list[dict[str, int]]) -> list[dict[str, Any]]:
        if not spans:
            raise ValueError("at least one evidence span is required")
        output: list[dict[str, Any]] = []
        for span in spans:
            start = span["start_codepoint"]
            end = span["end_codepoint"]
            if start < 0 or end <= start or end > len(revision.text):
                raise ValueError("evidence span is outside the source revision")
            exact = revision.text[start:end]
            output.append(
                {
                    "object_type": "revision",
                    "object_id": revision.id,
                    "revision_id": revision.id,
                    "start_codepoint": start,
                    "end_codepoint": end,
                    "exact_text_hash": text_hash(exact),
                }
            )
        return output

    def _rebalance_splits(self, annotation_set: AnnotationSet) -> None:
        units = list(
            self.session.scalars(
                select(AnnotationUnit).where(AnnotationUnit.annotation_set_id == annotation_set.id)
            )
        )
        grouped: dict[str, list[AnnotationUnit]] = defaultdict(list)
        for unit in units:
            grouped[unit.group_id].append(unit)
        total = len(units)
        targets = {
            "train": round(total * 0.6),
            "development": round(total * 0.2),
            "test": total - round(total * 0.6) - round(total * 0.2),
        }
        assigned = {split: 0 for split in targets}
        seed = str(annotation_set.sampling_spec.get("seed", "gold-ru-v0"))
        groups = sorted(
            grouped.items(),
            key=lambda item: (
                -len(item[1]),
                hashlib.sha256(f"{seed}:{item[0]}".encode()).hexdigest(),
            ),
        )
        for _group_id, members in groups:
            size = len(members)
            destination = min(
                targets,
                key=lambda split: (
                    (assigned[split] + size - targets[split]) ** 2
                    - (assigned[split] - targets[split]) ** 2,
                    split,
                ),
            )
            for unit in members:
                unit.split = destination
            assigned[destination] += size
        annotation_set.sampling_spec = {
            **annotation_set.sampling_spec,
            "strategy": "deterministic-stratified-group-balanced-v2",
            "actual_split_counts": assigned,
        }

    def _assign_double_annotation(self, annotation_set: AnnotationSet) -> None:
        units = list(
            self.session.scalars(
                select(AnnotationUnit).where(AnnotationUnit.annotation_set_id == annotation_set.id)
            )
        )
        fraction = float(annotation_set.sampling_spec.get("double_annotation_fraction", 0))
        required = round(len(units) * fraction)
        seed = str(annotation_set.sampling_spec.get("seed", "gold-ru-v0"))
        ranked = sorted(
            units,
            key=lambda unit: hashlib.sha256(
                f"{seed}:double-annotation:{unit.object_id}".encode()
            ).hexdigest(),
        )
        selected = {unit.id for unit in ranked[:required]}
        for unit in units:
            unit.strata = {
                **unit.strata,
                "double_annotation_required": unit.id in selected,
            }
        annotation_set.sampling_spec = {
            **annotation_set.sampling_spec,
            "double_annotation_required": required,
        }

    @staticmethod
    def _is_difficult(message: Message, revision: MessageRevision) -> bool:
        return bool(
            message.reply_to_external_id
            or "?" in revision.text
            or len(revision.text) > 180
            or revision.text.count(".") > 1
        )

    @classmethod
    def _strata(cls, message: Message, revision: MessageRevision) -> dict[str, Any]:
        length = len(revision.text)
        return {
            "length_bucket": "short" if length < 60 else "medium" if length < 180 else "long",
            "has_explicit_reply": bool(message.reply_to_external_id),
            "contains_question": "?" in revision.text,
            "difficult": cls._is_difficult(message, revision),
        }
