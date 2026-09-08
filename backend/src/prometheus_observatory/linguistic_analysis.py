from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from datetime import UTC, datetime
from typing import Any

import pymorphy3
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .codebooks import release_identity
from .config import get_settings
from .model_gateway import (
    EvidenceItem,
    LocalLinguisticAnalysisAdapter,
    ModelPolicy,
    ModelRouter,
    TaskCapabilityRegistry,
)
from .models import (
    AnalysisRun,
    AnalysisTask,
    Annotation,
    Corpus,
    CorpusSnapshot,
    DependencyFingerprint,
    DerivationEdge,
    Message,
    MessageRevision,
    Participant,
    SnapshotMessageRevision,
    new_id,
)
from .ontology import PrivacyPolicy
from .text import normalize_text

ANALYSIS_VERSION = "linguistic-features-ru@0.1.0"
TOKEN_PATTERN = re.compile(r"[\w-]+|[^\w\s]", re.UNICODE)
WORD_PATTERN = re.compile(r"^[\w-]+$", re.UNICODE)
PRONOUNS = {
    "он",
    "она",
    "оно",
    "они",
    "его",
    "её",
    "ее",
    "их",
    "это",
    "этот",
    "эта",
    "эти",
    "тот",
    "та",
    "те",
}
MODALS = {
    "мочь",
    "должный",
    "нужно",
    "необходимо",
    "следовать",
    "хотеть",
    "возможно",
    "вероятно",
}
UD_POS = {
    "NOUN": "NOUN",
    "ADJF": "ADJ",
    "ADJS": "ADJ",
    "COMP": "ADJ",
    "VERB": "VERB",
    "INFN": "VERB",
    "PRTF": "VERB",
    "PRTS": "VERB",
    "GRND": "VERB",
    "NUMR": "NUM",
    "ADVB": "ADV",
    "NPRO": "PRON",
    "PRED": "ADV",
    "PREP": "ADP",
    "CONJ": "CCONJ",
    "PRCL": "PART",
    "INTJ": "INTJ",
}
ENTITY_GRAMMEMES = {
    "Name": "PERSON",
    "Surn": "PERSON",
    "Patr": "PERSON",
    "Geox": "LOCATION",
    "Orgn": "ORGANIZATION",
    "Trad": "PRODUCT",
}


