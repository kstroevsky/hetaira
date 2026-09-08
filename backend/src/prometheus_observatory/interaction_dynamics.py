from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

import numpy as np
from scipy.optimize import minimize
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from .models import (
    AnalysisRun,
    Corpus,
    CorpusSnapshot,
    DerivationEdge,
    MeasurementDefinition,
    MeasurementResult,
    Message,
    MessageRevision,
    ResponseRelation,
    SnapshotMessageRevision,
    new_id,
)

ANALYSIS_VERSION = "interaction-dynamics@0.1.0"
FUNCTION_WORDS = {"и", "а", "но", "что", "как", "если", "то", "же", "ли", "бы", "не"}
PRONOUNS = {"я", "ты", "он", "она", "мы", "вы", "они", "это", "тот", "эта"}
PARTICLES = {"же", "ли", "бы", "ведь", "вот", "даже", "только", "именно"}
TOKEN = re.compile(r"\w+", re.UNICODE)
EMOJI = re.compile("[\U0001f300-\U0001faff]")


class InteractionDynamicsService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, corpus_id: str) -> AnalysisRun:
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
            f"{snapshot.id}:{snapshot.manifest_hash}:{ANALYSIS_VERSION}:explicit-replies".encode()
        ).hexdigest()
        existing = next(
            (
                run
                for run in self.session.scalars(
                    select(AnalysisRun).where(
                        AnalysisRun.snapshot_id == snapshot.id,
                        AnalysisRun.run_type == "interaction-dynamics",
                    )
                )
                if run.configuration.get("fingerprint") == fingerprint
            ),
            None,
        )
        if existing:
            return existing
        run = AnalysisRun(
            id=new_id(),
            snapshot_id=snapshot.id,
            run_type="interaction-dynamics",
            status="running",
            progress=0,
            started_at=datetime.now(UTC),
            configuration={
                "analysis_version": ANALYSIS_VERSION,
                "event_source": "source_native_REPLIES_TO_only",
                "fingerprint": fingerprint,
            },
        )
        self.session.add(run)
        self.session.flush()
        messages = self._messages(snapshot.id)
        events = self._events(snapshot.id, messages)
        outputs = {
            "directional-coordination@0.1.0": self._coordination(messages, events),
            "response-survival@0.1.0": self._survival(messages, events),
            "relational-event-choice@0.1.0": self._relational_event(messages, events),
        }
        for definition_id, payload in outputs.items():
            self._persist(run, corpus_id, definition_id, payload, events)
        run.status = "completed"
        run.progress = 1
        run.completed_at = datetime.now(UTC)
        self.session.commit()
        return run

    def result(self, corpus_id: str, run_id: str | None = None) -> dict[str, Any]:
        snapshot_ids = select(CorpusSnapshot.id).where(CorpusSnapshot.corpus_id == corpus_id)
        statement = select(AnalysisRun).where(
            AnalysisRun.snapshot_id.in_(snapshot_ids),
            AnalysisRun.run_type == "interaction-dynamics",
        )
        if run_id:
            statement = statement.where(AnalysisRun.id == run_id)
        run = self.session.scalar(statement.order_by(AnalysisRun.created_at.desc()))
        if run is None:
            raise LookupError("interaction dynamics run not found")
        results = list(
            self.session.scalars(
                select(MeasurementResult).where(MeasurementResult.run_id == run.id)
            )
        )
        return {
            "run": {
                "id": run.id,
                "snapshot_id": run.snapshot_id,
                "status": run.status,
                "progress": run.progress,
                "configuration": run.configuration,
            },
            "measurements": {result.definition_id: result.result for result in results},
            "guardrail": (
                "Outputs are descriptive or associational and do not establish "
                "influence or causality."
            ),
        }

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
        source_membership = aliased(SnapshotMessageRevision)
        target_membership = aliased(SnapshotMessageRevision)
        return [
            {
                "relation_id": relation.id,
                "source": messages[relation.source_message_id],
                "target": messages[relation.target_message_id],
            }
            for relation in self.session.scalars(
                select(ResponseRelation)
                .join(
                    source_membership,
                    source_membership.message_id == ResponseRelation.source_message_id,
                )
                .join(
                    target_membership,
                    target_membership.message_id == ResponseRelation.target_message_id,
                )
                .where(
                    source_membership.snapshot_id == snapshot_id,
                    target_membership.snapshot_id == snapshot_id,
                    ResponseRelation.explicit.is_(True),
                    ResponseRelation.relation_type == "REPLIES_TO",
                )
            )
            if relation.source_message_id in messages and relation.target_message_id in messages
        ]

    def _coordination(
        self, messages: dict[str, dict[str, Any]], events: list[dict[str, Any]]
    ) -> dict[str, Any]:
        vectors_by_sender: dict[str, list[dict[str, float]]] = defaultdict(list)
        for message in messages.values():
            if message["sender_id"] and message["text"]:
                vectors_by_sender[message["sender_id"]].append(self._style(message["text"]))
        baselines = {
            sender: self._mean_vectors(vectors) for sender, vectors in vectors_by_sender.items()
        }
        by_pair: dict[tuple[str, str], list[float]] = defaultdict(list)
        excluded = Counter()
        for event in events:
            reply, target = event["source"], event["target"]
            if not reply["sender_id"] or not target["sender_id"]:
                excluded["missing_sender"] += 1
                continue
            if reply["sender_id"] == target["sender_id"]:
                excluded["self_reply"] += 1
                continue
            target_style, reply_style = self._style(target["text"]), self._style(reply["text"])
            observed = self._similarity(target_style, reply_style)
            baseline = self._similarity(target_style, baselines[reply["sender_id"]])
            by_pair[(target["sender_id"], reply["sender_id"])].append(observed - baseline)
        estimates = []
        for (initiator, responder), values in sorted(by_pair.items()):
            mean = sum(values) / len(values)
            se = self._standard_error(values)
            estimates.append(
                {
                    "initiator_id": initiator,
                    "responder_id": responder,
                    "events": len(values),
                    "accommodation_delta": mean,
                    "lower": mean - 1.96 * se,
                    "upper": mean + 1.96 * se,
                }
            )
        return {
            "estimate": estimates,
            "sample_size": sum(map(len, by_pair.values())),
            "denominator": len(events),
            "numerator": None,
            "uncertainty": {"method": "normal_interval_over_reply_events", "level": 0.95},
            "missingness": dict(excluded),
            "controls": [
                "responder_snapshot_baseline",
                "ordered_pair",
                "immediately_replied_message",
            ],
            "null_model": None,
            "causal_status": "descriptive",
            "feature_inventory": [
                "function_words",
                "pronouns",
                "particles",
                "punctuation",
                "emoji",
                "length",
            ],
        }

    def _survival(
        self, messages: dict[str, dict[str, Any]], events: list[dict[str, Any]]
    ) -> dict[str, Any]:
        first_reply: dict[str, datetime] = {}
        for event in events:
            target_id = event["target"]["id"]
            timestamp = event["source"]["sent_at"]
            if timestamp >= event["target"]["sent_at"]:
                first_reply[target_id] = min(timestamp, first_reply.get(target_id, timestamp))
        end_by_conversation: dict[str, datetime] = {}
        for message in messages.values():
            end_by_conversation[message["conversation_id"]] = max(
                message["sent_at"],
                end_by_conversation.get(message["conversation_id"], message["sent_at"]),
            )
        observations = []
        for message in messages.values():
            if not message["sender_id"] or not message["text"]:
                continue
            end = first_reply.get(message["id"], end_by_conversation[message["conversation_id"]])
            observations.append(
                (
                    max(0, (end - message["sent_at"]).total_seconds() / 60),
                    message["id"] in first_reply,
                )
            )
        curve = self._kaplan_meier(observations)
        median = next((point["minutes"] for point in curve if point["survival"] <= 0.5), None)
        return {
            "estimate": {"median_minutes": median, "survival_curve": curve},
            "sample_size": len(observations),
            "denominator": len(observations),
            "numerator": sum(observed for _duration, observed in observations),
            "uncertainty": {"method": "kaplan_meier_greenwood", "level": 0.95},
            "missingness": {"messages_without_sender_or_text": len(messages) - len(observations)},
            "controls": ["right_censor_at_conversation_end", "first_explicit_reply_only"],
            "null_model": None,
            "causal_status": "descriptive",
        }

    def _relational_event(
        self, messages: dict[str, dict[str, Any]], events: list[dict[str, Any]]
    ) -> dict[str, Any]:
        participants: dict[str, set[str]] = defaultdict(set)
        for message in messages.values():
            if message["sender_id"]:
                participants[message["conversation_id"]].add(message["sender_id"])
        dyad = Counter()
        incoming = Counter()
        last: dict[tuple[str, str], datetime] = {}
        risk_sets = []
        for event in sorted(events, key=lambda item: item["source"]["sent_at"]):
            source, target = event["source"], event["target"]
            sender, receiver = source["sender_id"], target["sender_id"]
            choices = sorted(participants[source["conversation_id"]] - {sender}) if sender else []
            if receiver in choices and len(choices) > 1:
                matrix = []
                for candidate in choices:
                    previous = last.get((sender, candidate))
                    hours = (
                        (source["sent_at"] - previous).total_seconds() / 3600 if previous else None
                    )
                    matrix.append(
                        [
                            math.log1p(dyad[(sender, candidate)]),
                            math.log1p(dyad[(candidate, sender)]),
                            math.log1p(incoming[candidate]),
                            math.exp(-hours / 24) if hours is not None and hours >= 0 else 0,
                        ]
                    )
                risk_sets.append((np.asarray(matrix), choices.index(receiver)))
            if sender and receiver:
                dyad[(sender, receiver)] += 1
                incoming[receiver] += 1
                last[(sender, receiver)] = source["sent_at"]
        names = ["repetition", "reciprocity", "receiver_popularity", "dyad_recency_24h"]
        if len(risk_sets) < 10:
            return {
                "estimate": {},
                "sample_size": len(risk_sets),
                "denominator": len(events),
                "numerator": None,
                "uncertainty": {
                    "method": "not_estimated",
                    "reason": "fewer_than_10_informative_risk_sets",
                },
                "missingness": {"uninformative_or_unresolved_events": len(events) - len(risk_sets)},
                "controls": ["sender", "conversation_risk_set", "event_history"],
                "null_model": None,
                "causal_status": "associational",
            }

        def objective(beta: np.ndarray) -> float:
            value = 0.0
            for matrix, chosen in risk_sets:
                scores = matrix @ beta
                maximum = float(np.max(scores))
                value -= float(scores[chosen] - maximum - np.log(np.exp(scores - maximum).sum()))
            return value + 0.5 * float(beta @ beta) * 0.01

        fit = minimize(objective, np.zeros(4), method="BFGS")
        coefficients = {name: float(value) for name, value in zip(names, fit.x, strict=True)}
        return {
            "estimate": {
                "coefficients": coefficients,
                "relative_choice_odds": {
                    name: math.exp(value) for name, value in coefficients.items()
                },
                "converged": bool(fit.success),
            },
            "sample_size": len(risk_sets),
            "denominator": len(events),
            "numerator": None,
            "uncertainty": {
                "method": "regularized_conditional_choice_likelihood",
                "optimizer": "BFGS",
            },
            "missingness": {"uninformative_or_unresolved_events": len(events) - len(risk_sets)},
            "controls": ["sender", "conversation_risk_set", "event_history"],
            "null_model": None,
            "causal_status": "associational",
        }

    @staticmethod
    def _style(text: str) -> dict[str, float]:
        words = [word.casefold() for word in TOKEN.findall(text)]
        total = max(len(words), 1)
        return {
            "function_words": sum(w in FUNCTION_WORDS for w in words) / total,
            "pronouns": sum(w in PRONOUNS for w in words) / total,
            "particles": sum(w in PARTICLES for w in words) / total,
            "punctuation": sum(text.count(mark) for mark in ".,!?;:") / max(len(text), 1),
            "emoji": len(EMOJI.findall(text)) / max(len(text), 1),
            "length": min(len(words), 100) / 100,
        }

    @staticmethod
    def _mean_vectors(vectors: list[dict[str, float]]) -> dict[str, float]:
        return {key: sum(item[key] for item in vectors) / len(vectors) for key in vectors[0]}

    @staticmethod
    def _similarity(left: dict[str, float], right: dict[str, float]) -> float:
        return sum(1 - min(abs(left[key] - right[key]), 1) for key in left) / len(left)

    @staticmethod
    def _standard_error(values: list[float]) -> float:
        if len(values) < 2:
            return 0
        mean = sum(values) / len(values)
        return math.sqrt(
            sum((value - mean) ** 2 for value in values) / (len(values) - 1)
        ) / math.sqrt(len(values))

    @staticmethod
    def _kaplan_meier(observations: list[tuple[float, bool]]) -> list[dict[str, float | int]]:
        at_risk = len(observations)
        survival = 1.0
        output = []
        for time in sorted({duration for duration, _observed in observations}):
            deaths = sum(duration == time and observed for duration, observed in observations)
            censored = sum(duration == time and not observed for duration, observed in observations)
            if deaths and at_risk:
                survival *= 1 - deaths / at_risk
            output.append(
                {
                    "minutes": time,
                    "survival": survival,
                    "at_risk": at_risk,
                    "replies": deaths,
                    "censored": censored,
                }
            )
            at_risk -= deaths + censored
        return output

    def _persist(
        self,
        run: AnalysisRun,
        corpus_id: str,
        definition_id: str,
        payload: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> None:
        if self.session.get(MeasurementDefinition, definition_id) is None:
            self.session.add(
                MeasurementDefinition(
                    id=definition_id,
                    version="0.1.0",
                    title=definition_id,
                    description="Provisional interaction-dynamics measurement",
                    unit_of_analysis="reply_event",
                    manifest={"causal": False, "event_source": "explicit_replies"},
                )
            )
        result = MeasurementResult(
            id=new_id(),
            definition_id=definition_id,
            run_id=run.id,
            subject_type="corpus",
            subject_id=corpus_id,
            result=payload,
            provenance={
                "snapshot_id": run.snapshot_id,
                "run_id": run.id,
                "analysis_version": ANALYSIS_VERSION,
            },
        )
        self.session.add(result)
        self.session.flush()
        self.session.add_all(
            DerivationEdge(
                id=new_id(),
                source_type="response_relation",
                source_id=event["relation_id"],
                target_type="measurement",
                target_id=result.id,
                relation="USES_EXPLICIT_REPLY_EVENT",
                run_id=run.id,
            )
            for event in events
        )
