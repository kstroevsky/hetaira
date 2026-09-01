# Episode Microscope v0.1

The Episode Microscope is the first evidence-first deep-analysis slice. It is computed on demand for the deterministic semantic window containing a selected message; it does not annotate the full corpus as a side effect.

```text
selected representative message
  → structural 8-hour episode
  → matching window of at most 40 messages
  → Unicode sentence spans
  → provisional dialogue acts and propositions
  → explicit reply target
  → resolved SUPPORT / OPPOSE edge or ABSTAIN
  → grounding / clarification / repair signals
  → exact source message and offsets
```

The current `episode-microscope-rules-ru@0.1.0` implementation deliberately uses only high-precision Russian rules. Agreement and disagreement require both an explicit reply and a lexical stance signal. A stance edge is resolved only when the replied-to message contains exactly one candidate proposition; otherwise the result is `ABSTAIN` with all candidate targets. `ABSTAIN` means unresolved target—not neutrality.

Every proposition retains the message, revision, Unicode-codepoint offsets, and exact text. The UI can open every message in the existing source microscope.

## Identity provenance

Participant names in the Overview now open a source-backed identity popover. It distinguishes direct Telegram IDs, usernames, and unambiguous source-roster mappings. Observed names and roster aliases are listed separately with evidence messages. For example, a current display name can remain `Undefined` while a roster alias shows `Людвиг`; the UI does not silently replace one with the other.

## Validation boundary

All outputs are `provisional_rules`. Absence of a proposition, stance, or grounding label is not evidence that the phenomenon is absent. This vertical slice is intended to make errors visible and collect Russian adjudication data before introducing local/API model challengers or corpus-wide composite claims.
