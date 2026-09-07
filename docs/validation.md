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

## Reference-pilot gate

- Do not create or label `gold-ru-v1` yet. Start with a corpus-specific `reference-ru-pilot-v1`: 80 anchor messages sampled over the complete snapshot, 24 with blind independent A/B judgments, and complete episode groups assigned to one 60/20/20 split.
- Every unit has an explicit FINAL judgment for each required task: dialogue act, proposition, stance, epistemic state, grounding, and argumentation. `PRESENT`, `ABSENT`, and `ABSTAIN` are completed judgments; `NOT_ANNOTATED` is not.
- A/B observations remain hidden from each other and immutable after submission. Their agreement is calculated before adjudication. FINAL is a separate expert judgment and is the only layer used for model evaluation.
- The pilot validates the codebook and workflow first. Only after real humans can apply it consistently should the project define a multi-corpus `gold-ru-core-v1` and task-specific challenge sets.

## Scientific promotion gates

- A future `gold-ru-core-v1` may target roughly 1,200 naturalistic units, but sample size is not a scientific requirement and does not replace rare-phenomenon challenge sets.
- Span extraction: exact and overlap F1.
- Labels: task- and class-specific macro/micro F1. Stance, epistemics, grounding, and argument relations use endpoint-aware matching; repeated same-label instances are matched as distinct spans/entities.
- Calibration: ECE and Brier score.
- Promotion: five-point macro-F1 non-inferiority margin against a trained annotator, plus task floor (0.80 simple classification, 0.70 difficult span/relation tasks).
- Retrieval: at least 300 Russian queries and recall@20 ≥ 0.90 before evidence-backed synthesis promotion.
- Any failed task remains `provisional` and cannot feed an unqualified composite finding.
- Forecasting uses forward-time validation only.
- Pivotalness cannot ship before the associated forecaster is calibrated and prospectively validated.

## Gold-set operational contract

The reference pilot stores the exact 30% double-annotation cohort on each unit as `double_annotation_required`. Membership is a deterministic hash of the frozen snapshot object identity and the set seed. Complete episode groups are assigned to exactly one split; the validation cockpit reports authoritative full-set counts rather than the paginated annotation queue.

Freezing requires all six FINAL task judgments for every unit. For DOUBLE units, FINAL cannot be submitted until two distinct humans have independently completed A and B for that task. The frozen manifest preserves A, B, and FINAL while evaluation consumes FINAL only. The cockpit exposes per-task completion, split counts, double-annotation completion, difficult-case count, and raw pre-adjudication agreement. Raw agreement is diagnostic only and does not replace a task-appropriate human-agreement statistic or promotion thresholds.

Reserved targeted challenge sets are `challenge-ru-stance-target-v1`, `challenge-ru-epistemic-attribution-v1`, `challenge-ru-grounding-repair-v1`, and `challenge-ru-argument-relations-v1`. They are not promoted or populated until the reference pilot stabilizes the codebook.
