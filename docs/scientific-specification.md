# Scientific specification v0.1

## Epistemic hierarchy

| Level | Meaning | Examples |
| --- | --- | --- |
| L0 Source | Literal source fact | message, sender, timestamp, reply relation |
| L1 Observation | Evidence-linked annotation | proposition, stance, dialogue act, epistemic status |
| L2 Measurement | Deterministic or statistical derivation | participation share, reciprocity, stance trajectory |
| L3 Interpretation | Falsifiable hypothesis over measurements | possible topic-specific broker role |
| L4 Causal | Claim under a declared identification design | effect of an intervention or policy |

The database and API carry the level explicitly. A `causal` finding is rejected unless it is L4, and the research-plan contract requires an `identification_design_id` for quasi-causal or causal work.

## Non-negotiable measurement rules

1. Messages and their source revisions are immutable.
2. Every annotation contains exact evidence and full producer provenance.
3. Proposition clustering never deletes or rewrites proposition mentions.
4. Stance has a holder and target; sentiment is not stance.
5. Epistemic state separates polarity, commitment, certainty, evidence basis, and attribution.
6. Influence, power, persuasion, health, and relationship state are vectors or hypotheses over primitives, never raw LLM labels.
7. Findings show supporting cases, counterexamples, alternative explanations, and sensitivity results.
8. Summaries and embeddings are indexes, not source evidence.

## Current validity status

The deterministic rules are inspectable development baselines and remain `provisional`. They make the complete evidence system usable before a local model is configured; they do not satisfy the planned Russian gold-set gates. The English pipeline is a functioning demo marked `UNVALIDATED` and is excluded from scientific claims.
