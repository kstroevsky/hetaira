from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .codebooks import release_identity
from .config import get_settings
from .measurements import MeasurementContext, foundational_registry
from .models import (
    AnalysisRun,
    AnalysisTask,
    Annotation,
    Corpus,
    CorpusSnapshot,
    DependencyFingerprint,
    DerivationEdge,
    EpistemicObservation,
    Finding,
    MeasurementDefinition,
    MeasurementResult,
    Message,
    MessageRevision,
    Participant,
    PropositionMention,
    ResponseRelation,
    SnapshotMessageRevision,
    Span,
    StanceObservation,
    Utterance,
)
from .ontology import CausalStatus, EpistemicLevel, RunStatus
from .text import sentence_spans, text_hash

PATTERNS: dict[str, re.Pattern[str]] = {
    "QUESTION": re.compile(r"\?|\b(почему|зачем|когда|где|кто|что именно|как)\b", re.I),
    "PROPOSE": re.compile(r"\b(давайте|давай|предлагаю|можем|нужно|стоит)\b", re.I),
    "AGREE": re.compile(
        r"(?<!не )\b(согласен|согласна|согласны)\b|\b(верно|точно|поддерживаю)\b",
        re.I,
    ),
    "DISAGREE": re.compile(r"\b(не согласен|не согласна|возражаю|неверно|нет,|но это не)\b", re.I),
    "COMMIT": re.compile(r"\b(сделаю|возьму|обещаю|отпишусь|проверю|исправлю)\b", re.I),
    "ACKNOWLEDGE": re.compile(r"^(ок|понял[аи]?|ясно|вижу|принято)[.! ]*$", re.I),
    "UNCERTAIN": re.compile(
        r"\b(не уверен|не уверена|возможно|кажется|наверное|может быть|похоже)\b", re.I
    ),
    "CLARIFICATION_REQUESTED": re.compile(
        r"\b(уточни|уточните|что значит|не понял|не поняла|правильно ли)\b", re.I
    ),
    "REPAIRED": re.compile(
        r"\b(точнее|я имел в виду|я имела в виду|поправлюсь|не так выразил)\b", re.I
    ),
    "ARGUMENT": re.compile(r"\b(потому что|так как|поэтому|следовательно|из-за того)\b", re.I),
}


