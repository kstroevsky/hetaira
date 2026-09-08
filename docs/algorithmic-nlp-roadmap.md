# Algorithmic and statistical NLP roadmap

Status: approved implementation direction. The source proposal is retained outside the repository
with SHA-256 `8fb13ae85939bafea092b90c8a19242f4d383731c35f1faf10fe428532db0c60`.
It is design input rather than a frozen scientific specification.

## First implemented slice

The conversation graph pipeline operates on a frozen corpus snapshot and produces:

- source-native `REPLIES_TO` links read directly from imports;
- provisional `RESPONDS_TO` candidate rankings from a bounded Russian lexical baseline;
- an optional local `multilingual-e5-small` cosine challenger through the existing model policy;
- provisional message-to-message discourse proposals with exact endpoint revisions and spans;
- resumable task checkpoints, dependency fingerprints, paged graph queries, and human reviews;
- a separate one-human `conversation-graph-reference-v1` workflow whose targets can be found by
  searching the complete source conversation independently of the candidate generator.

The default candidate horizon is the preceding 40 non-empty messages inside eight hours, with five
persisted alternatives. An available source reply target is included even when it lies outside that
horizon. These are operational defaults, not scientific thresholds. Rankings never become accepted
edges automatically. Encoder cosine is uncalibrated; ECE and Brier scores remain unavailable until
a probabilistic task model exists.

Initial discourse labels are `ANSWERS`, `ELABORATES`, `CONTRASTS`, `ACKNOWLEDGES`, `CORRECTS`,
`CLARIFIES`, `ACCEPTS`, and `REJECTS`. Multiple labels and targets are allowed. These labels describe
textual relations and do not establish truth, causation, influence, stance, or internal state.

## Staged roadmap

| IDs | Stage | Intended capability |
| --- | --- | --- |
| NLP-01, NLP-02, NLP-04 | Conversation graph | Reply candidates, discourse relations, local encoder tier |
| NLP-03, NLP-22, NLP-05, NLP-06 | Linguistic expansion | Morphosyntax/SRL, uncertain entity links, NLI challenger, argument graph |
| NLP-10, NLP-07, NLP-08 | Interaction dynamics | Directional coordination, relational events, survival analysis |
| NLP-11–NLP-14 | Semantic/state dynamics | Contextual change, topic challengers, change points, latent states |
| NLP-09, NLP-15–NLP-17 | Network/sequence analysis | Diffusion, multilayer communities, motifs, sequence mining |
| NLP-18, NLP-19 | Horizontal statistics | Null models, controls, hierarchical models, uncertainty |
| NLP-20, NLP-21 | Experimental research | Transfer entropy/PID and multidimensional linguistic affect |

## Linguistic expansion implemented slice

NLP-03 and NLP-22 now have a corpus-wide provisional vertical slice. Every Russian message can
persist exact-offset tokens, lemmas, Universal-style POS labels, OpenCorpora morphology, heuristic
noun phrases, negation scopes, and modal markers. Entity mentions preserve their source spans and
basis. Pronouns and repeated mentions receive bounded, recency/morphology-ranked antecedent
alternatives; no entity or coreference target is accepted automatically.

Dependency trees, model-based NER/coreference, and semantic roles use an optional typed local parser
contract. The endpoint must use literal loopback HTTP, declare a pinned model revision, reproduce
all source offsets, and return token-linked dependency and SRL structures. Missing or failed parser
output leaves the deterministic layer available and is represented as unavailable rather than as a
negative observation.

NLP-05 and NLP-06 now have a provisional reasoning-graph slice. Existing proposition and reply
graphs generate bounded proposition-pair candidates; rules classify observable argument components
and propose `SUPPORTS` or `ATTACKS` while retaining abstained candidates. A typed, pinned, loopback
pair classifier can contribute NLI scores as a separate channel. Every NLI result records
`truth_status: not_determined`; it never silently becomes a stance, argument, or truth judgment.

NLP-07, NLP-08, and NLP-10 now have an explicit-reply interaction-dynamics baseline. Directional
coordination compares each reply with the immediately replied-to message relative to the responder's
snapshot baseline and reports ordered-pair intervals. Response survival uses first explicit replies,
right-censors at conversation end, and publishes its Kaplan–Meier risk table. The relational-event
engine fits a regularized sender-conditioned receiver-choice likelihood over conversation risk sets
with repetition, reciprocity, receiver popularity, and 24-hour dyad recency. It refuses estimation
below ten informative risk sets and describes exponentiated coefficients as relative choice odds,
not causal effects or unconditional event rates.

NLP-11 through NLP-14 now have a multi-method semantic/state artifact. Semantic change prefers
pinned cached contextual embeddings and names its TF-IDF context fallback when embeddings are not
available. NMF and LDA publish separate topic assignments and adjusted Rand agreement. CUSUM and
binary segmentation emit independent candidates over activity and topic prevalence. A two-state
diagonal-Gaussian HMM baseline models monthly observation vectors; its states remain `state_0` and
`state_1` rather than receiving post-hoc psychological or conversational labels.

NLP-09 and NLP-15 through NLP-17 now have a network/sequence artifact. It separates interaction,
semantic-similarity, support, and attack layers, while marking stance and knowledge-flow layers
unavailable until their endpoints exist. Leiden communities are reported per layer and per month for
interaction. Reciprocal and transitive motifs are compared with 100 seeded target permutations that
preserve sender and receiver event counts. Dialogue acts produce episode-level transitions and
frequent patterns without attaching success labels. A fixed-decay exponential-kernel Hawkes moment
baseline estimates participant excitation only above 20 events and reports stability diagnostics;
these values remain associational triggering signals.

NLP-18 and NLP-19 now have a horizontal statistical-synthesis artifact. The reusable null engine
runs seeded constrained permutations with an explicit statistic, denominator, preserved properties,
null mean/deviation, z-score, and finite-sample p-value. The first application shuffles reply
receivers within conversation while preserving sender sequence and receiver event totals. A
regularized hierarchical logistic MAP model estimates whether a message receives an explicit reply,
with fixed message-length/question/time controls and participant/conversation intercepts. It refuses
estimation below 50 messages, five events, five non-events, or three participants; posterior or
full-Hessian intervals remain explicitly unavailable in this baseline.

NLP-01 explicitly retains probabilistic pair/cross-encoder classifiers and global graph optimization
as later challengers after reference relations are ready. NLP-02 retains discourse-unit segmentation
and richer discourse parsing. The method inventories in the source proposal remain candidates to
compare; they are not commitments to ship every alternative.

## Validation boundary

The Foundation 80/24 pilot and its six tasks remain unchanged. The conversation graph reference is
single-human and therefore provisional. Scientific promotion requires independent human judgments,
task-specific endpoint metrics, calibration for probabilistic models, frozen comparison data, and
forward-time validation where forecasting is involved. Composite influence, power, persuasion,
coalition, health, and causal claims remain gated by the existing scientific specification.
