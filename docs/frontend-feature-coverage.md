# Frontend feature coverage

Status: complete for implemented baseline outputs. Every analytical response also provides a
collapsible **Полный технический результат** view so configuration, provenance, controls,
missingness, uncertainty, unavailable reasons, and fields not promoted into summary cards remain
inspectable.

Every methodology-bearing section and metric has an adjacent help control. The explanations define
the method in plain language, tell the reader how to interpret the displayed value, and state the
main epistemic limitation. The same guidance covers the source timeline, per-message microscope,
L0–L3 evidence chain, annotation protocol, validation gate, episode microscope, all roadmap
workspaces, and complete technical artifacts.

Help popovers share one application-level controller: opening one closes the previous one, an
outside pointer press closes the active popover, and Escape closes it while restoring focus to its
trigger. Popovers render in a body portal with fixed positioning, flip above the trigger when needed,
and clamp width, height, and coordinates to a 12 px viewport margin. This contract is tested at a
320 × 240 viewport as well as through the application interaction tests.

| Roadmap IDs | Primary UI | Visible coverage |
| --- | --- | --- |
| NLP-01–02 | Граф диалога | Source replies, all ranked candidates, proposal eligibility/reasons, discourse relations, review controls, run tasks, reference-set state and frozen evaluation metrics |
| NLP-03, NLP-22 | Лингвистика | Exact-offset tokens, lemmas, POS/morphology, noun phrases, negation, modals, entity mentions, coreference alternatives, local parser output/status |
| NLP-04 | Граф диалога / Лингвистика | Encoder and parser task availability, pinned run configuration, challenger results |
| NLP-05–06 | Аргументы | Components, relation candidates and abstention reasons, support/attack edges, NLI scores and truth guardrail |
| NLP-07–08, NLP-10 | Динамика | Ordered-pair coordination intervals, Kaplan–Meier risk/censoring rows, relational-event coefficients or sample gate, controls and missingness |
| NLP-11–14 | Состояния | Semantic-change ranking/representation, NMF/LDA topics and trajectories, ARI disagreement, activity/topic change points, HMM sequence/transition/emission diagnostics |
| NLP-09, NLP-15–17 | Сети | Hawkes status/matrix, layer and monthly communities, unavailable layers, motif/null comparison, dialogue transitions and frequent patterns |
| NLP-18–19 | Статистика | Dyad permutation statistics, preserved-null details, fixed effects, participant/conversation intercepts, controls, uncertainty/sample gates |
| NLP-20–21 | Эксперименты | Transfer entropy/null p-values, estimator bias, PID components, multidimensional affect trajectories and interpretation boundary |

Environment-backed local model provisioning remains configured outside corpus results. Each run
shows the effective model endpoint/model/revision configuration without exposing credentials.
