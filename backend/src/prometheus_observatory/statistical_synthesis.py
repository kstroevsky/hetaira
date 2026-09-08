from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

import numpy as np
from scipy.optimize import minimize
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from .models import (
    AnalysisRun,
    AnalysisTask,
    AnalyticalArtifact,
    Corpus,
    CorpusSnapshot,
    DependencyFingerprint,
    DerivationEdge,
    Message,
    MessageRevision,
    ResponseRelation,
    SnapshotMessageRevision,
    new_id,
)

ANALYSIS_VERSION = "statistical-synthesis@0.1.0"
T = TypeVar("T")


class NullModelEngine:
    """Deterministic constrained randomization with explicit statistic and denominator."""

    def __init__(self, *, permutations: int = 200, seed: int = 42) -> None:
        self.permutations = permutations
        self.seed = seed

    def test(
        self,
        observed_items: list[T],
        statistic: Callable[[list[T]], float],
        permute: Callable[[list[T], random.Random], list[T]],
    ) -> dict[str, Any]:
        observed = float(statistic(observed_items))
        rng = random.Random(self.seed)
        null = [float(statistic(permute(observed_items, rng))) for _ in range(self.permutations)]
        mean = sum(null) / len(null) if null else 0.0
        sd = float(np.std(null, ddof=1)) if len(null) > 1 else 0.0
        extreme = sum(value >= observed for value in null)
        return {
            "observed": observed,
            "null_mean": mean,
            "null_sd": sd,
            "z_score": (observed - mean) / sd if sd else None,
            "one_sided_p": (extreme + 1) / (len(null) + 1),
            "permutations": self.permutations,
            "random_seed": self.seed,
        }