class LinguisticAnalysisService:
    """Persist interpretable Russian linguistic observations without generative models."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()
        self.morph = pymorphy3.MorphAnalyzer()

    def create(
        self,
        corpus_id: str,
        *,
        include_local_parser: bool = True,
        execute: bool = True,
    ) -> AnalysisRun:
        corpus = self.session.get(Corpus, corpus_id)
        if corpus is None:
            raise LookupError("corpus not found")
        snapshot = self._latest_snapshot(corpus_id)
        codebook_release, codebook_hash = release_identity(
            self.session, "linguistic-features-ru", "0.1.0"
        )
        configuration = {
            "analysis_version": ANALYSIS_VERSION,
            "codebook_release": codebook_release,
            "codebook_artifact_hash": codebook_hash,
            "batch_size": self.settings.linguistic_analysis_batch_size,
            "include_local_parser": include_local_parser,
            "local_parser": {
                "base_url": self.settings.local_linguistic_base_url,
                "model": self.settings.local_linguistic_model,
                "model_revision": self.settings.local_linguistic_revision,
                "tasks": ["dependency", "ner", "coreference", "srl"],
            },
            "accepted_entity_links": False,
            "score_semantics": "uncalibrated_heuristic",
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "snapshot_id": snapshot.id,
                    "manifest_hash": snapshot.manifest_hash,
                    **configuration,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        existing = next(
            (
                run
                for run in self.session.scalars(
                    select(AnalysisRun).where(
                        AnalysisRun.snapshot_id == snapshot.id,
                        AnalysisRun.run_type == "linguistic-analysis",
                    )
                )
                if run.configuration.get("fingerprint") == fingerprint
            ),
            None,
        )
        if existing is not None:
            if execute and existing.status in {"pending", "failed", "cancelled"}:
                return self.resume(existing.id)
            return existing
        run = AnalysisRun(
            id=new_id(),
            snapshot_id=snapshot.id,
            run_type="linguistic-analysis",
            status="pending",
            progress=0,
            configuration={**configuration, "fingerprint": fingerprint},
        )
        self.session.add(run)
        self.session.flush()
        for task_key in ("morphosyntax", "entity_tracking", "local_parser"):
            task = AnalysisTask(
                id=new_id(),
                run_id=run.id,
                task_key=task_key,
                status="pending",
                progress=0,
                idempotency_key=f"{run.id}:{task_key}",
                checkpoint={"offset": 0, "mention_history": []}
                if task_key == "morphosyntax"
                else {},
            )
            self.session.add(task)
            self.session.flush()
            self.session.add(
                DependencyFingerprint(
                    id=new_id(),
                    task_id=task.id,
                    dependency_type="linguistic_configuration",
                    dependency_key=task_key,
                    fingerprint=fingerprint,
                )
            )
        self.session.commit()
        return self.execute(run.id) if execute else run

    def execute(self, run_id: str) -> AnalysisRun:
        run = self._run(run_id)
        if run.status in {"completed", "cancelled"}:
            return run
        run.status = "running"
        run.started_at = run.started_at or datetime.now(UTC)
        run.error = None
        self.session.commit()
        try:
            self._run_baseline(run)
            if self._is_cancelled(run.id):
                return self._run(run.id)
            try:
                self._run_local_parser(run)
            except Exception as parser_error:
                self.session.rollback()
                run = self._run(run.id)
                task = self._tasks(run.id)["local_parser"]
                task.status = "failed"
                task.error = str(parser_error)
                run.configuration = {
                    **run.configuration,
                    "local_parser_warning": str(parser_error),
                }
                self.session.commit()
            run = self._run(run.id)
            if run.status != "cancelled":
                run.status = "completed"
                run.progress = 1
                run.completed_at = datetime.now(UTC)
                self.session.commit()
            return run
        except Exception as error:
            self.session.rollback()
            run = self._run(run_id)
            run.status = "failed"
            run.error = str(error)
            self.session.commit()
            raise

    def cancel(self, run_id: str) -> AnalysisRun:
        run = self._run(run_id)
        if run.status != "completed":
            run.status = "cancelled"
            run.completed_at = datetime.now(UTC)
            self.session.commit()
        return run

    def resume(self, run_id: str) -> AnalysisRun:
        run = self._run(run_id)
        if run.status == "completed":
            return run
        expected = run.configuration.get("fingerprint")
        fingerprints = list(
            self.session.scalars(
                select(DependencyFingerprint.fingerprint)
                .join(AnalysisTask, AnalysisTask.id == DependencyFingerprint.task_id)
                .where(AnalysisTask.run_id == run.id)
            )
        )
        if not fingerprints or any(item != expected for item in fingerprints):
            raise ValueError("analysis dependency fingerprint changed; create a new run")
        run.status = "pending"
        run.completed_at = None
        self.session.commit()
        return self.execute(run.id)

    def run_payload(self, run_id: str) -> dict[str, Any]:
        run = self._run(run_id)
        return {
            "id": run.id,
            "snapshot_id": run.snapshot_id,
            "run_type": run.run_type,
            "status": run.status,
            "progress": run.progress,
            "configuration": run.configuration,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "error": run.error,
            "tasks": [
                {
                    "id": task.id,
                    "task_key": task.task_key,
                    "status": task.status,
                    "progress": task.progress,
                    "checkpoint": task.checkpoint,
                    "error": task.error,
                }
                for task in self._tasks(run.id).values()
            ],
        }

    def message_analysis(
        self, corpus_id: str, message_id: str, *, run_id: str | None = None
    ) -> dict[str, Any]:
        corpus = self.session.get(Corpus, corpus_id)
        if corpus is None:
            raise LookupError("corpus not found")
        run = self._analysis_run(corpus_id, run_id)
        membership = self.session.scalar(
            select(SnapshotMessageRevision).where(
                SnapshotMessageRevision.snapshot_id == run.snapshot_id,
                SnapshotMessageRevision.message_id == message_id,
            )
        )
        if membership is None:
            raise LookupError("message is not present in the analysis snapshot")
        annotations = list(
            self.session.scalars(
                select(Annotation)
                .where(
                    Annotation.run_id == run.id,
                    Annotation.object_id == message_id,
                    Annotation.kind.in_(
                        [
                            "linguistic_features",
                            "entity_mention",
                            "coreference_candidates",
                            "linguistic_parser_output",
                        ]
                    ),
                )
                .order_by(Annotation.created_at, Annotation.id)
            )
        )
        return {
            "run": self.run_payload(run.id),
            "message_id": message_id,
            "revision_id": membership.revision_id,
            "annotations": [
                {
                    "id": annotation.id,
                    "kind": annotation.kind,
                    "value": annotation.value,
                    "evidence": annotation.evidence,
                    "status": annotation.status,
                    "raw_confidence": annotation.raw_confidence,
                    "calibrated_confidence": annotation.calibrated_confidence,
                    "alternatives": annotation.alternatives,
                    "provenance": annotation.provenance,
                }
                for annotation in annotations
            ],
            "guardrail": (
                "Entity and coreference links are provisional textual hypotheses. "
                "Missing parser output means unavailable analysis, not absence."
            ),
        }

    def _run_baseline(self, run: AnalysisRun) -> None:
        tasks = self._tasks(run.id)
        morph_task = tasks["morphosyntax"]
        entity_task = tasks["entity_tracking"]
        if morph_task.status == entity_task.status == "completed":
            return
        morph_task.status = entity_task.status = "running"
        checkpoint = morph_task.checkpoint or {"offset": 0, "mention_history": []}
        offset = int(checkpoint.get("offset", 0))
        history: deque[dict[str, Any]] = deque(checkpoint.get("mention_history", []), maxlen=200)
        total = (
            self.session.scalar(
                select(func.count(SnapshotMessageRevision.id)).where(
                    SnapshotMessageRevision.snapshot_id == run.snapshot_id
                )
            )
            or 0
        )
        participants = list(
            self.session.scalars(
                select(Participant).where(
                    Participant.corpus_id == self._snapshot(run.snapshot_id).corpus_id
                )
            )
        )
        batch_size = int(run.configuration["batch_size"])
        while offset < total:
            if self._is_cancelled(run.id):
                return
            rows = self._rows(run.snapshot_id, offset, batch_size)
            if not rows:
                break
            for message, revision in rows:
                tokens = self._tokens(revision.text)
                features = self._feature_payload(tokens)
                annotation = self._annotation(
                    run,
                    message,
                    revision,
                    "linguistic_features",
                    features,
                    0,
                    len(revision.text),
                    "pymorphy3-baseline",
                )
                self.session.add(annotation)
                self.session.flush()
                self._derive(revision.id, annotation.id, run.id, "DERIVES_LINGUISTIC_FEATURES")
                mentions = self._mentions(message, revision, tokens, participants)
                current_history: list[dict[str, Any]] = []
                for mention in mentions:
                    mention_annotation = self._annotation(
                        run,
                        message,
                        revision,
                        "entity_mention",
                        mention,
                        mention["start_codepoint"],
                        mention["end_codepoint"],
                        "pymorphy3-entity-baseline",
                    )
                    self.session.add(mention_annotation)
                    self.session.flush()
                    mention["annotation_id"] = mention_annotation.id
                    self._derive(
                        revision.id,
                        mention_annotation.id,
                        run.id,
                        "DERIVES_ENTITY_MENTION",
                    )
                    candidates = self._coreference_candidates(mention, message, history)
                    if candidates:
                        coreference = self._annotation(
                            run,
                            message,
                            revision,
                            "coreference_candidates",
                            {
                                "mention_id": mention["mention_id"],
                                "mention_annotation_id": mention_annotation.id,
                                "accepted_target": None,
                                "score_semantics": "uncalibrated_heuristic",
                            },
                            mention["start_codepoint"],
                            mention["end_codepoint"],
                            "recency-morph-agreement@0.1.0",
                            alternatives=[{"value": candidate} for candidate in candidates],
                        )
                        self.session.add(coreference)
                        self.session.flush()
                        self._derive(
                            revision.id,
                            coreference.id,
                            run.id,
                            "PROPOSES_COREFERENCE_CANDIDATES",
                        )
                    current_history.append(
                        {
                            "conversation_id": message.conversation_id,
                            "message_id": message.id,
                            "revision_id": revision.id,
                            "sent_at": message.resolved_timestamp.isoformat(),
                            **mention,
                        }
                    )
                history.extend(current_history)
            offset += len(rows)
            progress = offset / total if total else 1
            morph_task.checkpoint = {
                "offset": offset,
                "mention_history": list(history),
            }
            morph_task.progress = entity_task.progress = progress
            run.progress = progress * 0.8
            self.session.commit()
        morph_task.status = entity_task.status = "completed"
        morph_task.progress = entity_task.progress = 1
        self.session.commit()

    def _run_local_parser(self, run: AnalysisRun) -> None:
        task = self._tasks(run.id)["local_parser"]
        if task.status in {"completed", "unavailable", "disabled"}:
            return
        if not run.configuration.get("include_local_parser"):
            task.status = "disabled"
            task.progress = 1
            self.session.commit()
            return
        parser = run.configuration["local_parser"]
        if not parser.get("base_url"):
            task.status = "unavailable"
            task.progress = 1
            task.error = "PROMETHEUS_LOCAL_LINGUISTIC_BASE_URL is not configured"
            self.session.commit()
            return
        if parser.get("model_revision") == "unversioned":
            task.status = "unavailable"
            task.progress = 1
            task.error = "PROMETHEUS_LOCAL_LINGUISTIC_REVISION must pin the parser artifact"
            self.session.commit()
            return
        adapter = LocalLinguisticAnalysisAdapter(
            base_url=parser["base_url"],
            model=parser["model"],
            model_revision=parser["model_revision"],
        )
        registry = TaskCapabilityRegistry()
        registry.register("russian_linguistic_analysis", minimum_context=1024)
        router = ModelRouter(self.session, registry)
        task.status = "running"
        offset = int((task.checkpoint or {}).get("offset", 0))
        total = (
            self.session.scalar(
                select(func.count(SnapshotMessageRevision.id)).where(
                    SnapshotMessageRevision.snapshot_id == run.snapshot_id
                )
            )
            or 0
        )
        batch_size = min(32, int(run.configuration["batch_size"]))
        corpus_id = self._snapshot(run.snapshot_id).corpus_id
        while offset < total:
            if self._is_cancelled(run.id):
                return
            rows = self._rows(run.snapshot_id, offset, batch_size)
            result = router.analyze_linguistics(
                corpus_id=corpus_id,
                run_id=run.id,
                task="russian_linguistic_analysis",
                adapter=adapter,
                items=[
                    EvidenceItem(evidence_id=revision.id, text=revision.text)
                    for _message, revision in rows
                ],
                policy=ModelPolicy(
                    privacy_policy=PrivacyPolicy.LOCAL_ONLY,
                    max_cost=0,
                    max_input_tokens=8192,
                    preferred_language="ru",
                    redact_pii=False,
                ),
                reason="local dependency, NER, coreference, and SRL analysis",
            )
            for (message, revision), analysis in zip(rows, result.analyses, strict=True):
                self._validate_parser_analysis(revision.text, analysis)
                annotation = self._annotation(
                    run,
                    message,
                    revision,
                    "linguistic_parser_output",
                    {
                        "tokens": analysis["tokens"],
                        "dependencies": analysis["dependencies"],
                        "entities": analysis["entities"],
                        "semantic_roles": analysis["semantic_roles"],
                        "coreference": analysis.get("coreference", []),
                        "capability_status": {
                            "dependencies": "available",
                            "named_entities": "available",
                            "coreference": "available",
                            "semantic_roles": "available",
                        },
                    },
                    0,
                    len(revision.text),
                    "local-pinned-linguistic-parser",
                    model=adapter.model,
                    model_revision=adapter.model_revision,
                )
                self.session.add(annotation)
                self.session.flush()
                self._derive(revision.id, annotation.id, run.id, "DERIVES_PARSER_ANALYSIS")
            offset += len(rows)
            task.checkpoint = {"offset": offset, "total": total}
            task.progress = offset / total if total else 1
            run.progress = 0.8 + task.progress * 0.2
            self.session.commit()
        task.status = "completed"
        task.progress = 1
        self.session.commit()

    def _tokens(self, text: str) -> list[dict[str, Any]]:
        normalized = normalize_text(text)
        tokens: list[dict[str, Any]] = []
        for index, match in enumerate(TOKEN_PATTERN.finditer(normalized), start=1):
            surface = match.group(0)
            if WORD_PATTERN.match(surface):
                parse = self.morph.parse(surface)[0]
                grammemes = sorted(str(item) for item in parse.tag.grammemes)
                pos = UD_POS.get(parse.tag.POS, "X") if parse.tag.POS else "X"
                lemma = parse.normal_form
            else:
                grammemes = []
                pos = "PUNCT"
                lemma = surface
            tokens.append(
                {
                    "id": index,
                    "text": surface,
                    "lemma": lemma,
                    "upos": pos,
                    "grammemes": grammemes,
                    "start_codepoint": match.start(),
                    "end_codepoint": match.end(),
                }
            )
        return tokens

    @staticmethod
    def _feature_payload(tokens: list[dict[str, Any]]) -> dict[str, Any]:
        noun_phrases: list[dict[str, Any]] = []
        current: list[dict[str, Any]] = []
        for token in [*tokens, {"upos": "PUNCT"}]:
            if token["upos"] in {"ADJ", "NOUN", "PROPN"}:
                current.append(token)
            else:
                if current and any(item["upos"] in {"NOUN", "PROPN"} for item in current):
                    noun_phrases.append(
                        {
                            "start_codepoint": current[0]["start_codepoint"],
                            "end_codepoint": current[-1]["end_codepoint"],
                            "token_ids": [item["id"] for item in current],
                        }
                    )
                current = []
        negation_scopes = []
        for index, token in enumerate(tokens):
            if token["lemma"] not in {"не", "ни"}:
                continue
            governed = next(
                (item for item in tokens[index + 1 : index + 4] if item["upos"] != "PUNCT"),
                None,
            )
            negation_scopes.append(
                {
                    "marker_token_id": token["id"],
                    "governed_token_id": governed["id"] if governed else None,
                    "status": "heuristic_scope",
                }
            )
        modals = [
            {"token_id": token["id"], "lemma": token["lemma"]}
            for token in tokens
            if token["lemma"] in MODALS
        ]
        return {
            "tokens": tokens,
            "noun_phrases": noun_phrases,
            "negation_scopes": negation_scopes,
            "modals": modals,
            "capability_status": {
                "tokens": "available",
                "lemmas": "available",
                "part_of_speech": "available",
                "morphology": "available",
                "noun_phrases": "heuristic",
                "negation_scope": "heuristic",
                "dependencies": "unavailable_without_local_parser",
                "named_entities": "heuristic",
                "semantic_roles": "unavailable_without_local_parser",
            },
        }

    def _mentions(
        self,
        message: Message,
        revision: MessageRevision,
        tokens: list[dict[str, Any]],
        participants: list[Participant],
    ) -> list[dict[str, Any]]:
        found: dict[tuple[int, int], dict[str, Any]] = {}
        for participant in participants:
            name = participant.display_name.strip()
            if not name:
                continue
            for match in re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", revision.text, re.I):
                found[(match.start(), match.end())] = self._mention(
                    revision,
                    match.start(),
                    match.end(),
                    "PERSON",
                    "participant_display_name",
                    participant_id=participant.id,
                )
        for token in tokens:
            grammemes = set(token["grammemes"])
            entity_type = next(
                (kind for marker, kind in ENTITY_GRAMMEMES.items() if marker in grammemes), None
            )
            if entity_type and (token["start_codepoint"], token["end_codepoint"]) not in found:
                found[(token["start_codepoint"], token["end_codepoint"])] = self._mention(
                    revision,
                    token["start_codepoint"],
                    token["end_codepoint"],
                    entity_type,
                    "morphological_grammeme",
                    grammemes=token["grammemes"],
                )
            if token["lemma"] in PRONOUNS:
                found[(token["start_codepoint"], token["end_codepoint"])] = self._mention(
                    revision,
                    token["start_codepoint"],
                    token["end_codepoint"],
                    "PRONOUN",
                    "pronoun_inventory",
                    grammemes=token["grammemes"],
                )
        return sorted(
            found.values(), key=lambda item: (item["start_codepoint"], item["end_codepoint"])
        )

    @staticmethod
    def _mention(
        revision: MessageRevision,
        start: int,
        end: int,
        entity_type: str,
        basis: str,
        *,
        participant_id: str | None = None,
        grammemes: list[str] | None = None,
    ) -> dict[str, Any]:
        exact = revision.text[start:end]
        return {
            "mention_id": hashlib.sha256(
                f"{revision.id}:{start}:{end}:{exact}".encode()
            ).hexdigest()[:24],
            "text": exact,
            "normalized": exact.casefold(),
            "entity_type": entity_type,
            "source_basis": basis,
            "participant_id": participant_id,
            "grammemes": grammemes or [],
            "start_codepoint": start,
            "end_codepoint": end,
            "resolution_status": "candidate_only",
        }

    @staticmethod
    def _coreference_candidates(
        mention: dict[str, Any], message: Message, history: deque[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        mention_grammemes = set(mention.get("grammemes", []))
        for distance, previous in enumerate(reversed(history), start=1):
            if previous["conversation_id"] != message.conversation_id:
                continue
            same_surface = previous["normalized"] == mention["normalized"]
            pronoun = mention["entity_type"] == "PRONOUN"
            if pronoun and previous["entity_type"] == "PRONOUN":
                continue
            agreement = bool(
                mention_grammemes
                & set(previous.get("grammemes", []))
                & {"masc", "femn", "neut", "sing", "plur"}
            )
            if not same_surface and not pronoun:
                continue
            score = (
                (0.9 if same_surface else 0.55)
                + (0.1 if agreement else 0)
                - min(distance, 40) / 200
            )
            candidates.append(
                {
                    "target_mention_id": previous["mention_id"],
                    "target_annotation_id": previous["annotation_id"],
                    "target_message_id": previous["message_id"],
                    "target_revision_id": previous["revision_id"],
                    "raw_score": max(0, round(score, 6)),
                    "basis": "same_surface" if same_surface else "recency_morph_agreement",
                }
            )
            if len(candidates) == 5:
                break
        if mention.get("participant_id"):
            candidates.insert(
                0,
                {
                    "target_type": "participant",
                    "target_id": mention["participant_id"],
                    "raw_score": 1,
                    "basis": "source_participant_display_name",
                },
            )
        return candidates[:5]

    @staticmethod
    def _validate_parser_analysis(text: str, analysis: dict[str, Any]) -> None:
        token_ids: set[int] = set()
        for token in analysis["tokens"]:
            required = {"id", "text", "start_codepoint", "end_codepoint"}
            if not required <= set(token):
                raise ValueError("parser token is missing identity or exact offsets")
            start, end = token["start_codepoint"], token["end_codepoint"]
            if not 0 <= start < end <= len(text) or text[start:end] != token["text"]:
                raise ValueError("parser token offsets do not reconstruct source text")
            token_ids.add(token["id"])
        if len(token_ids) != len(analysis["tokens"]):
            raise ValueError("parser token IDs must be unique")
        for dependency in analysis["dependencies"]:
            if dependency.get("dependent_id") not in token_ids:
                raise ValueError("dependency dependent does not reference a parser token")
            if dependency.get("head_id") not in token_ids | {0}:
                raise ValueError("dependency head does not reference a parser token or root")
            if not dependency.get("relation"):
                raise ValueError("dependency relation is required")
        for entity in analysis["entities"]:
            start, end = entity.get("start_codepoint"), entity.get("end_codepoint")
            if not isinstance(start, int) or not isinstance(end, int):
                raise ValueError("parser entity requires exact offsets")
            if not 0 <= start < end <= len(text) or text[start:end] != entity.get("text"):
                raise ValueError("parser entity offsets do not reconstruct source text")
            if not entity.get("entity_type"):
                raise ValueError("parser entity type is required")
        for frame in analysis["semantic_roles"]:
            if frame.get("predicate_token_id") not in token_ids:
                raise ValueError("semantic-role predicate does not reference a parser token")
            if any(
                argument.get("token_id") not in token_ids for argument in frame.get("arguments", [])
            ):
                raise ValueError("semantic-role argument does not reference a parser token")
            if any(not argument.get("role") for argument in frame.get("arguments", [])):
                raise ValueError("semantic-role argument label is required")
        for chain in analysis.get("coreference", []):
            for mention in chain.get("mentions", []):
                start, end = mention.get("start_codepoint"), mention.get("end_codepoint")
                if not isinstance(start, int) or not isinstance(end, int):
                    raise ValueError("coreference mention requires exact offsets")
                if not 0 <= start < end <= len(text) or text[start:end] != mention.get("text"):
                    raise ValueError("coreference mention offsets do not reconstruct source text")

    def _annotation(
        self,
        run: AnalysisRun,
        message: Message,
        revision: MessageRevision,
        kind: str,
        value: dict[str, Any],
        start: int,
        end: int,
        method: str,
        *,
        alternatives: list[dict[str, Any]] | None = None,
        model: str = "pymorphy3",
        model_revision: str | None = None,
    ) -> Annotation:
        return Annotation(
            id=new_id(),
            snapshot_id=run.snapshot_id,
            run_id=run.id,
            object_type="message",
            object_id=message.id,
            kind=kind,
            value=value,
            evidence=[
                {
                    "object_type": "message",
                    "object_id": message.id,
                    "revision_id": revision.id,
                    "start_codepoint": start,
                    "end_codepoint": end,
                    "exact_text_hash": revision.text_hash,
                }
            ],
            status="provisional",
            raw_confidence=None,
            calibrated_confidence=None,
            alternatives=alternatives or [],
            provenance={
                "corpus_snapshot_id": run.snapshot_id,
                "ontology_version": self.settings.ontology_version,
                "codebook_version": run.configuration["codebook_release"],
                "codebook_artifact_hash": run.configuration["codebook_artifact_hash"],
                "pipeline_version": ANALYSIS_VERSION,
                "model_provider": "deterministic" if model == "pymorphy3" else "local",
                "model": model,
                "model_revision": model_revision,
                "method": method,
                "analysis_run_id": run.id,
                "created_at": datetime.now(UTC).isoformat(),
            },
        )

    def _derive(self, revision_id: str, annotation_id: str, run_id: str, relation: str) -> None:
        self.session.add(
            DerivationEdge(
                id=new_id(),
                source_type="message_revision",
                source_id=revision_id,
                target_type="annotation",
                target_id=annotation_id,
                relation=relation,
                run_id=run_id,
            )
        )

    def _rows(
        self, snapshot_id: str, offset: int, limit: int
    ) -> list[tuple[Message, MessageRevision]]:
        return list(
            self.session.execute(
                select(Message, MessageRevision)
                .join(SnapshotMessageRevision, SnapshotMessageRevision.message_id == Message.id)
                .join(MessageRevision, MessageRevision.id == SnapshotMessageRevision.revision_id)
                .where(SnapshotMessageRevision.snapshot_id == snapshot_id)
                .order_by(Message.conversation_id, Message.resolved_timestamp, Message.id)
                .offset(offset)
                .limit(limit)
            )
        )

    def _analysis_run(self, corpus_id: str, run_id: str | None) -> AnalysisRun:
        statement = (
            select(AnalysisRun)
            .join(CorpusSnapshot, CorpusSnapshot.id == AnalysisRun.snapshot_id)
            .where(
                CorpusSnapshot.corpus_id == corpus_id,
                AnalysisRun.run_type == "linguistic-analysis",
            )
        )
        if run_id:
            statement = statement.where(AnalysisRun.id == run_id)
        run = self.session.scalar(statement.order_by(AnalysisRun.created_at.desc()))
        if run is None:
            raise LookupError("linguistic analysis run not found")
        return run

    def _latest_snapshot(self, corpus_id: str) -> CorpusSnapshot:
        snapshot = self.session.scalar(
            select(CorpusSnapshot)
            .where(CorpusSnapshot.corpus_id == corpus_id)
            .order_by(CorpusSnapshot.created_at.desc(), CorpusSnapshot.id.desc())
        )
        if snapshot is None:
            raise LookupError("corpus snapshot not found")
        return snapshot

    def _snapshot(self, snapshot_id: str) -> CorpusSnapshot:
        snapshot = self.session.get(CorpusSnapshot, snapshot_id)
        if snapshot is None:
            raise LookupError("corpus snapshot not found")
        return snapshot

    def _run(self, run_id: str) -> AnalysisRun:
        run = self.session.get(AnalysisRun, run_id)
        if run is None or run.run_type != "linguistic-analysis":
            raise LookupError("linguistic analysis run not found")
        return run

    def _tasks(self, run_id: str) -> dict[str, AnalysisTask]:
        return {
            task.task_key: task
            for task in self.session.scalars(
                select(AnalysisTask).where(AnalysisTask.run_id == run_id)
            )
        }

    def _is_cancelled(self, run_id: str) -> bool:
        self.session.expire_all()
        return self._run(run_id).status == "cancelled"
