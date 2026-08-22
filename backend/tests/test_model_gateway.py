from __future__ import annotations

import pytest

from prometheus_observatory.model_gateway import (
    EvidenceBundle,
    EvidenceItem,
    GenericHTTPAdapter,
    ModelPolicy,
    pseudonymize_bundle,
)
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