class DeterministicAnalyzer:
    codebook_version = "foundational-conversation-ru@0.1.0"
    model_name = "rules-ru-v1"

    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()

    def analyze(self, corpus_id: str) -> AnalysisRun:
        corpus = self.session.get(Corpus, corpus_id)
        if corpus is None:
            raise LookupError("corpus not found")
        snapshot = self.session.scalar(
            select(CorpusSnapshot)
            .where(CorpusSnapshot.corpus_id == corpus_id)
            .order_by(CorpusSnapshot.created_at.desc())
        )
        if snapshot is None:
            raise ValueError("corpus has no snapshot")
        codebook_release, codebook_hash = release_identity(
            self.session, "foundational-conversation-ru", "0.1.0"
        )
        self.codebook_version = codebook_release
        self.codebook_hash = codebook_hash
        dependencies = {
            "snapshot_manifest": snapshot.manifest_hash,
            "codebook_artifact": codebook_hash,
            "pipeline": self.settings.pipeline_version,
            "ontology": self.settings.ontology_version,
            "model_runtime": f"deterministic:{self.model_name}",
            "measurement_definitions": "participation-share@1,reply-reciprocity@1",
        }
        idempotency_key = hashlib.sha256(
            "\n".join(f"{key}={value}" for key, value in sorted(dependencies.items())).encode()
        ).hexdigest()
        existing_task = self.session.scalar(
            select(AnalysisTask).where(AnalysisTask.idempotency_key == idempotency_key)
        )
        if existing_task is not None:
            existing_run = self.session.get(AnalysisRun, existing_task.run_id)
            if existing_run is not None:
                return existing_run
        run = AnalysisRun(
            snapshot_id=snapshot.id,
            run_type="deterministic-foundation",
            status=RunStatus.RUNNING,
            progress=0,
            configuration={
                "language": corpus.language,
                "codebook": self.codebook_version,
                "ontology_version": self.settings.ontology_version,
            },
            started_at=datetime.now(UTC),
        )
        self.session.add(run)
        self.session.flush()
        task = AnalysisTask(
            run_id=run.id,
            task_key="foundational_annotations",
            status=RunStatus.RUNNING,
            progress=0,
            idempotency_key=idempotency_key,
        )
        self.session.add(task)
        self.session.flush()
        self.session.add_all(
            DependencyFingerprint(
                task_id=task.id,
                dependency_type=dependency_type,
                dependency_key=dependency_type,
                fingerprint=hashlib.sha256(value.encode()).hexdigest(),
            )
            for dependency_type, value in dependencies.items()
        )
        rows = self.session.execute(
            select(Message, MessageRevision, Participant)
            .join(SnapshotMessageRevision, SnapshotMessageRevision.message_id == Message.id)
            .join(MessageRevision, MessageRevision.id == SnapshotMessageRevision.revision_id)
            .outerjoin(Participant, Participant.id == Message.sender_id)
            .where(SnapshotMessageRevision.snapshot_id == snapshot.id)
            .order_by(Message.sent_at)
        ).all()
        total = max(len(rows), 1)
        proposition_by_message: dict[str, list[PropositionMention]] = defaultdict(list)
        message_lookup = {message.id: message for message, _, _ in rows}
        external_lookup = {
            (message.conversation_id, message.external_id): message for message, _, _ in rows
        }
        for index, (message, revision, _participant) in enumerate(rows, start=1):
            utterances = self._utterances(revision, corpus.language)
            for utterance in utterances:
                span = self._span(revision, utterance)
                acts = self._dialogue_acts(utterance.exact_text)
                for act in acts:
                    self.session.add(
                        self._annotation(
                            snapshot.id,
                            run.id,
                            "span",
                            span.id,
                            "dialogue_act",
                            {"label": act, "holder_id": message.sender_id},
                            span,
                            confidence=0.92 if act != "ASSERT" else 0.72,
                        )
                    )
                grounding = self._grounding(utterance.exact_text)
                if grounding:
                    self.session.add(
                        self._annotation(
                            snapshot.id,
                            run.id,
                            "span",
                            span.id,
                            "grounding",
                            {"label": grounding, "holder_id": message.sender_id},
                            span,
                            confidence=0.84,
                        )
                    )
                if PATTERNS["ARGUMENT"].search(utterance.exact_text):
                    self.session.add(
                        self._annotation(
                            snapshot.id,
                            run.id,
                            "span",
                            span.id,
                            "argumentation",
                            {"label": "REASON_GIVING", "holder_id": message.sender_id},
                            span,
                            confidence=0.80,
                        )
                    )
                if self._is_proposition(utterance.exact_text, acts):
                    annotation = self._annotation(
                        snapshot.id,
                        run.id,
                        "utterance",
                        utterance.id,
                        "proposition",
                        {
                            "text": utterance.exact_text.rstrip(".!?…"),
                            "type": "proposal" if "PROPOSE" in acts else "claim",
                            "holder_id": message.sender_id,
                        },
                        span,
                        confidence=0.82,
                    )
                    self.session.add(annotation)
                    self.session.flush()
                    proposition = PropositionMention(
                        annotation_id=annotation.id,
                        utterance_id=utterance.id,
                        span_id=span.id,
                        normalized_text=utterance.exact_text.rstrip(".!?…").strip(),
                        proposition_type="proposal" if "PROPOSE" in acts else "claim",
                        language=corpus.language,
                    )
                    self.session.add(proposition)
                    self.session.flush()
                    proposition_by_message[message.id].append(proposition)
                    if message.sender_id:
                        self._epistemic_observation(
                            snapshot.id,
                            run.id,
                            message.sender_id,
                            proposition,
                            span,
                            utterance.exact_text,
                        )
            task.progress = index / total
            if index % 250 == 0:
                task.checkpoint = {"processed": index, "last_message_id": message.id}
                self.session.flush()
        self._stance_observations(
            snapshot.id,
            run.id,
            rows,
            proposition_by_message,
            message_lookup,
            external_lookup,
        )
        self._connect_annotations(run.id)
        self._measure(corpus, snapshot, run, rows)
        task.status = RunStatus.COMPLETED
        task.progress = 1
        run.status = RunStatus.COMPLETED
        run.progress = 1
        run.completed_at = datetime.now(UTC)
        self.session.commit()
        return run

    def _utterances(self, revision: MessageRevision, language: str) -> list[Utterance]:
        existing = self.session.scalars(
            select(Utterance).where(Utterance.revision_id == revision.id)
        ).all()
        if existing:
            return list(existing)
        output: list[Utterance] = []
        for start, end, exact in sentence_spans(revision.text):
            utterance = Utterance(
                revision_id=revision.id,
                start_codepoint=start,
                end_codepoint=end,
                exact_text=exact,
                exact_text_hash=text_hash(exact),
                language=language,
            )
            self.session.add(utterance)
            output.append(utterance)
        self.session.flush()
        return output

    def _span(self, revision: MessageRevision, utterance: Utterance) -> Span:
        existing = self.session.scalar(
            select(Span).where(
                Span.revision_id == revision.id,
                Span.start_codepoint == utterance.start_codepoint,
                Span.end_codepoint == utterance.end_codepoint,
            )
        )
        if existing:
            return existing
        span = Span(
            revision_id=revision.id,
            start_codepoint=utterance.start_codepoint,
            end_codepoint=utterance.end_codepoint,
            exact_text=utterance.exact_text,
            exact_text_hash=utterance.exact_text_hash,
        )
        self.session.add(span)
        self.session.flush()
        return span

    def _dialogue_acts(self, text: str) -> list[str]:
        labels = [
            label
            for label in ("QUESTION", "PROPOSE", "AGREE", "DISAGREE", "COMMIT", "ACKNOWLEDGE")
            if PATTERNS[label].search(text)
        ]
        return labels or ["ASSERT"]

    def _grounding(self, text: str) -> str | None:
        if PATTERNS["CLARIFICATION_REQUESTED"].search(text):
            return "CLARIFICATION_REQUESTED"
        if PATTERNS["REPAIRED"].search(text):
            return "REPAIRED"
        if PATTERNS["ACKNOWLEDGE"].search(text):
            return "ACKNOWLEDGED"
        return None

    @staticmethod
    def _is_proposition(text: str, acts: list[str]) -> bool:
        return len(text.split()) >= 3 and acts != ["ACKNOWLEDGE"] and "QUESTION" not in acts

    def _annotation(
        self,
        snapshot_id: str,
        run_id: str,
        object_type: str,
        object_id: str,
        kind: str,
        value: dict[str, Any],
        span: Span,
        confidence: float,
    ) -> Annotation:
        evidence = [
            {
                "object_type": "span",
                "object_id": span.id,
                "revision_id": span.revision_id,
                "start_codepoint": span.start_codepoint,
                "end_codepoint": span.end_codepoint,
                "exact_text_hash": span.exact_text_hash,
            }
        ]
        return Annotation(
            snapshot_id=snapshot_id,
            run_id=run_id,
            object_type=object_type,
            object_id=object_id,
            kind=kind,
            value=value,
            evidence=evidence,
            status="provisional",
            raw_confidence=confidence,
            calibrated_confidence=None,
            alternatives=[],
            provenance={
                "corpus_snapshot_id": snapshot_id,
                "ontology_version": self.settings.ontology_version,
                "codebook_version": self.codebook_version,
                "codebook_artifact_hash": self.codebook_hash,
                "pipeline_version": self.settings.pipeline_version,
                "model_provider": "deterministic",
                "model": self.model_name,
                "analysis_run_id": run_id,
                "created_at": datetime.now(UTC).isoformat(),
            },
        )

    def _epistemic_observation(
        self,
        snapshot_id: str,
        run_id: str,
        holder_id: str,
        proposition: PropositionMention,
        span: Span,
        text: str,
    ) -> None:
        label = "UNCERTAIN" if PATTERNS["UNCERTAIN"].search(text) else "COMMITTED"
        commitment = 0.45 if label == "UNCERTAIN" else 0.78
        annotation = self._annotation(
            snapshot_id,
            run_id,
            "proposition",
            proposition.id,
            "epistemic_state",
            {
                "label": label,
                "holder_id": holder_id,
                "proposition_id": proposition.id,
                "polarity": "accept",
                "commitment": commitment,
                "certainty": commitment,
                "evidential_basis": "unspecified",
            },
            span,
            confidence=0.86,
        )
        self.session.add(annotation)
        self.session.flush()
        self.session.add(
            EpistemicObservation(
                annotation_id=annotation.id,
                holder_id=holder_id,
                proposition_id=proposition.id,
                polarity="accept",
                commitment=commitment,
                certainty=commitment,
                evidential_basis="unspecified",
            )
        )
        self._derive("span", span.id, "annotation", annotation.id, "DERIVED_FROM", run_id)

    def _stance_observations(
        self,
        snapshot_id: str,
        run_id: str,
        rows: list[tuple[Message, MessageRevision, Participant | None]],
        proposition_by_message: dict[str, list[PropositionMention]],
        _message_lookup: dict[str, Message],
        external_lookup: dict[tuple[str, str], Message],
    ) -> None:
        for message, revision, _participant in rows:
            if not message.sender_id or not message.reply_to_external_id:
                continue
            target_message = external_lookup.get(
                (message.conversation_id, message.reply_to_external_id)
            )
            if not target_message or not proposition_by_message.get(target_message.id):
                continue
            position = None
            strength = 0.0
            if PATTERNS["AGREE"].search(revision.text):
                position, strength = "support", 0.8
            elif PATTERNS["DISAGREE"].search(revision.text):
                position, strength = "oppose", -0.8
            if position is None:
                continue
            span = self.session.scalar(select(Span).where(Span.revision_id == revision.id))
            if span is None:
                continue
            candidates = proposition_by_message[target_message.id]
            if len(candidates) != 1:
                self._unresolved_stance(
                    snapshot_id, run_id, message, span, position, strength, candidates
                )
                continue
            target = candidates[0]
            annotation = self._annotation(
                snapshot_id,
                run_id,
                "message",
                message.id,
                "stance",
                {
                    "position": position,
                    "holder_id": message.sender_id,
                    "target_type": "proposition",
                    "target_id": target.id,
                    "strength": strength,
                },
                span,
                confidence=0.84,
            )
            self.session.add(annotation)
            self.session.flush()
            self.session.add(
                StanceObservation(
                    annotation_id=annotation.id,
                    holder_id=message.sender_id,
                    target_type="proposition",
                    target_id=target.id,
                    position=position,
                    strength=strength,
                    certainty=0.8,
                    target_weight=1.0,
                    resolution_status="RESOLVED",
                )
            )
            self._derive("span", span.id, "annotation", annotation.id, "DERIVED_FROM", run_id)

    def _unresolved_stance(
        self,
        snapshot_id: str,
        run_id: str,
        message: Message,
        span: Span,
        position: str,
        strength: float,
        candidates: list[PropositionMention],
    ) -> None:
        annotation = self._annotation(
            snapshot_id,
            run_id,
            "message",
            message.id,
            "stance",
            {
                "position": position,
                "holder_id": message.sender_id,
                "resolution_status": "ABSTAIN",
                "candidate_target_ids": [candidate.id for candidate in candidates],
                "strength": strength,
            },
            span,
            confidence=0.45,
        )
        annotation.status = "disputed"
        annotation.alternatives = [
            {"target_id": candidate.id, "weight": 1 / len(candidates)} for candidate in candidates
        ]
        self.session.add(annotation)
        self.session.flush()
        self._derive("span", span.id, "annotation", annotation.id, "DERIVED_FROM", run_id)

    def _derive(
        self,
        source_type: str,
        source_id: str,
        target_type: str,
        target_id: str,
        relation: str,
        run_id: str,
    ) -> None:
        self.session.add(
            DerivationEdge(
                source_type=source_type,
                source_id=source_id,
                target_type=target_type,
                target_id=target_id,
                relation=relation,
                run_id=run_id,
            )
        )

    def _connect_annotations(self, run_id: str) -> None:
        annotations = self.session.scalars(select(Annotation).where(Annotation.run_id == run_id))
        for annotation in annotations:
            for evidence in annotation.evidence:
                source_id = evidence.get("object_id")
                source_type = evidence.get("object_type")
                if source_id and source_type:
                    existing = self.session.scalar(
                        select(DerivationEdge.id).where(
                            DerivationEdge.source_type == source_type,
                            DerivationEdge.source_id == source_id,
                            DerivationEdge.target_type == "annotation",
                            DerivationEdge.target_id == annotation.id,
                            DerivationEdge.relation == "DERIVED_FROM",
                            DerivationEdge.run_id == run_id,
                        )
                    )
                    if existing is None:
                        self._derive(
                            source_type,
                            source_id,
                            "annotation",
                            annotation.id,
                            "DERIVED_FROM",
                            run_id,
                        )

    def _measure(
        self,
        corpus: Corpus,
        snapshot: CorpusSnapshot,
        run: AnalysisRun,
        rows: list[tuple[Message, MessageRevision, Participant | None]],
    ) -> None:
        registry = foundational_registry()
        context = MeasurementContext(
            session=self.session,
            corpus_id=corpus.id,
            snapshot_id=snapshot.id,
            run_id=run.id,
        )
        participation_result = registry.execute("participation-share@1", context)
        registry.execute("reply-reciprocity@1", context)
        shares = participation_result.result.get("estimate", {})
        top = max(shares.items(), key=lambda item: item[1], default=(None, 0))
        if top[0]:
            participant = self.session.get(Participant, top[0])
            finding = Finding(
                run_id=run.id,
                claim=(
                    f"{participant.display_name if participant else 'Участник'} "
                    f"написал(а) наибольшую долю сообщений: {top[1]:.0%}."
                ),
                epistemic_level=EpistemicLevel.MEASUREMENT,
                causal_status=CausalStatus.DESCRIPTIVE,
                supporting_evidence=[],
                counterevidence=[],
                alternative_explanations=["Доля сообщений не является мерой влияния или власти."],
                sensitivity_results=[],
                dependency_dag_root=participation_result.id,
                provenance={"snapshot_id": snapshot.id, "run_id": run.id},
            )
            self.session.add(finding)
            self.session.flush()
            self._derive(
                "measurement",
                participation_result.id,
                "finding",
                finding.id,
                "SUPPORTS_FINDING",
                run.id,
            )
        return

        definitions = [
            ("participation-share@1", "Распределение участия", "participant"),
            ("reply-reciprocity@1", "Взаимность ответов", "dyad"),
        ]
        for key, title, unit in definitions:
            if self.session.get(MeasurementDefinition, key) is None:
                self.session.add(
                    MeasurementDefinition(
                        id=key,
                        version="1",
                        title=title,
                        description=(
                            "Детерминированное базовое измерение "
                            "с видимым числителем и знаменателем."
                        ),
                        unit_of_analysis=unit,
                        manifest={"provisional": False, "causal": False},
                    )
                )
        self.session.flush()
        counts = Counter(message.sender_id for message, _, _ in rows if message.sender_id)
        total = sum(counts.values())
        shares = (
            {participant_id: count / total for participant_id, count in counts.items()}
            if total
            else {}
        )
        entropy = -sum(value * math.log(value, 2) for value in shares.values() if value)
        participation_result = MeasurementResult(
            definition_id="participation-share@1",
            run_id=run.id,
            subject_type="corpus",
            subject_id=corpus.id,
            result={
                "estimate": shares,
                "entropy_bits": entropy,
                "numerator": counts,
                "denominator": total,
                "sample_size": total,
                "uncertainty": {"method": "descriptive", "explanation": []},
                "provenance": {"snapshot_id": snapshot.id, "run_id": run.id},
            },
            provenance={"snapshot_id": snapshot.id, "run_id": run.id},
        )
        self.session.add(participation_result)
        self.session.flush()
        for message, _revision, _participant in rows:
            self._derive(
                "message",
                message.id,
                "measurement",
                participation_result.id,
                "USES_OBSERVATION",
                run.id,
            )
        replies = self.session.execute(
            select(Message.sender_id, Message.id, ResponseRelation.target_message_id)
            .join(ResponseRelation, ResponseRelation.source_message_id == Message.id)
            .join(SnapshotMessageRevision, SnapshotMessageRevision.message_id == Message.id)
            .where(
                SnapshotMessageRevision.snapshot_id == snapshot.id,
                ResponseRelation.explicit.is_(True),
                ResponseRelation.relation_type == "REPLIES_TO",
            )
        ).all()
        target_sender = {message.id: message.sender_id for message, _, _ in rows}
        directed = Counter(
            (sender, target_sender.get(target_id))
            for sender, _source_id, target_id in replies
            if sender and target_sender.get(target_id) and sender != target_sender.get(target_id)
        )
        reciprocated = sum(
            min(count, directed.get((target, source), 0))
            for (source, target), count in directed.items()
        )
        reply_total = sum(directed.values())
        reciprocity = reciprocated / reply_total if reply_total else 0
        reciprocity_result = MeasurementResult(
            definition_id="reply-reciprocity@1",
            run_id=run.id,
            subject_type="corpus",
            subject_id=corpus.id,
            result={
                "estimate": reciprocity,
                "numerator": reciprocated,
                "denominator": reply_total,
                "sample_size": reply_total,
                "directed_edges": {
                    f"{source}->{target}": count for (source, target), count in directed.items()
                },
                "uncertainty": {
                    "method": "descriptive",
                    "explanation": ["Только явные ответы"],
                },
                "provenance": {"snapshot_id": snapshot.id, "run_id": run.id},
            },
            provenance={"snapshot_id": snapshot.id, "run_id": run.id},
        )
        self.session.add(reciprocity_result)
        self.session.flush()
        response_ids = self.session.scalars(
            select(ResponseRelation.id)
            .join(Message, Message.id == ResponseRelation.source_message_id)
            .join(SnapshotMessageRevision, SnapshotMessageRevision.message_id == Message.id)
            .where(
                SnapshotMessageRevision.snapshot_id == snapshot.id,
                ResponseRelation.explicit.is_(True),
                ResponseRelation.relation_type == "REPLIES_TO",
            )
        )
        for response_id in response_ids:
            self._derive(
                "response_relation",
                response_id,
                "measurement",
                reciprocity_result.id,
                "USES_OBSERVATION",
                run.id,
            )
        top = max(shares.items(), key=lambda item: item[1], default=(None, 0))
        if top[0]:
            participant = self.session.get(Participant, top[0])
            evidence_message = next(
                (message for message, _, _ in rows if message.sender_id == top[0]), None
            )
            evidence = (
                [{"object_type": "message", "object_id": evidence_message.id}]
                if evidence_message
                else []
            )
            measurement = self.session.scalar(
                select(MeasurementResult)
                .where(MeasurementResult.run_id == run.id)
                .order_by(MeasurementResult.created_at)
            )
            finding = Finding(
                run_id=run.id,
                claim=(
                    f"{participant.display_name if participant else 'Участник'} "
                    f"написал(а) наибольшую долю сообщений: {top[1]:.0%}."
                ),
                epistemic_level=EpistemicLevel.MEASUREMENT,
                causal_status=CausalStatus.DESCRIPTIVE,
                supporting_evidence=evidence,
                counterevidence=[],
                alternative_explanations=["Доля сообщений не является мерой влияния или власти."],
                sensitivity_results=[],
                dependency_dag_root=(measurement.id if measurement else "participation-share@1"),
                provenance={"snapshot_id": snapshot.id, "run_id": run.id},
            )
            self.session.add(finding)
            self.session.flush()
            if measurement:
                self._derive(
                    "measurement",
                    measurement.id,
                    "finding",
                    finding.id,
                    "SUPPORTS_FINDING",
                    run.id,
                )


def select_conversation_ids(corpus_id: str):
    from .models import Conversation

    return select(Conversation.id).where(Conversation.corpus_id == corpus_id)
