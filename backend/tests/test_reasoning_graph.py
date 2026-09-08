from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from prometheus_observatory.importers import ImportService
from prometheus_observatory.model_gateway import (
    EvidenceBundle,
    LocalPairClassificationAdapter,
    ModelPolicy,
    PairClassificationResult,
)
from prometheus_observatory.models import Annotation, Corpus, PropositionRelation
from prometheus_observatory.object_store import ContentAddressedStore
from prometheus_observatory.reasoning_graph import ReasoningGraphService

FIXTURE = Path(__file__).parent / "fixtures" / "telegram.json"


def test_reasoning_graph_uses_propositions_and_keeps_nli_independent(
    db_session: Session, tmp_path: Path
) -> None:
    corpus = Corpus(name="Reasoning", language="ru", privacy_policy="LOCAL_ONLY")
    db_session.add(corpus)
    db_session.commit()
    with FIXTURE.open("rb") as source:
        stored = ContentAddressedStore(tmp_path / "objects").put_stream(source)
    ImportService(db_session).import_object(
        corpus, stored, FIXTURE.name, "application/json", "telegram"
    )

    service = ReasoningGraphService(db_session)
    run = service.create(corpus.id, include_nli=True)
    graph = service.graph(corpus.id, run_id=run.id)

    assert run.status == "completed"
    assert graph["propositions"]
    components = list(
        db_session.scalars(
            select(Annotation).where(
                Annotation.run_id == run.id,
                Annotation.kind == "argument_component",
            )
        )
    )
    candidates = list(
        db_session.scalars(
            select(Annotation).where(
                Annotation.run_id == run.id,
                Annotation.kind == "argument_relation_candidate",
            )
        )
    )
    assert components
    assert candidates
    assert all(item.value["accepted_relation"] is None for item in candidates)
    assert any(item["relation_type"] == "SUPPORTS" for item in graph["relations"])
    assert all(item["status"] == "provisional" for item in graph["relations"])
    nli_task = next(
        task
        for task in service.run_payload(run.id)["tasks"]
        if task["task_key"] == "nli_challenger"
    )
    assert nli_task["status"] == "unavailable"
    assert not list(
        db_session.scalars(
            select(PropositionRelation).where(
                PropositionRelation.run_id == run.id,
                PropositionRelation.relation_type.like("NLI_%"),
            )
        )
    )


def test_local_nli_is_persisted_as_a_non_truth_challenger(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = Corpus(name="NLI", language="ru", privacy_policy="LOCAL_ONLY")
    db_session.add(corpus)
    db_session.commit()
    with FIXTURE.open("rb") as source:
        stored = ContentAddressedStore(tmp_path / "objects").put_stream(source)
    ImportService(db_session).import_object(
        corpus, stored, FIXTURE.name, "application/json", "telegram"
    )
    service = ReasoningGraphService(db_session)
    monkeypatch.setattr(service.settings, "local_nli_base_url", "http://127.0.0.1:8082/v1")
    monkeypatch.setattr(service.settings, "local_nli_revision", "nli-revision-1")

    def classify(
        adapter: LocalPairClassificationAdapter,
        bundle: EvidenceBundle,
        pairs: list[dict[str, str]],
        _policy: ModelPolicy,
    ) -> PairClassificationResult:
        return PairClassificationResult(
            classifications=[
                {
                    "pair_id": pair["pair_id"],
                    "label": "ENTAILMENT",
                    "scores": {"ENTAILMENT": 0.8, "CONTRADICTION": 0.1, "NEUTRAL": 0.1},
                }
                for pair in pairs
            ],
            provider=adapter.provider,
            model=adapter.model,
            latency_ms=1,
            request_hash=bundle.request_hash(),
        )

    monkeypatch.setattr(LocalPairClassificationAdapter, "classify_pairs", classify)

    run = service.create(corpus.id, include_nli=True)
    nli = db_session.scalar(
        select(Annotation).where(Annotation.run_id == run.id, Annotation.kind == "nli_relation")
    )

    assert nli is not None
    assert nli.value["label"] == "ENTAILMENT"
    assert nli.value["truth_status"] == "not_determined"
    assert nli.calibrated_confidence is None
