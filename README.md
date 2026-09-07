# Hetaira Observatory

Hetaira is a local-first, Russian-first computational conversation observatory. It preserves imported Telegram and WhatsApp data as immutable source evidence, derives versioned observations and measurements, and keeps every interpretation navigable back to exact message spans.

The current Foundation release implements the first complete vertical slice:

- streaming Telegram JSON and WhatsApp TXT imports with cumulative immutable snapshots;
- immutable messages and revisions, Unicode span hashes, sessions, episodes, participants, replies, and attachments;
- Russian codebook-backed deterministic dialogue acts, propositions, stance, epistemics, grounding, and argument cues;
- plugin-validated participation and explicit-reply reciprocity measurements;
- a persisted multidimensional Overview covering temporal, participation, reply, network, role, lexical, and health-primitive dimensions;
- L0 source → L1 observation → L2 measurement → L3 interpretation evidence chains;
- traceable Russian lexical retrieval and a bounded research-plan contract;
- loopback-only local model routing with budgets, JSON Schema validation, and invocation audits;
- a full React analysis microscope and an explicitly unvalidated 100-message English demo.

High-level influence, power, persuasion, coalition, forecasting, and pivotal-moment systems remain gated behind validated primitive measurements. The ontology already reserves their evidence/provenance contracts; the application does not invent direct scores for them.

## Quick start

Requirements: Python 3.12, Node 22+, pnpm, and optionally Docker for PostgreSQL.

```bash
make install
make backend
# separate terminal
make frontend
```

Open [http://localhost:5173](http://localhost:5173). API documentation is at [http://localhost:8000/docs](http://localhost:8000/docs).

The default zero-configuration database is SQLite. PostgreSQL 18 + pgvector is the intended canonical deployment:

```bash
docker compose up -d postgres
cp .env.example .env
# enable the PostgreSQL PROMETHEUS_DATABASE_URL compatibility setting in .env
.venv/bin/python -m alembic -c backend/alembic.ini upgrade head
```

## Verification

```bash
make test
make lint
pnpm --dir frontend build
```

Generate a scale fixture without keeping the full message list in memory:

```bash
.venv/bin/python scripts/generate_scale_fixture.py --count 1000000 --output scale-1m.json
```

Run the interruption/restart and bounded-memory gate:

```bash
PROMETHEUS_DATABASE_URL=postgresql+psycopg://prometheus:prometheus@localhost:5432/prometheus \
  .venv/bin/python scripts/run_scale_gate.py \
  --count 1000000 --fixture /tmp/hetaira-scale-1m.json \
  --object-root /tmp/hetaira-scale-objects
```

Create and inspect the corpus-specific Russian reference pilot (also available through the **Разметка** UI). It samples 80 anchor messages from the complete snapshot, marks 24 for blind A/B annotation, and keeps FINAL adjudication separate:

```bash
.venv/bin/python scripts/gold_ru_pilot.py create --corpus-id <corpus-id>
.venv/bin/python scripts/gold_ru_pilot.py status <annotation-set-id>
.venv/bin/python scripts/gold_ru_pilot.py export <annotation-set-id> --output reference-ru-pilot-v1.json
```

## Source map

- `backend/src/prometheus_observatory/models.py` — persistence ontology and immutability enforcement.
- `backend/src/prometheus_observatory/ontology.py` — public evidence, provenance, measurement, and finding contracts.
- `backend/src/prometheus_observatory/importers/` — Telegram and WhatsApp adapters.
- `backend/src/prometheus_observatory/analyzer.py` — deterministic Russian foundation pipeline.
- `backend/src/prometheus_observatory/retrieval.py` — snapshot-scoped traceable retrieval.
- `backend/src/prometheus_observatory/observatory.py` — persisted multidimensional descriptive analysis.
- `frontend/src/` — live analysis workbench.
- `docs/` — scientific specification, annotation manual, architecture, and validation rules.

## Safety boundary

This deployment is local-model-only. New corpora default to `LOCAL_ONLY`, the runtime rejects remote model adapters even if a corpus record carries an older API-capable policy, and model cost must remain zero. Retrieved content is always data, never model authority.
