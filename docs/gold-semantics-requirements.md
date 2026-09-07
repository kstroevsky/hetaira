# Gold semantics change ledger

Status: accepted implementation input from the 2026-09-07 review. This document supplements, and does not replace, the original Foundation plan.

## Active requirements

| ID | Requirement | Exact contract / failure action |
| --- | --- | --- |
| GOLD-001 | Per-task completeness | Every required task has one of `PRESENT`, `ABSENT`, `ABSTAIN`, `NOT_ANNOTATED`. A unit is incomplete while any required FINAL judgment is `NOT_ANNOTATED`. |
| GOLD-002 | Independent and final layers | Preserve independent A, independent B where required, and FINAL adjudicated judgments as different records. Model evaluation consumes FINAL only. |
| GOLD-003 | Pre-adjudication agreement | Human agreement compares A versus B before adjudication. An LLM never counts as the second human. |
| GOLD-004 | Blind annotation | A cannot read B or FINAL; B cannot read A or FINAL. FINAL may read both independent judgments. |
| GOLD-005 | Explicit negatives | `ABSENT` means the human examined the task and found no instance. Missing rows or `NOT_ANNOTATED` never mean absence. |
| GOLD-006 | Task-specific evaluation | Use separate dialogue-act, proposition-span, stance, epistemic, grounding, and argument-relation evaluators. |
| GOLD-007 | Endpoint-aware relations | Stance and argument matches include holder/source/target endpoints. Different targets are different relations. |
| GOLD-008 | Preserve multiplicity | Multiple same-kind/same-label instances are matched as lists using span/entity endpoints; dictionary-key collapse is forbidden. |
| GOLD-009 | Context-aware anchor | The anchor message receives labels. Annotators receive previous turns, explicit reply target, optional next turn, and episode context without labelling context spans. |
| GOLD-010 | Whole-snapshot sampling | Sampling scans the complete snapshot and records time period, conversation, participant, episode size, reply status, length, question status, proposition multiplicity cue, rare cues, platform, and conversation goal/type. Prefix-only candidate pools are forbidden. |
| GOLD-010A | Russian eligibility | The Russian reference set excludes empty/attachment-only, pure non-Cyrillic, and system-event anchors while reporting all exclusion counts. Context may remain multilingual. |
| GOLD-011 | Corpus-specific naming | A set derived from one corpus is named as a corpus-specific reference/gold candidate; multi-corpus `gold-ru-core-v1` requires multiple diverse corpora. |
| GOLD-012 | Core size is practical | Approximately 1,200 naturalistic units are a practical benchmark size, not a scientific sufficiency guarantee. |
| GOLD-013 | Challenge sets | Reserve separate sets named `challenge-ru-stance-target-v1`, `challenge-ru-epistemic-attribution-v1`, `challenge-ru-grounding-repair-v1`, and `challenge-ru-argument-relations-v1`. |
| GOLD-014 | Single-human status | With one human, use `reference` or `gold candidate`, never “fully gold”. |
| GOLD-015 | Pilot before scale | Before the 1,200-unit effort, create a 50–100 unit pilot and double-annotate 20–30 units to validate the codebook with humans. |
| GOLD-016 | Task/class metrics | Report metrics per task and per class in addition to any macro or micro aggregate. “Macro over kinds” cannot be presented as class macro-F1. |
| GOLD-017 | Dependency-aware promotion | Model/prompt/runtime promotion records task-specific quality and calibration; composite findings inherit dependency validity. |
| FOUND-001 | Snapshot-safe idempotency | Analyzer run identity includes `snapshot.id` as well as the manifest hash. Same-content snapshots remain distinct runs. |
| FOUND-002 | Import identity audit | Export filename is not a canonical source namespace; renamed and incremental imports must not silently reuse stale segmentation. |
| MODEL-001 | Local models only | Paid/external API execution is out of scope. LLM assistance may use local models only and remains silver/provisional until human review. |

## Selected pilot parameters

The first corpus-specific pilot uses 80 naturalistic anchor units and 24 DOUBLE units. These values are implementation choices inside the accepted 50–100 and 20–30 ranges; they are not promotion thresholds.

Required tasks for every anchor:

1. `dialogue_act`
2. `proposition`
3. `stance`
4. `epistemic_state`
5. `grounding`
6. `argumentation`

## Superseded behavior

- A single confirmed annotation no longer completes a unit.
- Two “confirmed” annotations no longer stand in for blind A/B judgments.
- Generic `(revision_id, kind, label)` dictionary matching no longer defines gold equality.
- The empty 1,200-unit `gold-ru-v1` draft is not an annotation target. It was deleted after verifying that it contained zero linked annotations; the immutable source corpus and its analytical runs were not removed.

## Verification map

| Requirement IDs | Implementation evidence |
| --- | --- |
| GOLD-001–005, GOLD-008–009, GOLD-014–015 | `GoldTaskJudgment`, `GoldJudgmentAnnotation`, context API, blind A/B/FINAL workbench, immutable submissions, explicit task states, corpus-specific 80/24 pilot. |
| GOLD-006–008, GOLD-016 | Task-specific evaluator registry, endpoint-aware stance/argument matching, multiplicity-preserving bipartite matching, per-task and per-class reports. |
| GOLD-010–013 | Complete-snapshot multistrata sampler, group-safe splits, corpus-specific naming, reserved challenge-set contracts. |
| GOLD-017 | FINAL-only evaluation and task-level quality outputs are implemented; automatic dependency-aware model promotion remains a later phase. |
| FOUND-001–002 | Snapshot ID is part of analyzer idempotency; Telegram namespace is filename-independent; incremental segmentation appends new messages and rejects historical insertions. |
| MODEL-001 | Remote model routing is disabled by default; local adapters accept literal loopback HTTP only. |