class StatisticalSynthesisService:
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
            run_type="statistical-synthesis",
            status="running",
            progress=0,
            started_at=datetime.now(UTC),
            configuration={
                "analysis_version": ANALYSIS_VERSION,
                "fingerprint": fingerprint,
                "permutations": 200,
                "random_seed": 42,
            },
        )
        task = AnalysisTask(
            id=new_id(),
            run_id=run.id,
            task_key="null_and_hierarchical_models",
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
        messages = self._messages(snapshot.id)
        events = self._events(snapshot.id, messages)
        null_models = self._dyad_nulls(events)
        task.progress = 0.5
        task.checkpoint = {"stage": "null_models", "reply_events": len(events)}
        hierarchical = self._hierarchical_reply_model(messages, events)
        payload = {
            "schema": "hetaira.statistical-synthesis.v1",
            "analysis_version": ANALYSIS_VERSION,
            "corpus_id": corpus_id,
            "snapshot_id": snapshot.id,
            "null_models": null_models,
            "hierarchical_reply_model": hierarchical,
            "epistemic_status": "associational_provisional",
            "guardrail": (
                "Permutation departures and hierarchical coefficients are conditional "
                "associations. "
                "They are not influence, persuasion, power, or causal effects."
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
            artifact_type="statistical-synthesis",
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
                source_id=message["revision_id"],
                target_type="analytical_artifact",
                target_id=artifact.id,
                relation="USES_STATISTICAL_UNIT",
                run_id=run.id,
            )
            for message in messages.values()
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
                AnalyticalArtifact.artifact_type == "statistical-synthesis",
            )
            .order_by(AnalyticalArtifact.created_at.desc())
        )

    def _messages(self, snapshot_id: str) -> dict[str, dict[str, Any]]:
        return {
            message.id: {
                "id": message.id,
                "conversation_id": message.conversation_id,
                "sender_id": message.sender_id,
                "sent_at": message.resolved_timestamp,
                "text": revision.text,
                "revision_id": revision.id,
            }
            for message, revision in self.session.execute(
                select(Message, MessageRevision)
                .join(SnapshotMessageRevision, SnapshotMessageRevision.message_id == Message.id)
                .join(MessageRevision, MessageRevision.id == SnapshotMessageRevision.revision_id)
                .where(SnapshotMessageRevision.snapshot_id == snapshot_id)
                .order_by(Message.resolved_timestamp, Message.id)
            )
        }

    def _events(
        self, snapshot_id: str, messages: dict[str, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        left = aliased(SnapshotMessageRevision)
        right = aliased(SnapshotMessageRevision)
        return [
            {
                "relation_id": relation.id,
                "source": messages[relation.source_message_id],
                "target": messages[relation.target_message_id],
            }
            for relation in self.session.scalars(
                select(ResponseRelation)
                .join(left, left.message_id == ResponseRelation.source_message_id)
                .join(right, right.message_id == ResponseRelation.target_message_id)
                .where(
                    left.snapshot_id == snapshot_id,
                    right.snapshot_id == snapshot_id,
                    ResponseRelation.explicit.is_(True),
                    ResponseRelation.relation_type == "REPLIES_TO",
                )
            )
            if relation.source_message_id in messages
            and relation.target_message_id in messages
            and messages[relation.source_message_id]["sender_id"]
            and messages[relation.target_message_id]["sender_id"]
        ]

    @staticmethod
    def _dyad_nulls(events: list[dict[str, Any]]) -> dict[str, Any]:
        if not events:
            return {"status": "unavailable", "reason": "no_resolved_explicit_reply_events"}
        tuples = [
            (
                event["source"]["conversation_id"],
                event["source"]["sender_id"],
                event["target"]["sender_id"],
            )
            for event in events
        ]
        observed = Counter((source, target) for _conversation, source, target in tuples)
        engine = NullModelEngine(permutations=200, seed=42)

        def permute(
            items: list[tuple[str, str, str]], rng: random.Random
        ) -> list[tuple[str, str, str]]:
            grouped: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
            for item in items:
                grouped[item[0]].append(item)
            output = []
            for conversation, group in grouped.items():
                targets = [item[2] for item in group]
                rng.shuffle(targets)
                output.extend(
                    (conversation, item[1], targets[index]) for index, item in enumerate(group)
                )
            return output

        tests = []
        for (source, target), count in observed.most_common(50):
            result = engine.test(
                tuples,
                lambda items, pair=(source, target): sum(
                    item[1] == pair[0] and item[2] == pair[1] for item in items
                ),
                permute,
            )
            tests.append(
                {
                    "source_id": source,
                    "target_id": target,
                    "event_count": count,
                    **result,
                }
            )
        return {
            "status": "available",
            "null": "shuffle_receivers_within_conversation",
            "preserves": [
                "sender_sequence",
                "receiver_event_counts",
                "conversation",
                "event_count",
            ],
            "unit": "explicit_reply_event",
            "tests": tests,
        }

    @staticmethod
    def _hierarchical_reply_model(
        messages: dict[str, dict[str, Any]], events: list[dict[str, Any]]
    ) -> dict[str, Any]:
        received = {event["target"]["id"] for event in events}
        rows = [
            message for message in messages.values() if message["sender_id"] and message["text"]
        ]
        positives = sum(row["id"] in received for row in rows)
        participants = sorted({row["sender_id"] for row in rows})
        conversations = sorted({row["conversation_id"] for row in rows})
        if len(rows) < 50 or positives < 5 or len(rows) - positives < 5 or len(participants) < 3:
            return {
                "status": "unavailable",
                "reason": "requires_50_messages_5_events_5_nonevents_3_participants",
                "sample_size": len(rows),
                "events": positives,
                "participants": len(participants),
                "conversations": len(conversations),
            }
        participant_index = {value: index for index, value in enumerate(participants)}
        conversation_index = {value: index for index, value in enumerate(conversations)}
        fixed = np.asarray(
            [
                [
                    1,
                    math.log1p(len(row["text"])),
                    float("?" in row["text"]),
                    math.sin(2 * math.pi * row["sent_at"].hour / 24),
                    math.cos(2 * math.pi * row["sent_at"].hour / 24),
                ]
                for row in rows
            ],
            dtype=float,
        )
        fixed[:, 1] = (fixed[:, 1] - fixed[:, 1].mean()) / max(fixed[:, 1].std(), 1)
        y = np.asarray([row["id"] in received for row in rows], dtype=float)
        p_indices = np.asarray([participant_index[row["sender_id"]] for row in rows])
        c_indices = np.asarray([conversation_index[row["conversation_id"]] for row in rows])
        fixed_count = fixed.shape[1]
        participant_start = fixed_count
        conversation_start = participant_start + len(participants)

        def objective(parameters: np.ndarray) -> float:
            linear = (
                fixed @ parameters[:fixed_count]
                + parameters[participant_start:conversation_start][p_indices]
                + parameters[conversation_start:][c_indices]
            )
            likelihood = np.logaddexp(0, linear).sum() - float(y @ linear)
            prior = 0.5 * float((parameters[:fixed_count] / 5) @ (parameters[:fixed_count] / 5))
            prior += 0.5 * float(parameters[participant_start:] @ parameters[participant_start:])
            return float(likelihood + prior)

        parameter_count = fixed_count + len(participants) + len(conversations)
        fit = minimize(objective, np.zeros(parameter_count), method="L-BFGS-B")
        coefficients = fit.x[:fixed_count]
        names = ["intercept", "log_length_z", "question", "hour_sin", "hour_cos"]
        return {
            "status": "available" if fit.success else "nonconverged",
            "method": "hierarchical_logistic_map_gaussian_group_priors",
            "outcome": "message_receives_first_or_later_explicit_reply",
            "unit": "message",
            "sample_size": len(rows),
            "events": positives,
            "fixed_effects": {
                name: {"log_odds": float(value), "odds_ratio": math.exp(float(value))}
                for name, value in zip(names, coefficients, strict=True)
            },
            "participant_random_intercepts": {
                participant: float(value)
                for participant, value in zip(
                    participants,
                    fit.x[participant_start:conversation_start],
                    strict=True,
                )
            },
            "conversation_random_intercepts": {
                conversation: float(value)
                for conversation, value in zip(
                    conversations, fit.x[conversation_start:], strict=True
                )
            },
            "controls": ["message_length", "question", "hour", "participant", "conversation"],
            "uncertainty": {
                "method": "MAP_point_estimates",
                "intervals": "unavailable_without_full_hessian_or_posterior_sampling",
            },
            "causal_status": "associational",
        }
