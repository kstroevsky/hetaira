from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AnalysisRun,
    AnalysisTask,
    AnalyticalArtifact,
    Annotation,
    Corpus,
    CorpusSnapshot,
    DependencyFingerprint,
    DerivationEdge,
    Message,
    MessageRevision,
    SnapshotMessageRevision,
    new_id,
)

ANALYSIS_VERSION = "experimental-information-affect@0.1.0"
TOKEN = re.compile(r"(?iu)\b[а-яёa-z][а-яёa-z-]*\b")
LEXICONS = {
    "anger": {"злой", "злость", "бесит", "ярость", "возмущён", "ненавижу"},
    "fear": {"страшно", "страх", "боюсь", "опасно", "тревожно", "риск"},
    "sadness": {"грустно", "печально", "жаль", "потеря", "разочарован"},
    "joy": {"рад", "рада", "радость", "отлично", "счастлив", "ура"},
    "frustration": {"устал", "надоело", "опять", "не получается", "тупик", "раздражает"},
    "positive": {"хорошо", "отлично", "рад", "успех", "получилось", "спасибо"},
    "negative": {"плохо", "ошибка", "провал", "проблема", "страх", "злость"},
    "dominant": {"точно", "обязательно", "решено", "делаем", "требую", "нужно"},
    "hedge": {"возможно", "кажется", "наверное", "может", "не уверен"},
    "arousal": {"срочно", "немедленно", "ужас", "ура", "бесит", "критично"},
}


