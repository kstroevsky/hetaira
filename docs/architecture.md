# Architecture

```text
React workbench
    ↓ typed REST/OpenAPI
FastAPI control plane
    ├── streaming import adapters
    ├── deterministic / local / generic-HTTP annotation adapters
    ├── evidence retrieval and bounded research planner
    ├── measurement plugin registry
    └── durable AnalysisRun / AnalysisTask state
           ↓
PostgreSQL 18 + pgvector (canonical) / SQLite (development)
    ├── immutable source and revisions
    ├── reversible semantic observations
    ├── results, provenance, hypotheses, traces
    └── content-addressed object store
```

The model proposes structured outputs. The control plane validates schemas, enforces privacy, records provenance, and writes results. Models never receive database, shell, or external-action authority.

The first research planner is single-loop and read-only. Its tool enum prevents arbitrary SQL or shell execution. Multi-agent orchestration is deliberately absent until an evaluation demonstrates that a bounded single planner misses material evidence.

## Source-backed participant identity

`Participant.display_name` is presentation data, never an identity key. Import adapters may create a `ParticipantIdentity` only from a stable source identifier such as Telegram `author_<user_id>`, a profile login, a WhatsApp sender address, or the corresponding native export ID.

Telegram HTML sometimes replaces an author with `Deleted Account` and removes both ID and login. Those messages retain the exact source name and a local `unresolved_sender_run_id` in `Message.raw_metadata`, while `Message.sender_id` remains null. Consecutive `joined` messages inherit the same unresolved run for source reconstruction, but the run is not promoted to a person. Consequently these messages remain readable in the timeline yet are excluded from participant rankings, dyadic graphs, roles, and other person-level measurements. This deliberately prefers missingness over falsely merging unrelated people by display name.
