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