class ExperimentalDynamicsService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def build(self, corpus_id: str) -> AnalyticalArtifact:
        corpus = self.session.get(Corpus, corpus_id)
        if corpus is None:
            raise LookupError("corpus not found")
        snapshot = self.session.scalar(
            select(CorpusSnapshot)
            .where(CorpusSnapshot.corpus_id == corpus_id)
            .order_by(CorpusSnapshot.created_at.desc(), CorpusSnapshot.id.desc())
        )
        if snapshot is None:
            raise LookupError("corpus snapshot not found")
        fingerprint = hashlib.sha256(
            f"{snapshot.id}:{snapshot.manifest_hash}:{ANALYSIS_VERSION}".encode()
        ).hexdigest()
        existing = self.session.scalar(
            select(AnalyticalArtifact).where(AnalyticalArtifact.fingerprint == fingerprint)
        )
        if existing:
            return existing
        run = AnalysisRun(
            id=new_id(),
            snapshot_id=snapshot.id,
            run_type="experimental-information-affect",
            status="running",
            progress=0,
            started_at=datetime.now(UTC),
            configuration={
                "analysis_version": ANALYSIS_VERSION,
                "fingerprint": fingerprint,
                "semantic_bins": "ISO_week",
                "te_permutations": 100,
                "random_seed": 42,
            },
        )
        task = AnalysisTask(
            id=new_id(),
            run_id=run.id,
            task_key="information_and_affect",
            status="running",
            progress=0,
            idempotency_key=fingerprint,
            checkpoint={},
        )
        self.session.add_all([run, task])
        self.session.flush()
        self.session.add(
            DependencyFingerprint(
                id=new_id(),
                task_id=task.id,
                dependency_type="snapshot_manifest",
                dependency_key=snapshot.id,
                fingerprint=snapshot.manifest_hash,
            )
        )
        rows = list(
            self.session.execute(
                select(Message, MessageRevision)
                .join(SnapshotMessageRevision, SnapshotMessageRevision.message_id == Message.id)
                .join(MessageRevision, MessageRevision.id == SnapshotMessageRevision.revision_id)
                .where(SnapshotMessageRevision.snapshot_id == snapshot.id)
                .order_by(Message.resolved_timestamp, Message.id)
            )
        )
        affect = self._affect(run, rows)
        task.progress = 0.45
        task.checkpoint = {"stage": "affect", "messages": len(rows)}
        information = self._information(rows)
        payload = {
            "schema": "hetaira.experimental-information-affect.v1",
            "analysis_version": ANALYSIS_VERSION,
            "corpus_id": corpus_id,
            "snapshot_id": snapshot.id,
            "semantic_information_dynamics": information,
            "linguistic_affect_dynamics": affect,
            "epistemic_status": "experimental_provisional",
            "guardrail": (
                "Transfer entropy is predictive information flow over discretized text states, "
                "not causal influence. Affect outputs describe linguistic signals, not feelings."
            ),
            "generated_at": datetime.now(UTC).isoformat(),
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        artifact = AnalyticalArtifact(
            id=new_id(),
            corpus_id=corpus_id,
            snapshot_id=snapshot.id,
            run_id=run.id,
            artifact_type="experimental-information-affect",
            analysis_version=ANALYSIS_VERSION,
            fingerprint=fingerprint,
            content_hash=hashlib.sha256(encoded).hexdigest(),
            payload=payload,
        )
        self.session.add(artifact)
        self.session.flush()
        self.session.add_all(
            DerivationEdge(
                id=new_id(),
                source_type="message_revision",
                source_id=revision.id,
                target_type="analytical_artifact",
                target_id=artifact.id,
                relation="USES_EXPERIMENTAL_STATE",
                run_id=run.id,
            )
            for _message, revision in rows
        )
        task.status = "completed"
        task.progress = 1
        task.checkpoint = {"artifact_id": artifact.id, "content_hash": artifact.content_hash}
        run.status = "completed"
        run.progress = 1
        run.completed_at = datetime.now(UTC)
        self.session.commit()
        return artifact

    def latest(self, corpus_id: str) -> AnalyticalArtifact | None:
        return self.session.scalar(
            select(AnalyticalArtifact)
            .where(
                AnalyticalArtifact.corpus_id == corpus_id,
                AnalyticalArtifact.artifact_type == "experimental-information-affect",
            )
            .order_by(AnalyticalArtifact.created_at.desc())
        )

    def _affect(self, run: AnalysisRun, rows: list[Any]) -> dict[str, Any]:
        monthly: dict[str, list[dict[str, float]]] = defaultdict(list)
        messages_with_signal = 0
        for message, revision in rows:
            tokens = TOKEN.findall(revision.text.casefold())
            denominator = max(len(tokens), 1)
            joined = " ".join(tokens)
            counts = {
                name: sum(token in terms for token in tokens)
                + sum(phrase in joined for phrase in terms if " " in phrase)
                for name, terms in LEXICONS.items()
            }
            signal = {
                "valence": (counts["positive"] - counts["negative"]) / denominator,
                "arousal": counts["arousal"] / denominator,
                "dominance": (counts["dominant"] - counts["hedge"]) / denominator,
                **{
                    name: counts[name] / denominator
                    for name in ("anger", "fear", "sadness", "joy", "frustration")
                },
            }
            messages_with_signal += int(any(value != 0 for value in signal.values()))
            monthly[message.resolved_timestamp.strftime("%Y-%m")].append(signal)
            annotation = Annotation(
                id=new_id(),
                snapshot_id=run.snapshot_id,
                run_id=run.id,
                object_type="message",
                object_id=message.id,
                kind="affect_signal",
                value={
                    **signal,
                    "observation_type": "linguistic_affect_signal",
                    "denominator_tokens": len(tokens),
                    "lexicon_version": "transparent-russian-affect-v0.1.0",
                },
                evidence=[
                    {
                        "object_type": "message",
                        "object_id": message.id,
                        "revision_id": revision.id,
                        "start_codepoint": 0,
                        "end_codepoint": len(revision.text),
                        "exact_text_hash": revision.text_hash,
                    }
                ],
                status="provisional",
                raw_confidence=None,
                calibrated_confidence=None,
                alternatives=[],
                provenance={
                    "corpus_snapshot_id": run.snapshot_id,
                    "pipeline_version": ANALYSIS_VERSION,
                    "model_provider": "deterministic",
                    "model": "transparent-russian-affect-lexicon",
                    "analysis_run_id": run.id,
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )
            self.session.add(annotation)
            self.session.flush()
            self.session.add(
                DerivationEdge(
                    id=new_id(),
                    source_type="message_revision",
                    source_id=revision.id,
                    target_type="annotation",
                    target_id=annotation.id,
                    relation="DERIVES_LINGUISTIC_AFFECT_SIGNAL",
                    run_id=run.id,
                )
            )
        dimensions = [
            "valence",
            "arousal",
            "dominance",
            "anger",
            "fear",
            "sadness",
            "joy",
            "frustration",
        ]
        trajectory = [
            {
                "month": month,
                "messages": len(signals),
                **{
                    dimension: sum(item[dimension] for item in signals) / len(signals)
                    for dimension in dimensions
                },
            }
            for month, signals in sorted(monthly.items())
        ]
        return {
            "status": "available",
            "method": "transparent_lexicon_rates",
            "unit": "message",
            "messages": len(rows),
            "messages_with_nonzero_signal": messages_with_signal,
            "dimensions": dimensions,
            "monthly_trajectory": trajectory,
            "interpretation": "linguistic_affect_signal_not_internal_emotion",
        }

    @staticmethod
    def _information(rows: list[Any]) -> dict[str, Any]:
        eligible = [
            (message, revision) for message, revision in rows if message.sender_id and revision.text
        ]
        participants = sorted({message.sender_id for message, _revision in eligible})
        if len(eligible) < 30 or len(participants) < 3:
            return {
                "status": "unavailable",
                "reason": "requires_30_messages_and_3_participants",
                "eligible_messages": len(eligible),
                "participants": len(participants),
            }
        try:
            matrix = TfidfVectorizer(
                token_pattern=r"(?u)\b[а-яёa-z][а-яёa-z]+\b", min_df=2
            ).fit_transform([revision.text for _message, revision in eligible])
        except ValueError:
            return {"status": "unavailable", "reason": "insufficient_semantic_vocabulary"}
        state_count = min(4, max(2, round(math.sqrt(len(eligible) / 10))))
        labels = KMeans(n_clusters=state_count, random_state=42, n_init=10).fit_predict(matrix)
        bins = sorted(
            {
                f"{message.resolved_timestamp.isocalendar().year}-W"
                f"{message.resolved_timestamp.isocalendar().week:02d}"
                for message, _revision in eligible
            }
        )
        values: dict[tuple[str, str], list[int]] = defaultdict(list)
        for (message, _revision), state in zip(eligible, labels, strict=True):
            iso = message.resolved_timestamp.isocalendar()
            values[(message.sender_id, f"{iso.year}-W{iso.week:02d}")].append(int(state))
        streams = {
            participant: [
                Counter(values[(participant, week)]).most_common(1)[0][0]
                if values[(participant, week)]
                else None
                for week in bins
            ]
            for participant in participants
        }
        estimates = []
        rng = random.Random(42)
        for source in participants:
            for target in participants:
                if source == target:
                    continue
                triples = [
                    (streams[target][index + 1], streams[source][index], streams[target][index])
                    for index in range(len(bins) - 1)
                    if streams[target][index + 1] is not None
                    and streams[source][index] is not None
                    and streams[target][index] is not None
                ]
                if len(triples) < 20:
                    continue
                observed = ExperimentalDynamicsService._conditional_mutual_information(triples)
                source_values = [item[1] for item in triples]
                null = []
                for _index in range(100):
                    shift = rng.randrange(1, len(source_values))
                    shifted = source_values[shift:] + source_values[:shift]
                    null.append(
                        ExperimentalDynamicsService._conditional_mutual_information(
                            [
                                (item[0], shifted[index], item[2])
                                for index, item in enumerate(triples)
                            ]
                        )
                    )
                estimates.append(
                    {
                        "source_id": source,
                        "target_id": target,
                        "transitions": len(triples),
                        "transfer_entropy_bits": observed,
                        "null_mean": sum(null) / len(null),
                        "one_sided_p": (sum(value >= observed for value in null) + 1)
                        / (len(null) + 1),
                    }
                )
        pid = ExperimentalDynamicsService._pid(participants, streams, bins)
        return {
            "status": "available" if estimates else "unavailable",
            "reason": None if estimates else "fewer_than_20_complete_transitions_per_pair",
            "representation": "weekly_dominant_tfidf_kmeans_state",
            "state_count": state_count,
            "estimator": "discrete_plugin_conditional_mutual_information",
            "bias_warning": "finite_sample_bias_and_discretization_sensitivity",
            "permutation_null": "100_seeded_circular_source_shifts",
            "transfer_entropy": estimates,
            "partial_information": pid,
            "causal_status": "predictive_association",
        }

    @staticmethod
    def _conditional_mutual_information(triples: list[tuple[int, int, int]]) -> float:
        y = [(item[0], item[2]) for item in triples]
        x = [(item[1], item[2]) for item in triples]
        z = [item[2] for item in triples]
        xyz = triples
        return max(
            0.0,
            ExperimentalDynamicsService._entropy(y)
            + ExperimentalDynamicsService._entropy(x)
            - ExperimentalDynamicsService._entropy(z)
            - ExperimentalDynamicsService._entropy(xyz),
        )

    @staticmethod
    def _entropy(values: list[Any]) -> float:
        counts = Counter(values)
        total = len(values)
        return -sum((count / total) * math.log2(count / total) for count in counts.values())

    @staticmethod
    def _mutual_information(left: list[Any], right: list[Any]) -> float:
        return max(
            0.0,
            ExperimentalDynamicsService._entropy(left)
            + ExperimentalDynamicsService._entropy(right)
            - ExperimentalDynamicsService._entropy(list(zip(left, right, strict=True))),
        )

    @staticmethod
    def _pid(
        participants: list[str], streams: dict[str, list[int | None]], bins: list[str]
    ) -> list[dict[str, Any]]:
        output = []
        for target in participants[:5]:
            sources = [item for item in participants[:5] if item != target]
            for left, right in itertools.combinations(sources, 2):
                values = [
                    (
                        streams[left][index],
                        streams[right][index],
                        streams[target][index + 1],
                    )
                    for index in range(len(bins) - 1)
                    if streams[left][index] is not None
                    and streams[right][index] is not None
                    and streams[target][index + 1] is not None
                ]
                if len(values) < 30:
                    continue
                left_values = [item[0] for item in values]
                right_values = [item[1] for item in values]
                target_values = [item[2] for item in values]
                left_information = ExperimentalDynamicsService._mutual_information(
                    left_values, target_values
                )
                right_information = ExperimentalDynamicsService._mutual_information(
                    right_values, target_values
                )
                joint_information = ExperimentalDynamicsService._mutual_information(
                    list(zip(left_values, right_values, strict=True)), target_values
                )
                redundancy = min(left_information, right_information)
                unique_left = max(0, left_information - redundancy)
                unique_right = max(0, right_information - redundancy)
                synergy = max(0, joint_information - redundancy - unique_left - unique_right)
                output.append(
                    {
                        "left_source_id": left,
                        "right_source_id": right,
                        "target_id": target,
                        "transitions": len(values),
                        "redundancy_bits": redundancy,
                        "unique_left_bits": unique_left,
                        "unique_right_bits": unique_right,
                        "synergy_bits": synergy,
                        "estimator": "imin_plugin_experimental",
                    }
                )
        return output
