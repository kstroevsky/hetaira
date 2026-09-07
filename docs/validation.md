# Validation gates

## Foundation 0.2 correctness gate

Phase 2 work may consume Foundation outputs only after all six steps pass on a frozen build:

1. **Snapshot identity:** repeated imports are idempotent; changed exports append revisions; every snapshot selects exactly one revision per message and older snapshots remain reproducible.
2. **Scope isolation:** evidence, retrieval, comparisons, derivations, and measurements cannot cross corpus or snapshot boundaries.
3. **Primitive semantics:** epistemic observations require propositions; stance resolution produces a resolved target, weighted targets, `ABSTAIN`, or `DISPUTED`, never a fabricated fallback target.
4. **Measurement provenance:** participation and reciprocity run only through validated plugins; explicit-reply filters, dependency fingerprints, and derivation edges are complete.
5. **Privacy boundary:** local adapters are literal HTTP loopback only; API routes cannot exceed the persisted corpus policy; preview/approval, redaction, schema, token, cost, and invocation checks pass.
6. **Operational evidence:** migration upgrade/rollback, concurrent artifact writes, interruption/resume fixtures, bounded-memory scale import, frontend build, and rendered workbench navigation pass.

Phase 2 completes deletion lineage, resumable task operations, artifact retention, and cost estimation by extending these frozen contracts. It must not create a second model gateway. Composite influence, power, persuasion, coalitions, health, forecasting, pivotalness, and hypothesis discovery remain gated behind their later validation phases.

## Scientific promotion gates

- `gold-ru-v1`: 1,200 stratified utterance/exchange units; 30% double-annotated; complete-episode 60/20/20 split.
- Span extraction: exact and overlap F1.
- Labels: macro/micro F1; relations: endpoint-aware F1.
- Calibration: ECE and Brier score.
- Promotion: five-point macro-F1 non-inferiority margin against a trained annotator, plus task floor (0.80 simple classification, 0.70 difficult span/relation tasks).
- Retrieval: at least 300 Russian queries and recall@20 ≥ 0.90 before evidence-backed synthesis promotion.
- Any failed task remains `provisional` and cannot feed an unqualified composite finding.
- Forecasting uses forward-time validation only.
- Pivotalness cannot ship before the associated forecaster is calibrated and prospectively validated.

## Gold-set operational contract

`gold-ru-v1` stores the exact 30% double-annotation cohort on each unit as `double_annotation_required`. Membership is a deterministic hash of the frozen snapshot object identity and the set seed. Complete episode groups are assigned to exactly one split; the validation cockpit reports authoritative full-set counts rather than the paginated annotation queue.

Freezing requires at least one confirmed annotation for every unit and two distinct confirmed annotators for every DOUBLE unit. The cockpit exposes confirmed-unit coverage, 60/20/20 split counts, double-annotation completion, difficult-case count, and exact raw agreement over comparable unit×kind pairs. Raw agreement is diagnostic only and does not replace the planned human-agreement statistic or promotion thresholds.
