from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from prometheus_observatory.model_gateway import (
    EgressPolicyEnforcer,
    EvidenceBundle,
    EvidenceItem,
    GenericHTTPAdapter,
    LocalLinguisticAnalysisAdapter,
    LocalOpenAICompatibleAdapter,
    LocalOpenAICompatibleEmbeddingAdapter,
    ModelPolicy,
    RemoteOpenAICompatibleAdapter,
    pseudonymize_bundle,
    sanitize_egress_bundle,
)
from prometheus_observatory.models import Corpus
from prometheus_observatory.ontology import PrivacyPolicy


def test_local_only_policy_blocks_external_calls() -> None:
    adapter = GenericHTTPAdapter(base_url="https://invalid.example", model="test")
    bundle = EvidenceBundle(
        items=[EvidenceItem(evidence_id="e1", text="Анна: тест")],
        privacy_policy=PrivacyPolicy.LOCAL_ONLY,
        reason="test",
    )
    with pytest.raises(PermissionError, match="forbids"):
        adapter.generate_structured("stance", bundle, {"type": "object"}, ModelPolicy())


def test_pseudonymization_preserves_stable_identity() -> None:
    bundle = pseudonymize_bundle(
        [
            EvidenceItem(evidence_id="1", text="Анна согласна", participant="Анна"),
            EvidenceItem(evidence_id="2", text="Анна уточняет", participant="Анна"),
        ],
        PrivacyPolicy.API_PSEUDONYMIZED_MINIMAL,
        "quality escalation",
    )
    assert all(item.participant == "Участник 1" for item in bundle.items)
    assert all("Анна" not in item.text for item in bundle.items)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8080/v1",
        "http://0.0.0.0:8080/v1",
        "https://127.0.0.1:8080/v1",
        "http://127.0.0.2:8080/v1",
        "http://local-model.example:8080/v1",
    ],
)
def test_local_adapter_accepts_only_literal_http_loopback(url: str) -> None:
    with pytest.raises(ValueError, match="literal loopback"):
        LocalOpenAICompatibleAdapter(base_url=url, model="test")


def test_local_adapter_accepts_ipv4_and_ipv6_loopback() -> None:
    assert LocalOpenAICompatibleAdapter(base_url="http://127.0.0.1:8080/v1", model="test").is_local
    assert LocalOpenAICompatibleAdapter(base_url="http://[::1]:8080/v1", model="test").is_local


def test_embedding_adapter_uses_the_same_literal_loopback_boundary() -> None:
    adapter = LocalOpenAICompatibleEmbeddingAdapter(
        base_url="http://127.0.0.1:8080/v1",
        model="intfloat/multilingual-e5-small",
        model_revision="pinned-revision",
    )
    assert adapter.is_local
    assert adapter.capabilities.embeddings
    with pytest.raises(ValueError, match="literal loopback"):
        LocalOpenAICompatibleEmbeddingAdapter(
            base_url="https://127.0.0.1:8080/v1",
            model="intfloat/multilingual-e5-small",
        )


def test_linguistic_adapter_requires_literal_loopback_and_pinned_revision() -> None:
    assert LocalLinguisticAnalysisAdapter(
        base_url="http://127.0.0.1:8081/v1",
        model="russian-parser",
        model_revision="sha256:parser",
    ).capabilities.linguistic_analysis
    with pytest.raises(ValueError, match="literal loopback"):
        LocalLinguisticAnalysisAdapter(
            base_url="https://127.0.0.1:8081/v1",
            model="russian-parser",
            model_revision="sha256:parser",
        )
    with pytest.raises(ValueError, match="pinned"):
        LocalLinguisticAnalysisAdapter(
            base_url="http://127.0.0.1:8081/v1",
            model="russian-parser",
            model_revision="unversioned",
        )


def test_pseudonymization_builds_complete_map_before_redacting() -> None:
    bundle, _count = sanitize_egress_bundle(
        [
            EvidenceItem(
                evidence_id="raw-id",
                text="Анна пишет Борису: https://private.example/user/1",
                participant="Анна",
                metadata={"username": "anna", "language": "ru", "attachment_path": "/x"},
            ),
            EvidenceItem(evidence_id="raw-id-2", text="Борис отвечает Анне", participant="Борис"),
        ],
        PrivacyPolicy.API_PSEUDONYMIZED_MINIMAL,
        "test",
        identities=["Анна", "Борис"],
    )
    serialized = bundle.model_dump_json()
    assert "Анна" not in serialized and "Борис" not in serialized
    assert "private.example" not in serialized
    assert "username" not in serialized and "attachment_path" not in serialized
    assert bundle.items[0].evidence_id == "E1"
    assert bundle.items[0].metadata == {"language": "ru"}


def test_model_policy_cannot_exceed_persisted_corpus_policy(db_session: Session) -> None:
    corpus = Corpus(name="Закрытый", privacy_policy="LOCAL_ONLY")
    db_session.add(corpus)
    db_session.commit()
    adapter = RemoteOpenAICompatibleAdapter(base_url="https://api.example", model="test")
    with pytest.raises(PermissionError, match="exceeds corpus"):
        EgressPolicyEnforcer(db_session).enforce(
            corpus,
            adapter,
            [EvidenceItem(evidence_id="1", text="секрет")],
            ModelPolicy(privacy_policy=PrivacyPolicy.API_PSEUDONYMIZED_MINIMAL),
            "test",
            approved=True,
        )


def test_remote_models_are_disabled_for_this_deployment(db_session: Session) -> None:
    corpus = Corpus(
        name="Legacy API-capable corpus",
        privacy_policy="API_PSEUDONYMIZED_MINIMAL",
    )
    db_session.add(corpus)
    db_session.commit()
    adapter = RemoteOpenAICompatibleAdapter(base_url="https://api.example", model="test")
    with pytest.raises(PermissionError, match="disabled for this deployment"):
        EgressPolicyEnforcer(db_session).enforce(
            corpus,
            adapter,
            [EvidenceItem(evidence_id="1", text="тест")],
            ModelPolicy(privacy_policy=PrivacyPolicy.API_PSEUDONYMIZED_MINIMAL),
            "test",
            approved=True,
        )
