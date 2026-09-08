from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from prometheus_observatory.importers import ImportService
from prometheus_observatory.linguistic_analysis import LinguisticAnalysisService
from prometheus_observatory.model_gateway import (
    EvidenceBundle,
    LinguisticResult,
    LocalLinguisticAnalysisAdapter,
    ModelPolicy,
)
from prometheus_observatory.models import Annotation, Corpus, MessageRevision
from prometheus_observatory.object_store import ContentAddressedStore


def import_linguistic_fixture(db_session: Session, tmp_path: Path) -> Corpus:
    payload = {
        "id": "linguistic-chat",
        "name": "Лингвистический тест",
        "messages": [
            {
                "id": 1,
                "type": "message",
                "date": "2026-01-01T10:00:00+00:00",
                "from": "Анна",
                "from_id": "anna",
                "text": "Анна не проверила новый отчёт.",
            },
            {
                "id": 2,
                "type": "message",
                "date": "2026-01-01T10:01:00+00:00",
                "from": "Борис",
                "from_id": "boris",
                "text": "Она должна отправить его Борису.",
            },
        ],
    }
    source_path = tmp_path / "linguistic.json"
    source_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    corpus = Corpus(name="Лингвистика", language="ru", privacy_policy="LOCAL_ONLY")
    db_session.add(corpus)
    db_session.commit()
    with source_path.open("rb") as source:
        stored = ContentAddressedStore(tmp_path / "objects").put_stream(source)
    ImportService(db_session).import_object(
        corpus, stored, source_path.name, "application/json", "telegram"
    )
    return corpus


def test_morphology_entities_and_coreference_are_evidence_linked_and_provisional(
    db_session: Session, tmp_path: Path
) -> None:
    corpus = import_linguistic_fixture(db_session, tmp_path)
    service = LinguisticAnalysisService(db_session)

    run = service.create(corpus.id, include_local_parser=False)
    repeated = service.create(corpus.id, include_local_parser=False)
    annotations = list(db_session.scalars(select(Annotation).where(Annotation.run_id == run.id)))
    linguistic = [item for item in annotations if item.kind == "linguistic_features"]
    mentions = [item for item in annotations if item.kind == "entity_mention"]
    coreference = [item for item in annotations if item.kind == "coreference_candidates"]

    assert run.status == "completed"
    assert repeated.id == run.id
    assert len(linguistic) == 2
    first = linguistic[0]
    assert first.status == "provisional"
    assert first.raw_confidence is None
    assert first.value["capability_status"]["dependencies"] == ("unavailable_without_local_parser")
    assert any(token["lemma"] == "не" for token in first.value["tokens"])
    assert first.value["negation_scopes"]
    for token in first.value["tokens"]:
        start, end = token["start_codepoint"], token["end_codepoint"]
        revision = db_session.get(MessageRevision, first.evidence[0]["revision_id"])
        assert revision is not None
        assert revision.text[start:end] == token["text"]
    assert {item.value["text"] for item in mentions} >= {"Анна", "Она", "Борису"}
    pronoun = next(
        item
        for item in coreference
        if item.value["mention_id"]
        in {mention.value["mention_id"] for mention in mentions if mention.value["text"] == "Она"}
    )
    assert pronoun.value["accepted_target"] is None
    assert pronoun.calibrated_confidence is None
    assert any(
        alternative["value"].get("target_message_id") for alternative in pronoun.alternatives
    )
    task = next(
        item for item in service.run_payload(run.id)["tasks"] if item["task_key"] == "local_parser"
    )
    assert task["status"] == "disabled"


def test_linguistic_run_can_cancel_and_resume_from_its_checkpoint(
    db_session: Session, tmp_path: Path
) -> None:
    corpus = import_linguistic_fixture(db_session, tmp_path)
    service = LinguisticAnalysisService(db_session)
    run = service.create(corpus.id, include_local_parser=False, execute=False)

    assert service.cancel(run.id).status == "cancelled"
    assert service.resume(run.id).status == "completed"
    assert service.create(corpus.id, include_local_parser=False).id == run.id


def test_pinned_local_parser_output_is_validated_and_persisted(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = import_linguistic_fixture(db_session, tmp_path)
    service = LinguisticAnalysisService(db_session)
    monkeypatch.setattr(service.settings, "local_linguistic_base_url", "http://127.0.0.1:8081/v1")
    monkeypatch.setattr(service.settings, "local_linguistic_revision", "parser-revision-1")

    def analyze(
        adapter: LocalLinguisticAnalysisAdapter,
        bundle: EvidenceBundle,
        _policy: ModelPolicy,
    ) -> LinguisticResult:
        analyses = []
        for item in bundle.items:
            analyses.append(
                {
                    "evidence_id": item.evidence_id,
                    "tokens": [
                        {
                            "id": 1,
                            "text": item.text,
                            "start_codepoint": 0,
                            "end_codepoint": len(item.text),
                        }
                    ],
                    "dependencies": [{"dependent_id": 1, "head_id": 0, "relation": "root"}],
                    "entities": [],
                    "semantic_roles": [],
                    "coreference": [],
                }
            )
        return LinguisticResult(
            analyses=analyses,
            provider=adapter.provider,
            model=adapter.model,
            latency_ms=1,
            request_hash=bundle.request_hash(),
        )

    monkeypatch.setattr(LocalLinguisticAnalysisAdapter, "analyze", analyze)

    run = service.create(corpus.id, include_local_parser=True)
    parser_annotations = list(
        db_session.scalars(
            select(Annotation).where(
                Annotation.run_id == run.id,
                Annotation.kind == "linguistic_parser_output",
            )
        )
    )
    task = next(
        item for item in service.run_payload(run.id)["tasks"] if item["task_key"] == "local_parser"
    )

    assert run.status == "completed"
    assert task["status"] == "completed"
    assert len(parser_annotations) == 2
    assert all(
        item.value["capability_status"]["semantic_roles"] == "available"
        for item in parser_annotations
    )


def test_invalid_local_parser_offsets_fail_only_the_optional_stage(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = import_linguistic_fixture(db_session, tmp_path)
    service = LinguisticAnalysisService(db_session)
    monkeypatch.setattr(service.settings, "local_linguistic_base_url", "http://127.0.0.1:8081/v1")
    monkeypatch.setattr(service.settings, "local_linguistic_revision", "parser-revision-1")

    def analyze(
        adapter: LocalLinguisticAnalysisAdapter,
        bundle: EvidenceBundle,
        _policy: ModelPolicy,
    ) -> LinguisticResult:
        return LinguisticResult(
            analyses=[
                {
                    "evidence_id": item.evidence_id,
                    "tokens": [
                        {"id": 1, "text": "wrong", "start_codepoint": 0, "end_codepoint": 5}
                    ],
                    "dependencies": [],
                    "entities": [],
                    "semantic_roles": [],
                }
                for item in bundle.items
            ],
            provider=adapter.provider,
            model=adapter.model,
            latency_ms=1,
            request_hash=bundle.request_hash(),
        )

    monkeypatch.setattr(LocalLinguisticAnalysisAdapter, "analyze", analyze)

    run = service.create(corpus.id, include_local_parser=True)
    task = next(
        item for item in service.run_payload(run.id)["tasks"] if item["task_key"] == "local_parser"
    )

    assert run.status == "completed"
    assert task["status"] == "failed"
    assert "offsets" in task["error"]
    assert db_session.scalar(
        select(Annotation).where(
            Annotation.run_id == run.id,
            Annotation.kind == "linguistic_features",
        )
    )
