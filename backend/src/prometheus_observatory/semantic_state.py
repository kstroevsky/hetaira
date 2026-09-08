from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

import numpy as np
from sklearn.decomposition import NMF, LatentDirichletAllocation
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.metrics import adjusted_rand_score, pairwise_distances
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AnalysisRun,
    AnalysisTask,
    AnalyticalArtifact,
    Corpus,
    CorpusSnapshot,
    DependencyFingerprint,
    DerivationEdge,
    Message,
    MessageFeature,
    MessageRevision,
    SnapshotMessageRevision,
    new_id,
)

ANALYSIS_VERSION = "semantic-state-dynamics@0.1.0"


class SemanticStateService:
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
            run_type="semantic-state-dynamics",
            status="running",
            progress=0,
            started_at=datetime.now(UTC),
            configuration={"analysis_version": ANALYSIS_VERSION, "fingerprint": fingerprint},
        )
        task = AnalysisTask(
            id=new_id(),
            run_id=run.id,
            task_key="semantic_state_models",
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
                .where(
                    SnapshotMessageRevision.snapshot_id == snapshot.id, MessageRevision.text != ""
                )
                .order_by(Message.resolved_timestamp, Message.id)
            )
        )
        documents = [revision.text for _message, revision in rows]
        months = [message.resolved_timestamp.strftime("%Y-%m") for message, _revision in rows]
        topic = self._topic_challengers(documents, months)
        task.progress = 0.35
        task.checkpoint = {"stage": "topic_challengers", "documents": len(documents)}
        self.session.flush()
        semantic_change = self._semantic_change(snapshot.id, rows, documents)
        task.progress = 0.6
        temporal = self._temporal_observations(rows)
        change_points = {
            "message_activity": self._change_points(
                [item["message_count"] for item in temporal],
                [item["month"] for item in temporal],
            ),
            "topic_prevalence": {
                method: [
                    {
                        "topic_id": item["topic_id"],
                        "candidates": self._change_points(
                            [point["share"] for point in item["trajectory"]],
                            [point["month"] for point in item["trajectory"]],
                        ),
                    }
                    for item in model.get("topics", [])
                ]
                for method, model in topic["models"].items()
                if model.get("status") == "available"
            },
        }
        task.progress = 0.8
        state_model = self._state_model(temporal)
        payload = {
            "schema": "hetaira.semantic-state-dynamics.v1",
            "analysis_version": ANALYSIS_VERSION,
            "corpus_id": corpus.id,
            "snapshot_id": snapshot.id,
            "semantic_change": semantic_change,
            "topic_challengers": topic,
            "change_points": change_points,
            "conversation_states": state_model,
            "epistemic_status": "descriptive_provisional",
            "guardrail": (
                "Themes, change points, semantic shifts, and latent states are competing "
                "analytical representations that require human interpretation and validation."
            ),
            "generated_at": datetime.now(UTC).isoformat(),
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        artifact = AnalyticalArtifact(
            id=new_id(),
            corpus_id=corpus.id,
            snapshot_id=snapshot.id,
            run_id=run.id,
            artifact_type="semantic-state-dynamics",
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
                relation="USES_CONTEXT_DOCUMENT",
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
                AnalyticalArtifact.artifact_type == "semantic-state-dynamics",
            )
            .order_by(AnalyticalArtifact.created_at.desc())
        )

    @staticmethod
    def _topic_challengers(documents: list[str], months: list[str]) -> dict[str, Any]:
        if len(documents) < 6:
            unavailable = {"status": "unavailable", "reason": "fewer_than_6_documents"}
            return {"models": {"nmf": unavailable, "lda": unavailable}, "agreement": None}
        count = CountVectorizer(token_pattern=r"(?u)\b[а-яёa-z][а-яёa-z]+\b", min_df=2)
        try:
            count_matrix = count.fit_transform(documents)
        except ValueError:
            unavailable = {"status": "unavailable", "reason": "insufficient_vocabulary"}
            return {"models": {"nmf": unavailable, "lda": unavailable}, "agreement": None}
        if count_matrix.shape[1] < 2:
            unavailable = {"status": "unavailable", "reason": "insufficient_feature_variance"}
            return {"models": {"nmf": unavailable, "lda": unavailable}, "agreement": None}
        k = min(5, max(2, round(math.sqrt(len(documents) / 2))), count_matrix.shape[1])
        tfidf = TfidfVectorizer(vocabulary=count.vocabulary_).fit_transform(documents)
        nmf = NMF(n_components=k, init="nndsvda", random_state=42, max_iter=400).fit(tfidf)
        lda = LatentDirichletAllocation(
            n_components=k, random_state=42, learning_method="batch"
        ).fit(count_matrix)
        nmf_weights = nmf.transform(tfidf)
        lda_weights = lda.transform(count_matrix)
        names = count.get_feature_names_out()
        unique_months = sorted(set(months))

        def describe(method: str, components: np.ndarray, weights: np.ndarray) -> dict[str, Any]:
            labels = weights.argmax(axis=1)
            topics = []
            for topic_id in range(k):
                top = components[topic_id].argsort()[::-1][:8]
                topics.append(
                    {
                        "topic_id": topic_id,
                        "terms": [str(names[index]) for index in top],
                        "trajectory": [
                            {
                                "month": month,
                                "documents": int(
                                    sum(
                                        (labels[index] == topic_id and months[index] == month)
                                        for index in range(len(labels))
                                    )
                                ),
                                "share": float(
                                    sum(
                                        (labels[index] == topic_id and months[index] == month)
                                        for index in range(len(labels))
                                    )
                                    / max(1, months.count(month))
                                ),
                            }
                            for month in unique_months
                        ],
                    }
                )
            return {
                "status": "available",
                "method": method,
                "topic_count": k,
                "topics": topics,
                "assignments": labels.tolist(),
            }

        nmf_payload = describe("tfidf_nmf", nmf.components_, nmf_weights)
        lda_payload = describe("count_lda", lda.components_, lda_weights)
        agreement = float(
            adjusted_rand_score(nmf_payload["assignments"], lda_payload["assignments"])
        )
        return {
            "models": {"nmf": nmf_payload, "lda": lda_payload},
            "agreement": {
                "adjusted_rand_index": agreement,
                "interpretation": "method_disagreement_is_uncertainty",
            },
        }

    def _semantic_change(
        self, snapshot_id: str, rows: list[Any], documents: list[str]
    ) -> dict[str, Any]:
        if len(rows) < 6:
            return {"status": "unavailable", "reason": "fewer_than_6_contexts", "terms": []}
        features = {
            item.message_id: item.values
            for item in self.session.scalars(
                select(MessageFeature).where(
                    MessageFeature.snapshot_id == snapshot_id,
                    MessageFeature.feature_type == "sentence_embedding",
                )
            )
        }
        representation = "pinned_contextual_embeddings"
        if sum(message.id in features for message, _revision in rows) < len(rows) * 0.8:
            matrix = (
                TfidfVectorizer(token_pattern=r"(?u)\b[а-яёa-z][а-яёa-z]+\b", min_df=2)
                .fit_transform(documents)
                .toarray()
            )
            vectors = {
                message.id: matrix[index].tolist()
                for index, (message, _revision) in enumerate(rows)
            }
            representation = "tfidf_context_fallback"
        else:
            vectors = features
        midpoint = len(rows) // 2
        early_ids = {row[0].id for row in rows[:midpoint]}
        term_docs: dict[str, list[str]] = defaultdict(list)
        for (message, _revision), text in zip(rows, documents, strict=True):
            for term in set(re.findall(r"(?iu)\b[а-яёa-z][а-яёa-z]+\b", text.casefold())):
                term_docs[term].append(message.id)
        output = []
        for term, ids in term_docs.items():
            early = [vectors[item] for item in ids if item in early_ids and item in vectors]
            late = [vectors[item] for item in ids if item not in early_ids and item in vectors]
            if len(early) < 2 or len(late) < 2:
                continue
            left, right = np.asarray(early), np.asarray(late)
            output.append(
                {
                    "term": term,
                    "early_occurrences": len(early),
                    "late_occurrences": len(late),
                    "average_pairwise_cosine_distance": float(
                        pairwise_distances(left, right, metric="cosine").mean()
                    ),
                    "mean_embedding_distance": float(
                        np.linalg.norm(left.mean(axis=0) - right.mean(axis=0))
                    ),
                }
            )
        output.sort(key=lambda item: item["average_pairwise_cosine_distance"], reverse=True)
        return {
            "status": "available",
            "representation": representation,
            "split": {"early_documents": midpoint, "late_documents": len(rows) - midpoint},
            "terms": output[:50],
        }

    @staticmethod
    def _temporal_observations(rows: list[Any]) -> list[dict[str, Any]]:
        grouped: dict[str, list[Any]] = defaultdict(list)
        for message, revision in rows:
            grouped[message.resolved_timestamp.strftime("%Y-%m")].append((message, revision))
        output = []
        for month, items in sorted(grouped.items()):
            senders = Counter(
                message.sender_id for message, _revision in items if message.sender_id
            )
            total = sum(senders.values())
            shares = [count / total for count in senders.values()] if total else []
            output.append(
                {
                    "month": month,
                    "message_count": len(items),
                    "question_rate": sum("?" in revision.text for _message, revision in items)
                    / len(items),
                    "reply_rate": sum(
                        message.reply_to_external_id is not None for message, _revision in items
                    )
                    / len(items),
                    "participant_entropy": -sum(
                        share * math.log2(share) for share in shares if share
                    ),
                    "mean_length": sum(len(revision.text) for _message, revision in items)
                    / len(items),
                }
            )
        return output

    @staticmethod
    def _change_points(values: list[float], labels: list[str]) -> list[dict[str, Any]]:
        if len(values) < 6:
            return []
        array = np.asarray(values, dtype=float)
        total_sse = float(((array - array.mean()) ** 2).sum())
        scores = []
        for split in range(2, len(array) - 1):
            within = float(
                ((array[:split] - array[:split].mean()) ** 2).sum()
                + ((array[split:] - array[split:].mean()) ** 2).sum()
            )
            scores.append((total_sse - within, split))
        binary_score, binary_split = max(scores)
        centered = array - array.mean()
        cusum = np.cumsum(centered)
        cusum_split = int(np.argmax(np.abs(cusum[:-1]))) + 1
        return [
            {
                "method": "binary_segmentation_sse",
                "month": labels[binary_split],
                "score": binary_score,
            },
            {
                "method": "cusum_max_deviation",
                "month": labels[cusum_split],
                "score": float(abs(cusum[cusum_split - 1])),
            },
        ]

    @staticmethod
    def _state_model(observations: list[dict[str, Any]]) -> dict[str, Any]:
        if len(observations) < 6:
            return {"status": "unavailable", "reason": "fewer_than_6_time_points"}
        keys = [
            "message_count",
            "question_rate",
            "reply_rate",
            "participant_entropy",
            "mean_length",
        ]
        matrix = np.asarray([[item[key] for key in keys] for item in observations], dtype=float)
        scale = matrix.std(axis=0)
        scale[scale == 0] = 1
        values = (matrix - matrix.mean(axis=0)) / scale
        labels = (values[:, 0] > np.median(values[:, 0])).astype(int)
        for _iteration in range(8):
            means = np.asarray(
                [
                    values[labels == state].mean(axis=0)
                    if np.any(labels == state)
                    else values.mean(axis=0)
                    for state in range(2)
                ]
            )
            variances = np.asarray(
                [
                    values[labels == state].var(axis=0) + 0.1
                    if np.any(labels == state)
                    else np.ones(values.shape[1])
                    for state in range(2)
                ]
            )
            transitions = np.ones((2, 2))
            for left, right in zip(labels[:-1], labels[1:], strict=True):
                transitions[left, right] += 1
            transitions /= transitions.sum(axis=1, keepdims=True)
            log_emit = np.asarray(
                [
                    [
                        -0.5
                        * float(
                            (
                                np.log(2 * np.pi * variances[state])
                                + ((row - means[state]) ** 2) / variances[state]
                            ).sum()
                        )
                        for state in range(2)
                    ]
                    for row in values
                ]
            )
            dp = np.zeros_like(log_emit)
            back = np.zeros_like(log_emit, dtype=int)
            dp[0] = math.log(0.5) + log_emit[0]
            for index in range(1, len(values)):
                for state in range(2):
                    candidates = dp[index - 1] + np.log(transitions[:, state])
                    back[index, state] = int(np.argmax(candidates))
                    dp[index, state] = candidates[back[index, state]] + log_emit[index, state]
            updated = np.zeros(len(values), dtype=int)
            updated[-1] = int(np.argmax(dp[-1]))
            for index in range(len(values) - 2, -1, -1):
                updated[index] = back[index + 1, updated[index + 1]]
            if np.array_equal(updated, labels):
                break
            labels = updated
        return {
            "status": "available",
            "method": "two_state_diagonal_gaussian_hmm_hard_em",
            "features": keys,
            "states_are_unlabeled": True,
            "sequence": [
                {"month": item["month"], "state": f"state_{int(state)}"}
                for item, state in zip(observations, labels, strict=True)
            ],
            "transition_matrix": transitions.tolist(),
            "state_means_standardized": means.tolist(),
        }
