from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
from collections import Counter
from datetime import UTC, datetime
from statistics import median
from typing import Any

import igraph as ig
import numpy as np
import pymorphy3
from sklearn.cluster import KMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import Normalizer
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from .config import get_settings
from .models import (
    AnalysisRun,
    AnalysisTask,
    AnalyticalArtifact,
    AttachmentRef,
    Conversation,
    ConversationSession,
    Corpus,
    CorpusSnapshot,
    DependencyFingerprint,
    DerivationEdge,
    Episode,
    EpisodeMessage,
    Finding,
    MeasurementDefinition,
    MeasurementResult,
    Message,
    MessageRevision,
    Participant,
    ResponseRelation,
    SnapshotMessageRevision,
    new_id,
)
from .ontology import CausalStatus, EpistemicLevel, RunStatus

ANALYSIS_VERSION = "observatory-overview@1.4.2"
WORD_PATTERN = re.compile(r"[а-яё]{4,}", re.IGNORECASE)
RUSSIAN_STOPWORDS = {
    "более",
    "больше",
    "будет",
    "были",
    "было",
    "быть",
    "вас",
    "ведь",
    "вот",
    "вообще",
    "всего",
    "всех",
    "весь",
    "где",
    "даже",
    "другой",
    "если",
    "есть",
    "ещё",
    "зачем",
    "здесь",
    "значит",
    "или",
    "иногда",
    "когда",
    "конечно",
    "короче",
    "кстати",
    "куда",
    "либо",
    "между",
    "меня",
    "может",
    "мочь",
    "можно",
    "много",
    "надо",
    "наши",
    "него",
    "нету",
    "ничего",
    "нужно",
    "один",
    "очень",
    "опять",
    "пока",
    "потом",
    "почему",
    "просто",
    "прям",
    "реально",
    "самый",
    "себе",
    "себя",
    "сейчас",
    "сегодня",
    "сказать",
    "снова",
    "также",
    "такой",
    "такое",
    "который",
    "тебя",
    "только",
    "тоже",
    "типа",
    "тогда",
    "того",
    "тут",
    "хотя",
    "через",
    "чтобы",
    "этого",
    "этой",
    "этот",
    "этому",
    "вчера",
    "сообщение",
    "сообщений",
    "обсуждалось",
    "скорее",
    "является",
    "говорить",
    "брать",
    "взять",
    "делать",
    "думать",
    "знать",
    "какой",
    "команда",
    "написать",
    "обсуждаться",
    "понимать",
    "поддержать",
    "свой",
    "человек",
    "хороший",
    "хотеть",
}


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(round((len(ordered) - 1) * fraction), len(ordered) - 1)
    return ordered[index]


def gini(values: list[int]) -> float:
    positive = sorted(value for value in values if value >= 0)
    total = sum(positive)
    if not positive or total == 0:
        return 0
    weighted = sum((index + 1) * value for index, value in enumerate(positive))
    return (2 * weighted) / (len(positive) * total) - (len(positive) + 1) / len(positive)


def tokens(value: str) -> list[str]:
    return [
        token.casefold()
        for token in WORD_PATTERN.findall(value)
        if token.casefold() not in RUSSIAN_STOPWORDS
    ]


