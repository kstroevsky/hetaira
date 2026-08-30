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

ANALYSIS_VERSION = "observatory-overview@1.1.0"
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
                "health_primitives": health_primitives,
                "data_quality": {
                    "timestamp_timezone": "unspecified_in_telegram_html"
                    if corpus.source_type == "telegram_html"
                    else "source_defined",
                    "missing_reply_targets": max(reply_marked - response_count, 0),
                    "missing_attachment_binaries": attachment_states.get("not_included", 0),
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

    def _persist_measurements(
        self,
        corpus: Corpus,
        snapshot: CorpusSnapshot,
        run: AnalysisRun,
        payloads: dict[str, Any],
    ) -> dict[str, MeasurementResult]:
        results: dict[str, MeasurementResult] = {}
        for dimension, payload in payloads.items():
            definition_id = f"observatory-{dimension}@1"
            if self.session.get(MeasurementDefinition, definition_id) is None:
                self.session.add(
                    MeasurementDefinition(
                        id=definition_id,
                        version="1",
                        title=dimension.replace("_", " ").title(),
                        description=(
                            "Snapshot-scoped descriptive observatory measurement; "
                            "not a causal or personality inference."
                        ),
                        unit_of_analysis="corpus_snapshot",
                        manifest={
                            "analysis_version": ANALYSIS_VERSION,
                            "causal": False,
                            "provisional": dimension in {"roles", "lexical_evolution"},
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
