.PHONY: install dev backend frontend test lint

install:
	python3.12 -m venv .venv
	.venv/bin/pip install -e 'backend[dev]'
	pnpm --dir frontend install

backend:
	.venv/bin/uvicorn prometheus_observatory.main:app --app-dir backend/src --reload --port 8000

frontend:
	pnpm --dir frontend dev

dev:
	@echo "Run 'make backend' and 'make frontend' in separate terminals."

test:
	.venv/bin/pytest backend/tests
	pnpm --dir frontend test -- --run

lint:
	.venv/bin/ruff check backend/src backend/tests backend/alembic scripts
	pnpm --dir frontend lint