class ObservatoryBuilder:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()
        self._morph: pymorphy3.MorphAnalyzer | None = None
        self._lemma_cache: dict[str, str] = {}

    def build(self, corpus_id: str, *, force: bool = False) -> AnalyticalArtifact:
        corpus = self.session.get(Corpus, corpus_id)
        if corpus is None:
            raise LookupError("corpus not found")
        snapshot = self.session.scalar(
            select(CorpusSnapshot)
            .where(CorpusSnapshot.corpus_id == corpus.id)
            .order_by(CorpusSnapshot.created_at.desc(), CorpusSnapshot.id.desc())
        )
        if snapshot is None:
            raise ValueError("corpus has no snapshot")
        fingerprint = hashlib.sha256(
            f"{snapshot.manifest_hash}:{ANALYSIS_VERSION}".encode()
        ).hexdigest()
        existing = self.session.scalar(
            select(AnalyticalArtifact).where(AnalyticalArtifact.fingerprint == fingerprint)
        )
        if existing is not None and not force:
            return existing
        run = AnalysisRun(
            id=new_id(),
            snapshot_id=snapshot.id,
            run_type="observatory-overview",
            status=RunStatus.RUNNING,
            progress=0,
            configuration={
                "analysis_version": ANALYSIS_VERSION,
                "snapshot_manifest_hash": snapshot.manifest_hash,
                "language": corpus.language,
            },
            started_at=datetime.now(UTC),
        )
        task = AnalysisTask(
            id=new_id(),
            run_id=run.id,
            task_key="build_observatory_overview",
            status=RunStatus.RUNNING,
            progress=0,
            idempotency_key=f"{fingerprint}:force:{run.id}" if force else fingerprint,
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
        try:
            payloads, evidence = self._compute(corpus, snapshot, task)
            results = self._persist_measurements(corpus, snapshot, run, payloads)
            findings = self._persist_findings(corpus, snapshot, run, results, payloads, evidence)
            artifact_payload = {
                "schema": "hetaira.observatory-overview.v1",
                "analysis_version": ANALYSIS_VERSION,
                "corpus": {
                    "id": corpus.id,
                    "name": corpus.name,
                    "language": corpus.language,
                    "privacy_policy": corpus.privacy_policy,
                },
                "snapshot": {
                    "id": snapshot.id,
                    "manifest_hash": snapshot.manifest_hash,
                    "message_count": snapshot.message_count,
                    "created_at": snapshot.created_at.isoformat(),
                },
                "dimensions": payloads,
                "findings": findings,
                "measurement_result_ids": {
                    dimension: result.id for dimension, result in results.items()
                },
                "epistemic_status": "descriptive_provisional",
                "generated_at": datetime.now(UTC).isoformat(),
            }
            encoded = json.dumps(
                artifact_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            artifact = AnalyticalArtifact(
                id=new_id(),
                corpus_id=corpus.id,
                snapshot_id=snapshot.id,
                run_id=run.id,
                artifact_type="observatory-overview",
                analysis_version=ANALYSIS_VERSION,
                fingerprint=fingerprint if not force else hashlib.sha256(encoded).hexdigest(),
                content_hash=hashlib.sha256(encoded).hexdigest(),
                payload=artifact_payload,
            )
            self.session.add(artifact)
            self.session.flush()
            self.session.add_all(
                DerivationEdge(
                    id=new_id(),
                    source_type="measurement",
                    source_id=result.id,
                    target_type="analytical_artifact",
                    target_id=artifact.id,
                    relation="USES_MEASUREMENT",
                    run_id=run.id,
                )
                for result in results.values()
            )
            task.status = RunStatus.COMPLETED
            task.progress = 1
            task.checkpoint = {"artifact_id": artifact.id, "content_hash": artifact.content_hash}
            run.status = RunStatus.COMPLETED
            run.progress = 1
            run.completed_at = datetime.now(UTC)
            self.session.commit()
            return artifact
        except Exception as error:
            self.session.rollback()
            failed_run = self.session.get(AnalysisRun, run.id)
            if failed_run is not None:
                failed_run.status = RunStatus.FAILED
                failed_run.error = str(error)
                failed_run.completed_at = datetime.now(UTC)
                self.session.commit()
            raise

    def latest(self, corpus_id: str) -> AnalyticalArtifact | None:
        return self.session.scalar(
            select(AnalyticalArtifact)
            .where(
                AnalyticalArtifact.corpus_id == corpus_id,
                AnalyticalArtifact.artifact_type == "observatory-overview",
            )
            .order_by(AnalyticalArtifact.created_at.desc())
        )

    def _compute(
        self, corpus: Corpus, snapshot: CorpusSnapshot, task: AnalysisTask
    ) -> tuple[dict[str, Any], dict[str, str]]:
        first_at, last_at = self.session.execute(
            select(func.min(Message.sent_at), func.max(Message.sent_at))
            .join(SnapshotMessageRevision, SnapshotMessageRevision.message_id == Message.id)
            .where(SnapshotMessageRevision.snapshot_id == snapshot.id)
        ).one()
        monthly: Counter[str] = Counter()
        participant_messages: Counter[str] = Counter()
        participant_characters: Counter[str] = Counter()
        participant_questions: Counter[str] = Counter()
        participant_sample: dict[str, str] = {}
        token_documents: Counter[str] = Counter()
        message_count = 0
        service_events = 0
        unresolved_sender_messages = 0
        reply_marked = 0
        empty_messages = 0
        total_characters = 0
        statement = (
            select(
                Message.id,
                Message.sender_id,
                Message.sent_at,
                Message.message_type,
                Message.reply_to_external_id,
                Message.raw_metadata,
                MessageRevision.text,
            )
            .join(SnapshotMessageRevision, SnapshotMessageRevision.message_id == Message.id)
            .join(MessageRevision, MessageRevision.id == SnapshotMessageRevision.revision_id)
            .where(SnapshotMessageRevision.snapshot_id == snapshot.id)
            .order_by(Message.sent_at, Message.id)
            .execution_options(yield_per=1000)
        )
        for row in self.session.execute(statement):
            message_count += 1
            month = row.sent_at.strftime("%Y-%m")
            monthly[month] += 1
            service_events += int(row.message_type == "service")
            unresolved_sender_messages += int(
                row.message_type == "message"
                and row.sender_id is None
                and (row.raw_metadata or {}).get("sender_identity_basis") == "unresolved_sender_run"
            )
            reply_marked += int(row.reply_to_external_id is not None)
            empty_messages += int(not row.text.strip())
            total_characters += len(row.text)
            if row.sender_id:
                participant_messages[row.sender_id] += 1
                participant_characters[row.sender_id] += len(row.text)
                participant_questions[row.sender_id] += int("?" in row.text)
                participant_sample.setdefault(row.sender_id, row.id)
            unique_tokens = set(tokens(row.text))
            token_documents.update(unique_tokens)
        task.progress = 0.25
        task.checkpoint = {"stage": "source_and_lexical_counts", "messages": message_count}
        self.session.flush()

        participant_names = {
            participant.id: participant.display_name
            for participant in self.session.scalars(
                select(Participant).where(Participant.corpus_id == corpus.id)
            )
        }
        source_membership = aliased(SnapshotMessageRevision)
        target_membership = aliased(SnapshotMessageRevision)
        target_message = aliased(Message)
        directed: Counter[tuple[str, str]] = Counter()
        reply_sent: Counter[str] = Counter()
        reply_received: Counter[str] = Counter()
        reply_latencies: list[float] = []
        response_count = 0
        reply_statement = (
            select(
                Message.sender_id.label("source_sender"),
                target_message.sender_id.label("target_sender"),
                Message.sent_at.label("source_at"),
                target_message.sent_at.label("target_at"),
            )
            .join(ResponseRelation, ResponseRelation.source_message_id == Message.id)
            .join(target_message, target_message.id == ResponseRelation.target_message_id)
            .join(source_membership, source_membership.message_id == Message.id)
            .join(target_membership, target_membership.message_id == target_message.id)
            .where(
                source_membership.snapshot_id == snapshot.id,
                target_membership.snapshot_id == snapshot.id,
                ResponseRelation.explicit.is_(True),
                ResponseRelation.relation_type == "REPLIES_TO",
            )
            .execution_options(yield_per=1000)
        )
        for row in self.session.execute(reply_statement):
            response_count += 1
            if row.source_sender and row.target_sender and row.source_sender != row.target_sender:
                directed[(row.source_sender, row.target_sender)] += 1
                reply_sent[row.source_sender] += 1
                reply_received[row.target_sender] += 1
            latency = (row.source_at - row.target_at).total_seconds() / 60
            if 0 <= latency <= 60 * 24 * 30:
                reply_latencies.append(latency)
        task.progress = 0.45
        task.checkpoint = {"stage": "reply_network", "responses": response_count}
        self.session.flush()

        temporal = self._temporal(monthly)
        participation = self._participation(
            participant_messages,
            participant_names,
            message_count,
        )
        network, roles = self._network(
            directed,
            participant_messages,
            participant_characters,
            participant_questions,
            reply_sent,
            reply_received,
            participant_names,
        )
        reciprocity_numerator = sum(
            min(count, directed.get((target, source), 0))
            for (source, target), count in directed.items()
        )
        reply_structure = {
            "reply_markers": reply_marked,
            "resolved_reply_relations": response_count,
            "missing_reply_targets": max(reply_marked - response_count, 0),
            "resolved_reply_rate": response_count / message_count if message_count else 0,
            "target_resolution_rate": response_count / reply_marked if reply_marked else 0,
            "weighted_dyadic_reciprocity": (
                reciprocity_numerator / sum(directed.values()) if directed else 0
            ),
            "median_response_minutes": percentile(reply_latencies, 0.5),
            "p90_response_minutes": percentile(reply_latencies, 0.9),
            "valid_latency_sample": len(reply_latencies),
        }
        lexical = self._lexical(
            snapshot,
            token_documents,
        )
        semantic_themes = self._semantic_themes(corpus, snapshot, temporal)
        sessions = (
            self.session.scalar(
                select(func.count())
                .select_from(ConversationSession)
                .join(Conversation, Conversation.id == ConversationSession.conversation_id)
                .where(Conversation.corpus_id == corpus.id)
            )
            or 0
        )
        attachments = list(
            self.session.scalars(
                select(AttachmentRef.source_metadata)
                .join(Message, Message.id == AttachmentRef.message_id)
                .join(
                    SnapshotMessageRevision,
                    SnapshotMessageRevision.message_id == Message.id,
                )
                .where(SnapshotMessageRevision.snapshot_id == snapshot.id)
            )
        )
        attachment_states = Counter(
            "included" if metadata.get("included", True) else "not_included"
            for metadata in attachments
        )
        source = {
            "messages": message_count,
            "participants": len(participant_messages),
            "service_events": service_events,
            "unresolved_sender_messages": unresolved_sender_messages,
            "empty_messages": empty_messages,
            "mean_message_characters": total_characters / message_count if message_count else 0,
            "first_timestamp": first_at.isoformat() if first_at else None,
            "last_timestamp": last_at.isoformat() if last_at else None,
            "sessions_8h": sessions,
            "attachment_states": dict(attachment_states),
        }
        health_primitives = {
            "goal": "informal_social",
            "participation_balance": participation["normalized_entropy"],
            "reply_target_resolution": reply_structure["target_resolution_rate"],
            "dyadic_reciprocity": reply_structure["weighted_dyadic_reciprocity"],
            "median_response_minutes": reply_structure["median_response_minutes"],
            "session_count": sessions,
            "aggregate_score": None,
            "missing_dimensions": [
                "semantic_responsivity",
                "grounding",
                "repair",
                "constructiveness",
                "goal_progress",
            ],
        }
        task.progress = 0.8
        task.checkpoint = {"stage": "dimension_assembly"}
        self.session.flush()
        return (
            {
                "source": source,
                "temporal": temporal,
                "participation": participation,
                "reply_structure": reply_structure,
                "network": network,
                "roles": roles,
                "lexical_evolution": lexical,
                "semantic_themes": semantic_themes,
                "health_primitives": health_primitives,
                "data_quality": {
                    "timestamp_timezone": "unspecified_in_telegram_html"
                    if corpus.source_type == "telegram_html"
                    else "source_defined",
                    "missing_reply_targets": max(reply_marked - response_count, 0),
                    "missing_attachment_binaries": attachment_states.get("not_included", 0),
                    "unresolved_sender_messages": unresolved_sender_messages,
                    "language_validation": corpus.is_validated_language,
                },
            },
            {
                "top_participant_message": participant_sample.get(
                    participant_messages.most_common(1)[0][0] if participant_messages else "",
                    "",
                ),
                "busiest_month_message": self._message_in_month(
                    snapshot.id, temporal["busiest_month"]
                ),
            },
        )

    @staticmethod
    def _temporal(monthly: Counter[str]) -> dict[str, Any]:
        series = [{"month": month, "messages": monthly[month]} for month in sorted(monthly)]
        deltas = [
            math.log1p(series[index]["messages"]) - math.log1p(series[index - 1]["messages"])
            for index in range(1, len(series))
        ]
        center = median(deltas) if deltas else 0
        deviations = [abs(value - center) for value in deltas]
        mad = median(deviations) if deviations else 0
        change_points = []
        for index, delta in enumerate(deltas, start=1):
            score = abs(delta - center) / (1.4826 * mad) if mad else abs(delta - center)
            if score >= 2:
                change_points.append(
                    {
                        "month": series[index]["month"],
                        "previous_messages": series[index - 1]["messages"],
                        "messages": series[index]["messages"],
                        "log_change": delta,
                        "robust_score": score,
                        "direction": "increase" if delta > 0 else "decrease",
                    }
                )
        busiest = max(series, key=lambda item: item["messages"], default=None)
        return {
            "monthly_activity": series,
            "busiest_month": busiest,
            "change_points": sorted(
                change_points, key=lambda item: item["robust_score"], reverse=True
            )[:6],
            "change_method": "robust_log_month_delta_mad",
            "partial_month_warning": True,
        }

    @staticmethod
    def _participation(counts: Counter[str], names: dict[str, str], total: int) -> dict[str, Any]:
        shares = [count / total for count in counts.values()] if total else []
        entropy = -sum(share * math.log2(share) for share in shares if share)
        normalized = entropy / math.log2(len(shares)) if len(shares) > 1 else 0
        ranked = [
            {
                "participant_id": participant_id,
                "participant": names.get(participant_id, "Неизвестный участник"),
                "messages": count,
                "share": count / total if total else 0,
            }
            for participant_id, count in counts.most_common(20)
        ]
        return {
            "entropy_bits": entropy,
            "normalized_entropy": normalized,
            "gini": gini(list(counts.values())),
            "top_participants": ranked,
            "top_1_share": ranked[0]["share"] if ranked else 0,
            "top_10_share": sum(item["share"] for item in ranked[:10]),
            "interpretation_guardrail": (
                "Доля сообщений не является мерой влияния, знания или власти."
            ),
        }

    @staticmethod
    def _network(
        directed: Counter[tuple[str, str]],
        messages: Counter[str],
        characters: Counter[str],
        questions: Counter[str],
        reply_sent: Counter[str],
        reply_received: Counter[str],
        names: dict[str, str],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        participant_ids = sorted(
            {participant for edge in directed for participant in edge} | set(messages)
        )
        graph = ig.Graph(directed=True)
        graph.add_vertices(participant_ids)
        weighted_edges = [(source, target, weight) for (source, target), weight in directed.items()]
        if weighted_edges:
            graph.add_edges([(source, target) for source, target, _weight in weighted_edges])
            graph.es["weight"] = [weight for _source, _target, weight in weighted_edges]
            pagerank = graph.pagerank(weights="weight")
            distances = [1 / max(weight, 1) for weight in graph.es["weight"]]
            betweenness = graph.betweenness(directed=True, weights=distances)
            undirected = graph.as_undirected(combine_edges={"weight": "sum"})
            communities = undirected.community_multilevel(weights="weight")
        else:
            pagerank = [0 for _participant in participant_ids]
            betweenness = [0 for _participant in participant_ids]
            communities = []
        page_by_id = dict(zip(participant_ids, pagerank, strict=True))
        between_by_id = dict(zip(participant_ids, betweenness, strict=True))
        degree_by_id = {
            participant_id: graph.degree(participant_id, mode="all")
            for participant_id in participant_ids
        }
        top_nodes = sorted(
            participant_ids,
            key=lambda participant_id: page_by_id[participant_id],
            reverse=True,
        )[:20]
        community_payload = []
        for community_id, members in enumerate(communities):
            member_ids = [participant_ids[index] for index in members]
            community_payload.append(
                {
                    "community_id": community_id,
                    "size": len(member_ids),
                    "members": [
                        names.get(participant_id, "Неизвестный участник")
                        for participant_id in sorted(
                            member_ids,
                            key=lambda value: page_by_id[value],
                            reverse=True,
                        )[:8]
                    ],
                }
            )
        network = {
            "participants": len(participant_ids),
            "directed_dyads": len(directed),
            "interaction_communities": sorted(
                community_payload, key=lambda item: item["size"], reverse=True
            ),
            "top_nodes": [
                {
                    "participant_id": participant_id,
                    "participant": names.get(participant_id, "Неизвестный участник"),
                    "pagerank": page_by_id[participant_id],
                    "betweenness": between_by_id[participant_id],
                    "degree": degree_by_id[participant_id],
                    "messages": messages[participant_id],
                    "replies_sent": reply_sent[participant_id],
                    "replies_received": reply_received[participant_id],
                }
                for participant_id in top_nodes
            ],
            "interpretation_guardrail": (
                "Центральность взаимодействия не является интеллектуальным влиянием, "
                "убеждением или властью."
            ),
        }
        between_threshold = percentile(list(between_by_id.values()), 0.75) or 0
        message_threshold = percentile([float(value) for value in messages.values()], 0.75) or 0
        response_rates = [
            reply_sent[participant_id] / messages[participant_id]
            for participant_id in participant_ids
            if messages[participant_id]
        ]
        response_threshold = percentile(response_rates, 0.75) or 0
        roles = []
        for participant_id in participant_ids:
            message_total = messages[participant_id]
            if message_total < 5:
                continue
            profiles: list[str] = []
            if between_by_id[participant_id] >= between_threshold and between_threshold > 0:
                profiles.append("broker-like")
            if message_total >= message_threshold:
                profiles.append("high-volume contributor")
            response_rate = reply_sent[participant_id] / message_total
            if response_rate >= response_threshold and response_threshold > 0:
                profiles.append("response-oriented")
            if reply_received[participant_id] > reply_sent[participant_id] * 1.5:
                profiles.append("attention hub")
            if not profiles:
                profiles.append("occasional contributor")
            roles.append(
                {
                    "participant_id": participant_id,
                    "participant": names.get(participant_id, "Неизвестный участник"),
                    "profiles": profiles,
                    "messages": message_total,
                    "mean_message_characters": characters[participant_id] / message_total,
                    "question_rate": questions[participant_id] / message_total,
                    "reply_rate": response_rate,
                    "betweenness": between_by_id[participant_id],
                    "status": "provisional_behavioral_profile",
                }
            )
        roles.sort(key=lambda item: ("broker-like" not in item["profiles"], -item["messages"]))
        return network, {"participant_profiles": roles[:30]}

    def _lexical(
        self,
        snapshot: CorpusSnapshot,
        documents: Counter[str],
    ) -> dict[str, Any]:
        vocabulary = [term for term, count in documents.most_common(80) if count >= 5]
        vocabulary_set = set(vocabulary)
        cooccurrence: Counter[tuple[str, str]] = Counter()
        statement = (
            select(MessageRevision.text)
            .join(
                SnapshotMessageRevision,
                SnapshotMessageRevision.revision_id == MessageRevision.id,
            )
            .where(SnapshotMessageRevision.snapshot_id == snapshot.id)
            .execution_options(yield_per=1000)
        )
        for value in self.session.scalars(statement):
            present = sorted(set(tokens(value)) & vocabulary_set)
            if len(present) > 15:
                present = present[:15]
            cooccurrence.update(itertools.combinations(present, 2))
        graph = ig.Graph()
        graph.add_vertices(vocabulary)
        edges = [
            (left, right, weight) for (left, right), weight in cooccurrence.items() if weight >= 3
        ]
        themes = []
        if edges:
            graph.add_edges([(left, right) for left, right, _weight in edges])
            graph.es["weight"] = [weight for _left, _right, weight in edges]
            communities = graph.community_multilevel(weights="weight")
            for theme_id, members in enumerate(communities):
                terms = [vocabulary[index] for index in members]
                ranked = sorted(terms, key=lambda term: documents[term], reverse=True)[:8]
                if len(ranked) >= 2:
                    themes.append(
                        {
                            "theme_id": theme_id,
                            "terms": ranked,
                            "document_frequency": sum(documents[term] for term in ranked),
                        }
                    )
        return {
            "method": "russian_lexical_document_frequency_and_cooccurrence_v1",
            "themes": sorted(themes, key=lambda item: item["document_frequency"], reverse=True)[
                :10
            ],
            "guardrail": (
                "Лексические кластеры — средство навигации, а не валидированные семантические темы."
            ),
        }

    def _semantic_themes(
        self,
        corpus: Corpus,
        snapshot: CorpusSnapshot,
        temporal: dict[str, Any],
    ) -> dict[str, Any]:
        episodes: dict[str, dict[str, Any]] = {}
        statement = (
            select(
                Episode.id.label("episode_id"),
                Message.id.label("message_id"),
                Message.sender_id,
                Message.sent_at,
                MessageRevision.text,
            )
            .join(EpisodeMessage, EpisodeMessage.episode_id == Episode.id)
            .join(Message, Message.id == EpisodeMessage.message_id)
            .join(
                SnapshotMessageRevision,
                SnapshotMessageRevision.message_id == Message.id,
            )
            .join(
                MessageRevision,
                MessageRevision.id == SnapshotMessageRevision.revision_id,
            )
            .join(ConversationSession, ConversationSession.id == Episode.session_id)
            .join(Conversation, Conversation.id == ConversationSession.conversation_id)
            .where(
                SnapshotMessageRevision.snapshot_id == snapshot.id,
                Conversation.corpus_id == corpus.id,
                Message.message_type == "message",
            )
            .order_by(Episode.id, EpisodeMessage.ordinal)
            .execution_options(yield_per=1000)
        )
        for row in self.session.execute(statement):
            episode = episodes.setdefault(
                row.episode_id,
                {
                    "id": row.episode_id,
                    "records": [],
                },
            )
            episode["records"].append(
                {
                    "message_id": row.message_id,
                    "sender_id": row.sender_id,
                    "sent_at": row.sent_at,
                    "text": row.text,
                }
            )
        documents = self._semantic_windows(episodes)
        if not documents:
            return self._empty_semantic_themes(
                "no non-empty episodes",
                structural_episode_count=len(episodes),
            )
        lemmatized = [self._lemmatize("\n".join(episode["texts"])) for episode in documents]
        vectorizer = TfidfVectorizer(
            token_pattern=r"(?u)\b[а-яё][а-яё]+\b",
            ngram_range=(1, 2),
            min_df=2 if len(documents) >= 4 else 1,
            max_df=0.9 if len(documents) >= 4 else 1.0,
            max_features=20_000,
            sublinear_tf=True,
        )
        try:
            matrix = vectorizer.fit_transform(lemmatized)
        except ValueError:
            return self._empty_semantic_themes(
                "insufficient Russian lexical features",
                structural_episode_count=len(episodes),
                window_count=len(documents),
            )
        if matrix.shape[1] < 2:
            return self._empty_semantic_themes(
                "insufficient feature variance",
                structural_episode_count=len(episodes),
                window_count=len(documents),
            )
        components = min(48, matrix.shape[0] - 1, matrix.shape[1] - 1)
        if components >= 2:
            reducer = TruncatedSVD(n_components=components, random_state=42)
            vectors = Normalizer(copy=False).fit_transform(reducer.fit_transform(matrix))
            explained_variance = float(reducer.explained_variance_ratio_.sum())
        else:
            vectors = matrix.toarray()
            explained_variance = 1.0
        labels, cluster_count, silhouette = self._select_clusters(vectors)
        feature_names = vectorizer.get_feature_names_out()
        participant_names = {
            participant.id: participant.display_name
            for participant in self.session.scalars(
                select(Participant).where(Participant.corpus_id == corpus.id)
            )
        }
        months = [item["month"] for item in temporal["monthly_activity"]]
        monthly_totals = {item["month"]: item["messages"] for item in temporal["monthly_activity"]}
        global_centroid = np.asarray(matrix.mean(axis=0)).ravel()
        themes = []
        all_changes = []
        for cluster_id in range(cluster_count):
            indices = np.flatnonzero(labels == cluster_id)
            if not len(indices):
                continue
            centroid = np.asarray(matrix[indices].mean(axis=0)).ravel()
            distinctiveness = centroid * np.maximum(
                np.log((centroid + 1e-9) / (global_centroid + 1e-9)),
                0,
            )
            top_indices = distinctiveness.argsort()[::-1]
            terms = [
                str(feature_names[index]) for index in top_indices if distinctiveness[index] > 0
            ][:10]
            center = vectors[indices].mean(axis=0)
            distances = np.linalg.norm(vectors[indices] - center, axis=1)
            representative_indices = indices[np.argsort(distances)[:3]]
            representative_ids = [
                self._representative_message_id(
                    documents[index],
                    vectorizer,
                    centroid,
                )
                for index in representative_indices
            ]
            monthly_messages: Counter[str] = Counter()
            participant_counts: Counter[str] = Counter()
            message_total = 0
            for index in indices:
                episode = documents[index]
                month = episode["start_at"].strftime("%Y-%m")
                episode_messages = len(episode["message_ids"])
                monthly_messages[month] += episode_messages
                message_total += episode_messages
                participant_counts.update(episode["participants"])
            trajectory = [
                {
                    "month": month,
                    "messages": monthly_messages[month],
                    "share": (
                        monthly_messages[month] / monthly_totals[month]
                        if monthly_totals.get(month)
                        else 0
                    ),
                }
                for month in months
            ]
            change_points = self._theme_change_points(trajectory)
            label = " · ".join(terms[:3]) if terms else f"Тема {cluster_id + 1}"
            theme = {
                "theme_id": cluster_id,
                "label": label,
                "terms": terms,
                "episodes": len(indices),
                "messages": message_total,
                "trajectory": trajectory,
                "change_points": change_points,
                "top_participants": [
                    {
                        "participant_id": participant_id,
                        "participant": participant_names.get(
                            participant_id, "Неизвестный участник"
                        ),
                        "messages": count,
                        "share": count / message_total if message_total else 0,
                    }
                    for participant_id, count in participant_counts.most_common(8)
                ],
                "representative_message_ids": representative_ids,
            }
            themes.append(theme)
            all_changes.extend(
                {
                    **change,
                    "theme_id": cluster_id,
                    "theme_label": label,
                    "representative_message_id": representative_ids[0]
                    if representative_ids
                    else None,
                }
                for change in change_points
            )
        themes.sort(key=lambda item: item["messages"], reverse=True)
        all_changes.sort(key=lambda item: item["robust_score"], reverse=True)
        separation_quality = self._separation_quality(silhouette)
        return {
            "method": "pymorphy3_tfidf_svd_kmeans_episode_window_v2",
            "status": "provisional_semantic_navigation",
            "unit": "episode_window",
            "structural_episode_count": len(episodes),
            "window_message_limit": 40,
            "episode_count": len(documents),
            "cluster_count": len(themes),
            "silhouette": silhouette,
            "separation_quality": separation_quality,
            "quality_note": {
                "high": "Темы хорошо разделены по внутренней диагностике.",
                "moderate": "Темы разделены умеренно; соседние темы могут пересекаться.",
                "low": (
                    "Разделимость низкая: используйте темы для навигации, "
                    "а не как устойчивую таксономию разговора."
                ),
                "unavailable": "Разделимость невозможно оценить на доступных данных.",
            }[separation_quality],
            "explained_variance": explained_variance,
            "themes": themes,
            "change_events": all_changes[:15],
            "guardrail": (
                "Темы получены без учителя из окон до 40 сообщений внутри сессий; "
                "названия основаны на отличительных терминах и требуют человеческой проверки."
            ),
        }

    @staticmethod
    def _semantic_windows(
        episodes: dict[str, dict[str, Any]],
        *,
        message_limit: int = 40,
        minimum_tail: int = 10,
    ) -> list[dict[str, Any]]:
        windows: list[dict[str, Any]] = []
        for episode in episodes.values():
            records = episode["records"]
            chunks = [
                records[index : index + message_limit]
                for index in range(0, len(records), message_limit)
            ]
            if len(chunks) > 1 and len(chunks[-1]) < minimum_tail:
                chunks[-2].extend(chunks.pop())
            for window_index, chunk in enumerate(chunks):
                texts = [record["text"] for record in chunk if record["text"].strip()]
                if not texts:
                    continue
                text_records = [record for record in chunk if record["text"].strip()]
                windows.append(
                    {
                        "id": f"{episode['id']}:{window_index}",
                        "texts": texts,
                        "text_message_ids": [record["message_id"] for record in text_records],
                        "message_ids": [record["message_id"] for record in chunk],
                        "participants": Counter(
                            record["sender_id"] for record in chunk if record["sender_id"]
                        ),
                        "start_at": chunk[0]["sent_at"],
                    }
                )
        return windows

    @staticmethod
    def _separation_quality(silhouette: float | None) -> str:
        if silhouette is None:
            return "unavailable"
        if silhouette >= 0.2:
            return "high"
        if silhouette >= 0.1:
            return "moderate"
        return "low"

    def _lemmatize(self, value: str) -> str:
        lemmas = []
        for token in WORD_PATTERN.findall(value):
            lowered = token.casefold()
            lemma = self._lemma_cache.get(lowered)
            if lemma is None:
                if self._morph is None:
                    self._morph = pymorphy3.MorphAnalyzer()
                lemma = self._morph.parse(lowered)[0].normal_form
                self._lemma_cache[lowered] = lemma
            if len(lemma) >= 4 and lemma not in RUSSIAN_STOPWORDS:
                lemmas.append(lemma)
        return " ".join(lemmas)

    def _representative_message_id(
        self,
        episode: dict[str, Any],
        vectorizer: TfidfVectorizer,
        theme_centroid: np.ndarray,
    ) -> str:
        texts = episode["texts"]
        message_ids = episode["text_message_ids"]
        if not texts:
            return episode["message_ids"][0]
        message_matrix = vectorizer.transform(self._lemmatize(text) for text in texts)
        similarities = np.asarray(message_matrix @ theme_centroid).ravel()
        return message_ids[int(similarities.argmax())]

    @staticmethod
    def _select_clusters(vectors: np.ndarray) -> tuple[np.ndarray, int, float | None]:
        count = len(vectors)
        if count < 2:
            return np.zeros(count, dtype=int), 1, None
        distinct_count = len(np.unique(np.round(vectors, decimals=8), axis=0))
        if distinct_count < 2:
            return np.zeros(count, dtype=int), 1, None
        maximum = min(10, count - 1, distinct_count)
        minimum = 2
        best_labels = np.zeros(count, dtype=int)
        best_count = 1
        best_score = -1.0
        minimum_cluster_size = max(2, math.ceil(count * 0.01))
        for cluster_count in range(minimum, maximum + 1):
            model = KMeans(n_clusters=cluster_count, random_state=42, n_init=10)
            labels = model.fit_predict(vectors)
            if len(set(labels)) < 2:
                continue
            cluster_sizes = np.bincount(labels)
            if cluster_sizes.min() < minimum_cluster_size:
                continue
            try:
                score = float(
                    silhouette_score(
                        vectors,
                        labels,
                        metric="cosine",
                        sample_size=min(count, 2_000),
                        random_state=42,
                    )
                )
            except ValueError:
                continue
            if not math.isfinite(score):
                continue
            if score > best_score:
                best_labels = labels
                best_count = cluster_count
                best_score = score
        return best_labels, best_count, best_score if best_count > 1 else None

    @staticmethod
    def _theme_change_points(trajectory: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(trajectory) < 4:
            return []
        deltas = [
            math.log((trajectory[index]["share"] + 1e-4) / (trajectory[index - 1]["share"] + 1e-4))
            for index in range(1, len(trajectory))
        ]
        center = median(deltas)
        mad = median(abs(value - center) for value in deltas)
        changes = []
        for index, delta in enumerate(deltas, start=1):
            score = abs(delta - center) / (1.4826 * mad) if mad else abs(delta - center)
            if score < 2 or trajectory[index]["messages"] < 5:
                continue
            direction = "increase" if delta > 0 else "decrease"
            previous_share = trajectory[index - 1]["share"]
            current_share = trajectory[index]["share"]
            threshold = (previous_share + current_share) / 2
            persistence = 0
            for later in trajectory[index:]:
                persists = (
                    later["share"] >= threshold
                    if direction == "increase"
                    else later["share"] <= threshold
                )
                if not persists:
                    break
                persistence += 1
            changes.append(
                {
                    "month": trajectory[index]["month"],
                    "direction": direction,
                    "previous_share": previous_share,
                    "share": current_share,
                    "share_delta": current_share - previous_share,
                    "robust_score": score,
                    "persistence_months": persistence,
                }
            )
        return sorted(changes, key=lambda item: item["robust_score"], reverse=True)[:5]

    @staticmethod
    def _empty_semantic_themes(
        reason: str,
        *,
        structural_episode_count: int = 0,
        window_count: int = 0,
    ) -> dict[str, Any]:
        return {
            "method": "pymorphy3_tfidf_svd_kmeans_episode_window_v2",
            "status": "insufficient_data",
            "unit": "episode_window",
            "structural_episode_count": structural_episode_count,
            "window_message_limit": 40,
            "episode_count": window_count,
            "cluster_count": 0,
            "silhouette": None,
            "separation_quality": "unavailable",
            "quality_note": "Разделимость невозможно оценить на доступных данных.",
            "explained_variance": None,
            "themes": [],
            "change_events": [],
            "guardrail": reason,
        }

    def _persist_measurements(
        self,
        corpus: Corpus,
        snapshot: CorpusSnapshot,
        run: AnalysisRun,
        payloads: dict[str, Any],
    ) -> dict[str, MeasurementResult]:
        results: dict[str, MeasurementResult] = {}
        measurement_version = ANALYSIS_VERSION.rsplit("@", maxsplit=1)[-1]
        for dimension, payload in payloads.items():
            definition_id = f"observatory-{dimension}@{measurement_version}"
            if self.session.get(MeasurementDefinition, definition_id) is None:
                self.session.add(
                    MeasurementDefinition(
                        id=definition_id,
                        version=measurement_version,
                        title=dimension.replace("_", " ").title(),
                        description=(
                            "Snapshot-scoped descriptive observatory measurement; "
                            "not a causal or personality inference."
                        ),
                        unit_of_analysis="corpus_snapshot",
                        manifest={
                            "analysis_version": ANALYSIS_VERSION,
                            "causal": False,
                            "provisional": dimension
                            in {"roles", "lexical_evolution", "semantic_themes"},
                        },
                    )
                )
            result = MeasurementResult(
                id=new_id(),
                definition_id=definition_id,
                run_id=run.id,
                subject_type="corpus_snapshot",
                subject_id=snapshot.id,
                result=payload,
                provenance={
                    "snapshot_id": snapshot.id,
                    "snapshot_manifest_hash": snapshot.manifest_hash,
                    "run_id": run.id,
                    "analysis_version": ANALYSIS_VERSION,
                },
            )
            self.session.add(result)
            results[dimension] = result
        self.session.flush()
        return results

    def _persist_findings(
        self,
        corpus: Corpus,
        snapshot: CorpusSnapshot,
        run: AnalysisRun,
        results: dict[str, MeasurementResult],
        payloads: dict[str, Any],
        evidence: dict[str, str],
    ) -> list[dict[str, Any]]:
        candidates: list[tuple[str, str, list[str], str | None]] = []
        busiest = payloads["temporal"]["busiest_month"]
        if busiest:
            candidates.append(
                (
                    "temporal",
                    f"Максимальная активность наблюдалась в {busiest['month']}: "
                    f"{busiest['messages']:,} сообщений.",
                    [
                        "Неполные крайние месяцы и изменения состава участников "
                        "могут влиять на сравнение."
                    ],
                    evidence.get("busiest_month_message"),
                )
            )
        participation = payloads["participation"]
        if participation["top_participants"]:
            top = participation["top_participants"][0]
            candidates.append(
                (
                    "participation",
                    f"{top['participant']} создал(а) {top['share']:.1%} сообщений корпуса.",
                    ["Объём сообщений не является мерой влияния, знания или власти."],
                    evidence.get("top_participant_message"),
                )
            )
        reply = payloads["reply_structure"]
        candidates.append(
            (
                "reply_structure",
                f"Разрешено {reply['resolved_reply_relations']:,} из "
                f"{reply['reply_markers']:,} явных ссылок на ответы.",
                [
                    "Отсутствующая цель означает неполноту экспорта, "
                    "а не отсутствие ответа в исходном чате."
                ],
                None,
            )
        )
        semantic = payloads["semantic_themes"]
        if semantic["change_events"] and semantic["separation_quality"] != "low":
            change = semantic["change_events"][0]
            candidates.append(
                (
                    "semantic_themes",
                    f"Тема «{change['theme_label']}» изменила месячную долю сообщений "
                    f"в {change['month']} с {change['previous_share']:.1%} "
                    f"до {change['share']:.1%}.",
                    [
                        "Автоматическая тема предварительна; изменение может отражать "
                        "одно событие, смену состава участников или ошибку кластеризации."
                    ],
                    change.get("representative_message_id"),
                )
            )
        output = []
        for dimension, claim, alternatives, message_id in candidates:
            supporting = [{"object_type": "message", "object_id": message_id}] if message_id else []
            finding = Finding(
                id=new_id(),
                run_id=run.id,
                claim=claim,
                epistemic_level=EpistemicLevel.MEASUREMENT,
                causal_status=CausalStatus.DESCRIPTIVE,
                supporting_evidence=supporting,
                counterevidence=[],
                alternative_explanations=alternatives,
                sensitivity_results=[],
                dependency_dag_root=results[dimension].id,
                provenance={
                    "snapshot_id": snapshot.id,
                    "snapshot_manifest_hash": snapshot.manifest_hash,
                    "run_id": run.id,
                    "analysis_version": ANALYSIS_VERSION,
                },
            )
            self.session.add(finding)
            self.session.add(
                DerivationEdge(
                    id=new_id(),
                    source_type="measurement",
                    source_id=results[dimension].id,
                    target_type="finding",
                    target_id=finding.id,
                    relation="SUPPORTS_FINDING",
                    run_id=run.id,
                )
            )
            output.append(
                {
                    "id": finding.id,
                    "dimension": dimension,
                    "claim": claim,
                    "epistemic_level": "L2_MEASUREMENT",
                    "causal_status": "descriptive",
                    "supporting_evidence": supporting,
                    "alternative_explanations": alternatives,
                }
            )
        self.session.flush()
        return output

    def _message_in_month(self, snapshot_id: str, busiest: dict | None) -> str:
        if not busiest:
            return ""
        prefix = busiest["month"]
        return (
            self.session.scalar(
                select(Message.id)
                .join(
                    SnapshotMessageRevision,
                    SnapshotMessageRevision.message_id == Message.id,
                )
                .where(
                    SnapshotMessageRevision.snapshot_id == snapshot_id,
                    func.strftime("%Y-%m", Message.sent_at) == prefix,
                )
                .limit(1)
            )
            if self.session.bind is not None and self.session.bind.dialect.name == "sqlite"
            else self.session.scalar(
                select(Message.id)
                .join(
                    SnapshotMessageRevision,
                    SnapshotMessageRevision.message_id == Message.id,
                )
                .where(
                    SnapshotMessageRevision.snapshot_id == snapshot_id,
                    func.to_char(Message.sent_at, "YYYY-MM") == prefix,
                )
                .limit(1)
            )
        ) or ""
