# LOOP — Workflow Intelligence Platform

## What this is
Detects repetitive enterprise workflows from activity logs, converts them into
automations, and safely promotes those automations from "suggested" to
"autonomous" through a measured trust ladder.

Hackathon project. Optimise for a working demo, not for scale.

## Stack — as built
- Monorepo: npm workspaces (pnpm was specified but is not installed on the dev machine)
- Frontend: Next.js 15 (App Router), TypeScript strict, Tailwind v3.4, TanStack
  Query v5, Recharts. Tailwind v4 requires Node 20; this machine runs Node 18.
- Backend: Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0 (async)
- DB: SQLite by default (zero infra), Postgres 16 via Docker Compose
- LLM: a local model through Ollama (`qwen2.5:7b-instruct`), structured output
  via JSON-schema `format`, with a deterministic fallback for every call so the
  product runs with no model installed and nothing ever leaves the machine
- ML: scikit-learn + rapidfuzz. sentence-transformers is optional
  (`pip install -e ".[embeddings]"`); without it, embeddings come from a
  character-n-gram TF-IDF projection, which performs comparably on strings this
  short and avoids a 2GB torch download.
- Package managers: npm (JS), uv (Python)

## Non-negotiable rules
1. NO placeholder code. No `# TODO: implement`, no bare `pass`, no mock returns
   where real logic belongs.
2. NO hardcoded secrets. Everything through `.env`, documented in `.env.example`.
3. Every API endpoint gets a Pydantic request AND response model.
4. Frontend never calls `fetch` directly — always through `lib/api/`.
5. `make check` must pass: ruff, tsc, eslint, pytest.
6. Prefer boring, correct code over clever code.
7. Never inflate a number. If accuracy is 0.9275, report 0.9275. If coverage
   cannot account for guard holds, fix coverage rather than the wording.

## Conventions
- Python: snake_case, full type hints, Google-style docstrings on public fns
- TypeScript: named exports only (except Next.js pages)
- API routes: `/api/v1/<resource>`, plural nouns
- All timestamps UTC, ISO 8601, stored as `TIMESTAMPTZ`
- All money in minor units (paise) as integers, never floats
- Comments explain *why*, never *what*. No comment should restate the code.

## Architectural invariants — do not break these
- Detection is a pure function of the event log. Re-running it must produce the
  same clusters. Nothing downstream of the log is authoritative.
- The seed generator never labels a workflow do-not-automate. That conclusion is
  earned by the variance detector from the data, or it is not a feature.
- `replay` and `shadow` force mock connectors in the engine, not in each
  connector, so a new connector cannot forget to be safe.
- Guard expressions are evaluated by a restricted comparator, never `eval`. Flow
  definitions are partly model-generated and are therefore untrusted input.
- Promotion is manual; demotion is automatic. A system that waits for permission
  to become safer is not a safety mechanism.

## Commands
```bash
make setup      # install everything
make seed       # regenerate synthetic data + run detection
make dev        # API on :8000, console on :3000
make test       # pytest
make check      # ruff + tsc + eslint + pytest
make demo       # reset to the known-good demo state
```

## Before you finish any task
Run `make check`. If it fails, fix it. Do not report done on a red build.
