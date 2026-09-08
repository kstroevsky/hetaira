from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

import igraph as ig
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from .analyzer import DeterministicAnalyzer
from .models import (
    AnalysisRun,
    AnalysisTask,
    AnalyticalArtifact,
    Annotation,
    Corpus,
    CorpusSnapshot,
    DependencyFingerprint,
    DerivationEdge,
    EpisodeMessage,
    Message,
    MessageRevision,
    Participant,
    PropositionMention,
    PropositionRelation,
    ResponseRelation,
    SnapshotMessageRevision,
    Span,
    Utterance,
    new_id,
)
from .reasoning_graph import ReasoningGraphService

ANALYSIS_VERSION = "network-sequence-dynamics@0.1.0"


class NetworkSequenceService:
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
        foundation = self._latest_run(snapshot.id, "deterministic-foundation")
        if foundation is None:
            foundation = DeterministicAnalyzer(self.session).analyze(corpus_id)
        reasoning = self._latest_run(snapshot.id, "reasoning-graph")
        if reasoning is None:
            reasoning = ReasoningGraphService(self.session).create(corpus_id, include_nli=False)
        fingerprint = hashlib.sha256(
            f"{snapshot.id}:{snapshot.manifest_hash}:{foundation.id}:{reasoning.id}:{ANALYSIS_VERSION}".encode()
        ).hexdigest()
        existing = self.session.scalar(
            select(AnalyticalArtifact).where(AnalyticalArtifact.fingerprint == fingerprint)
        )
        if existing:
            return existing
        run = AnalysisRun(
            id=new_id(),
            snapshot_id=snapshot.id,
            run_type="network-sequence-dynamics",
            status="running",
            progress=0,
            started_at=datetime.now(UTC),
            configuration={
                "analysis_version": ANALYSIS_VERSION,
                "foundation_run_id": foundation.id,
                "reasoning_run_id": reasoning.id,
                "fingerprint": fingerprint,
                "random_seed": 42,
            },
        )
        task = AnalysisTask(
            id=new_id(),
            run_id=run.id,
            task_key="network_sequence_models",
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
                dependency_type="network_sequence_inputs",
                dependency_key=snapshot.id,
                fingerprint=fingerprint,
            )
        )
        messages = self._messages(snapshot.id)
        reply_events = self._reply_events(snapshot.id, messages)
        task.progress = 0.2
        layers = self._layers(
            corpus_id, snapshot.id, foundation.id, reasoning.id, messages, reply_events
        )
        task.progress = 0.45
        motifs = self._motifs(reply_events)
        task.progress = 0.65
        sequences = self._sequences(foundation.id)
        task.progress = 0.8
        hawkes = self._hawkes(messages)
        payload = {
            "schema": "hetaira.network-sequence-dynamics.v1",
            "analysis_version": ANALYSIS_VERSION,
            "corpus_id": corpus_id,
            "snapshot_id": snapshot.id,
            "hawkes": hawkes,
            "multilayer_communities": layers,
            "network_motifs": motifs,
            "dialogue_sequences": sequences,
            "epistemic_status": "descriptive_associational_provisional",
            "guardrail": (
                "Excitation, communities, motifs, and sequences are structural associations. "
                "They do not establish influence, causality, stable coalitions, "
                "or successful outcomes."
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
            artifact_type="network-sequence-dynamics",
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
                source_id=item["revision_id"],
                target_type="analytical_artifact",
                target_id=artifact.id,
                relation="USES_NETWORK_EVENT",
                run_id=run.id,
            )
            for item in messages.values()
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
                AnalyticalArtifact.artifact_type == "network-sequence-dynamics",
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

    def _reply_events(
        self, snapshot_id: str, messages: dict[str, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        left = aliased(SnapshotMessageRevision)
        right = aliased(SnapshotMessageRevision)
        return [
            {
                "id": relation.id,
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
            if relation.source_message_id in messages and relation.target_message_id in messages
        ]

    def _layers(
        self,
        corpus_id: str,
        snapshot_id: str,
        foundation_run: str,
        reasoning_run: str,
        messages: dict[str, dict[str, Any]],
        replies: list[dict[str, Any]],
    ) -> dict[str, Any]:
        names = {
            item.id: item.display_name
            for item in self.session.scalars(
                select(Participant).where(Participant.corpus_id == corpus_id)
            )
        }
        interaction = Counter(
            (event["source"]["sender_id"], event["target"]["sender_id"])
            for event in replies
            if event["source"]["sender_id"] and event["target"]["sender_id"]
        )
        proposition_senders = self._proposition_senders()
        argument = Counter()
        for relation in self.session.scalars(
            select(PropositionRelation).where(
                PropositionRelation.run_id == reasoning_run,
                PropositionRelation.relation_type.in_(["SUPPORTS", "ATTACKS"]),
            )
        ):
            source = proposition_senders.get(relation.source_proposition_id)
            target = proposition_senders.get(relation.target_proposition_id)
            if source and target:
                argument[(source, target, relation.relation_type)] += 1
        participant_texts: dict[str, list[str]] = defaultdict(list)
        for message in messages.values():
            if message["sender_id"] and message["text"]:
                participant_texts[message["sender_id"]].append(message["text"])
        semantic = Counter()
        participant_ids = sorted(participant_texts)
        if len(participant_ids) >= 2:
            try:
                vectors = TfidfVectorizer(
                    token_pattern=r"(?u)\b[а-яёa-z][а-яёa-z]+\b", min_df=2
                ).fit_transform(["\n".join(participant_texts[item]) for item in participant_ids])
                similarity = cosine_similarity(vectors)
                for left_index, right_index in itertools.combinations(
                    range(len(participant_ids)), 2
                ):
                    if similarity[left_index, right_index] >= 0.25:
                        semantic[(participant_ids[left_index], participant_ids[right_index])] = (
                            float(similarity[left_index, right_index])
                        )
            except ValueError:
                pass
        layer_edges = {
            "interaction": [
                (a, b, float(weight)) for (a, b), weight in interaction.items() if a != b
            ],
            "semantic_similarity": [(a, b, weight) for (a, b), weight in semantic.items()],
            "support": [
                (a, b, float(weight))
                for (a, b, kind), weight in argument.items()
                if kind == "SUPPORTS"
            ],
            "attack": [
                (a, b, float(weight))
                for (a, b, kind), weight in argument.items()
                if kind == "ATTACKS"
            ],
        }
        interaction_by_month: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
        for event in replies:
            source = event["source"]["sender_id"]
            target = event["target"]["sender_id"]
            if source and target and source != target:
                month = event["source"]["sent_at"].strftime("%Y-%m")
                interaction_by_month[month].append((source, target, 1.0))
        return {
            "layers": {
                layer: self._communities(edges, names) for layer, edges in layer_edges.items()
            },
            "dynamic_interaction": [
                {"month": month, **self._communities(edges, names)}
                for month, edges in sorted(interaction_by_month.items())
            ],
            "knowledge_flow": {
                "status": "unavailable",
                "reason": "validated_concept_uptake_edges_not_available",
            },
            "stance": {
                "status": "unavailable",
                "reason": "participant_target_stance_layer_not_yet_materialized",
            },
            "interpretation": "layer_disagreement_is_retained",
        }

    @staticmethod
    def _communities(edges: list[tuple[str, str, float]], names: dict[str, str]) -> dict[str, Any]:
        vertices = sorted({endpoint for edge in edges for endpoint in edge[:2]})
        if len(vertices) < 2 or not edges:
            return {"status": "unavailable", "reason": "insufficient_edges", "communities": []}
        graph = ig.Graph(directed=False)
        graph.add_vertices(vertices)
        combined = Counter(tuple(sorted((left, right))) for left, right, _weight in edges)
        weights = Counter()
        for left, right, weight in edges:
            weights[tuple(sorted((left, right)))] += weight
        graph.add_edges(list(combined))
        graph.es["weight"] = [weights[edge] for edge in combined]
        partition = graph.community_leiden(weights="weight", objective_function="modularity")
        return {
            "status": "available",
            "method": "leiden_modularity",
            "communities": [
                {
                    "community_id": index,
                    "participants": [
                        {"id": vertices[node], "name": names.get(vertices[node], "Unknown")}
                        for node in members
                    ],
                }
                for index, members in enumerate(partition)
            ],
        }

    @staticmethod
    def _motif_counts(edges: list[tuple[str, str]]) -> dict[str, int]:
        edge_set = {(left, right) for left, right in edges if left != right}
        reciprocal = sum((right, left) in edge_set for left, right in edge_set) // 2
        transitive = sum(
            (left, right) in edge_set and (right, third) in edge_set and (left, third) in edge_set
            for left, right, third in itertools.permutations(
                {node for edge in edge_set for node in edge}, 3
            )
        )
        return {"reciprocal_dyads": reciprocal, "transitive_triads": transitive}

    def _motifs(self, replies: list[dict[str, Any]]) -> dict[str, Any]:
        edges = [
            (event["source"]["sender_id"], event["target"]["sender_id"])
            for event in replies
            if event["source"]["sender_id"] and event["target"]["sender_id"]
        ]
        observed = self._motif_counts(edges)
        rng = random.Random(42)
        targets = [right for _left, right in edges]
        null = []
        for _index in range(100):
            shuffled = targets.copy()
            rng.shuffle(shuffled)
            null.append(
                self._motif_counts(
                    [(edges[index][0], shuffled[index]) for index in range(len(edges))]
                )
            )
        summary = {
            key: {
                "observed": value,
                "null_mean": sum(item[key] for item in null) / len(null) if null else 0,
                "null_sd": float(np.std([item[key] for item in null])) if null else 0,
            }
            for key, value in observed.items()
        }
        return {
            "status": "available" if edges else "unavailable",
            "method": "target_permutation_preserving_in_out_event_counts",
            "permutations": 100,
            "random_seed": 42,
            "motifs": summary,
            "event_count": len(edges),
        }

    def _sequences(self, foundation_run: str) -> dict[str, Any]:
        rows = list(
            self.session.execute(
                select(Annotation, Message, EpisodeMessage)
                .join(Span, Span.id == Annotation.object_id)
                .join(MessageRevision, MessageRevision.id == Span.revision_id)
                .join(Message, Message.id == MessageRevision.message_id)
                .outerjoin(EpisodeMessage, EpisodeMessage.message_id == Message.id)
                .where(Annotation.run_id == foundation_run, Annotation.kind == "dialogue_act")
                .order_by(
                    EpisodeMessage.episode_id,
                    EpisodeMessage.ordinal,
                    Span.start_codepoint,
                    Annotation.id,
                )
            )
        )
        episodes: dict[str, list[str]] = defaultdict(list)
        for annotation, message, episode in rows:
            episodes[episode.episode_id if episode else message.conversation_id].append(
                annotation.value["label"]
            )
        patterns = Counter()
        transitions = Counter()
        for sequence in episodes.values():
            transitions.update(zip(sequence, sequence[1:], strict=False))
            for size in range(2, min(5, len(sequence)) + 1):
                patterns.update(
                    tuple(sequence[index : index + size])
                    for index in range(len(sequence) - size + 1)
                )
        return {
            "status": "available" if rows else "unavailable",
            "unit": "structural_episode",
            "transitions": [
                {"from": left, "to": right, "count": count}
                for (left, right), count in transitions.most_common(30)
            ],
            "frequent_patterns": [
                {"sequence": list(pattern), "count": count}
                for pattern, count in patterns.most_common(30)
            ],
            "outcome_association": {
                "status": "unavailable",
                "reason": "validated_episode_outcomes_not_defined",
            },
        }

    @staticmethod
    def _hawkes(messages: dict[str, dict[str, Any]]) -> dict[str, Any]:
        events = [item for item in messages.values() if item["sender_id"] and item["text"]]
        if len(events) < 20:
            return {"status": "unavailable", "reason": "fewer_than_20_message_events"}
        active = [
            sender
            for sender, _count in Counter(item["sender_id"] for item in events).most_common(10)
        ]
        index = {sender: offset for offset, sender in enumerate(active)}
        beta_hours = 24.0
        first, last = events[0]["sent_at"], events[-1]["sent_at"]
        duration = max((last - first).total_seconds() / 3600, 1)
        counts = Counter(item["sender_id"] for item in events)
        baseline = {sender: counts[sender] / duration for sender in active}
        excitation = np.zeros((len(active), len(active)))
        active_events = [item for item in events if item["sender_id"] in index]
        for source_index, source in enumerate(active_events):
            for target in active_events[source_index + 1 :]:
                delta = (target["sent_at"] - source["sent_at"]).total_seconds() / 3600
                if delta > beta_hours * 5:
                    break
                excitation[index[target["sender_id"]], index[source["sender_id"]]] += math.exp(
                    -delta / beta_hours
                )
        for source, source_id in enumerate(active):
            excitation[:, source] /= max(counts[source_id], 1)
            excitation[:, source] = np.maximum(
                excitation[:, source]
                - np.asarray([baseline[item] * beta_hours for item in active])
                / max(counts[source_id], 1),
                0,
            )
        radius = float(max(abs(np.linalg.eigvals(excitation)))) if excitation.size else 0
        return {
            "status": "available",
            "method": "exponential_kernel_moment_baseline",
            "decay_hours": beta_hours,
            "participants": active,
            "baseline_events_per_hour": baseline,
            "excitation_matrix": excitation.tolist(),
            "spectral_radius": radius,
            "stability_warning": radius >= 1,
            "causal_status": "associational",
        }

    def _proposition_senders(self) -> dict[str, str | None]:
        return {
            proposition.id: message.sender_id
            for proposition, message in self.session.execute(
                select(PropositionMention, Message)
                .join(Utterance, Utterance.id == PropositionMention.utterance_id)
                .join(MessageRevision, MessageRevision.id == Utterance.revision_id)
                .join(Message, Message.id == MessageRevision.message_id)
            )
        }

    def _latest_run(self, snapshot_id: str, run_type: str) -> AnalysisRun | None:
        return self.session.scalar(
            select(AnalysisRun)
            .where(
                AnalysisRun.snapshot_id == snapshot_id,
                AnalysisRun.run_type == run_type,
                AnalysisRun.status == "completed",
            )
            .order_by(AnalysisRun.created_at.desc())
        )
