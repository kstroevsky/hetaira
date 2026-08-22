from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from prometheus_observatory.ontology import (
    CausalStatus,
    EpistemicLevel,
    EvidenceRef,
    FindingEnvelope,
    Provenance,
)


def provenance() -> Provenance:
    return Provenance(
        corpus_snapshot_id="snapshot",
        ontology_version="0.1.0",
        codebook_version="ru@0.1",
        pipeline_version="0.1.0",
        analysis_run_id="run",
        created_at=datetime.now(UTC),
    )


def test_evidence_span_requires_both_offsets() -> None:
    with pytest.raises(ValidationError):
        EvidenceRef(object_type="span", object_id="s1", start_codepoint=2)


def test_causal_status_requires_l4() -> None:
    with pytest.raises(ValidationError):
        FindingEnvelope(
            claim="X caused Y",
            epistemic_level=EpistemicLevel.INTERPRETATION,
            causal_status=CausalStatus.CAUSAL,
            supporting_evidence=[],
            dependency_dag_root="m1",
            provenance=provenance(),
        )
