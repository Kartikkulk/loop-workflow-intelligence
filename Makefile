# LOOP — workflow intelligence platform
#
# Everything runs locally with no external services: SQLite by default, mock
# connectors, and a deterministic fallback for every AI feature. `make setup &&
# make dev` is enough from a clean clone.

SHELL := /bin/bash
API := apps/api
WEB := apps/web
PY := $(API)/.venv/bin/python
UV := $(shell command -v uv 2>/dev/null)

.DEFAULT_GOAL := help
.PHONY: help setup setup-api setup-web dev api web seed demo test test-api test-web \
        test-collector check check-all lint typecheck fmt build clean reset-db logs \
        contract contract-check fixtures web-mock collectors

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# ── setup ──────────────────────────────────────────────────────────────────

setup: setup-api setup-web ## Install everything
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example")
	@echo ""
	@echo "Ready. Run 'make seed' then 'make dev'."

setup-api: ## Create the Python venv and install API dependencies
ifndef UV
	@echo "uv is required: curl -LsSf https://astral.sh/uv/install.sh | sh" && exit 1
endif
	cd $(API) && uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev]"

setup-web: ## Install frontend dependencies
	npm install

# ── running ────────────────────────────────────────────────────────────────

dev: ## Run API and console together (Ctrl-C stops both)
	@test -f $(API)/loop.db || $(MAKE) seed
	@echo "API     http://localhost:8000  (docs at /docs)"
	@echo "Console http://localhost:3000"
	@trap 'kill 0' EXIT INT TERM; \
	  ( cd $(API) && .venv/bin/python -m uvicorn app.main:app --reload --port 8000 ) & \
	  ( npm run dev --workspace $(WEB) ) & \
	  wait

api: ## Run only the API
	cd $(API) && .venv/bin/python -m uvicorn app.main:app --reload --port 8000

web: ## Run only the console
	npm run dev --workspace $(WEB)

web-mock: ## Run the console from fixtures — no Python, no backend needed
	NEXT_PUBLIC_API_MOCK=1 npm run dev --workspace $(WEB)

# ── data ───────────────────────────────────────────────────────────────────

seed: ## Regenerate synthetic data, run detection, build starting automations
	cd $(API) && .venv/bin/python scripts/seed.py --export

contract: ## Regenerate contracts/openapi.json (run after any API change)
	cd $(API) && .venv/bin/python scripts/export_openapi.py

contract-check: ## Fail if the committed contract is stale
	cd $(API) && .venv/bin/python scripts/export_openapi.py --check

fixtures: ## Capture live API responses as frontend fixtures (needs `make api`)
	cd $(API) && .venv/bin/python scripts/export_fixtures.py

collectors: ## Assemble the browser extensions into collectors/dist/
	node collectors/build.mjs

demo: ## Reset to the exact known-good demo starting state
	cd $(API) && rm -f loop.db && .venv/bin/python scripts/seed.py
	@echo "Demo state ready. See DEMO.md for the run sheet."

reset-db: ## Delete the local database
	rm -f $(API)/loop.db $(API)/test_loop.db

# ── quality ────────────────────────────────────────────────────────────────

test: test-api test-collector ## Run all tests

test-api: ## Run the Python test suite
	cd $(API) && .venv/bin/python -m pytest -q

test-collector: ## Test the browser collector (needs Google Chrome installed)
	npm run test:collector

test-web: ## Typecheck and lint the console
	npm run check --workspace $(WEB)

lint: ## Lint Python
	cd $(API) && .venv/bin/python -m ruff check app scripts tests

typecheck: ## Typecheck Python and TypeScript
	cd $(API) && .venv/bin/python -m mypy app || true
	npm run typecheck --workspace $(WEB)

fmt: ## Auto-fix Python lint issues
	cd $(API) && .venv/bin/python -m ruff check --fix app scripts tests

check: ## Everything CI would run
	cd $(API) && .venv/bin/python -m ruff check app scripts tests
	npm run typecheck --workspace $(WEB)
	npm run lint --workspace $(WEB)
	cd $(API) && .venv/bin/python -m pytest -q
	cd $(API) && .venv/bin/python scripts/export_openapi.py --check

check-all: check test-collector ## check, plus the browser-collector tests

build: ## Production build of the console
	npm run build --workspace $(WEB)

clean: ## Remove build artefacts, caches and the database
	rm -rf node_modules $(WEB)/.next $(WEB)/node_modules
	rm -rf $(API)/.venv $(API)/.pytest_cache $(API)/.ruff_cache $(API)/.mypy_cache
	find $(API) -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -f $(API)/loop.db $(API)/test_loop.db
