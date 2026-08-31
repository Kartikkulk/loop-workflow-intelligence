# LOOP — Claude Code Build Kit

Everything you need to build the hackathon project with Claude Code in your IDE.

**Contents**
1. MCP servers & tools to install *before* you start
2. `CLAUDE.md` — drop this in your repo root first
3. The master build prompt (copy-paste)
4. Follow-up prompts for each phase
5. Troubleshooting prompts

---

# PART 1 — Install these first

## 1.1 MCP servers

Run these in your terminal. Claude Code picks them up automatically.

```bash
# Context7 — live, version-correct docs for Next.js, FastAPI, SQLAlchemy, shadcn.
# THIS IS THE MOST IMPORTANT ONE. Without it Claude writes outdated Next.js 13
# patterns and deprecated SQLAlchemy 1.x syntax.
claude mcp add context7 -- npx -y @upstash/context7-mcp

# Postgres — lets Claude inspect your live schema and run queries while debugging.
claude mcp add postgres -- npx -y @modelcontextprotocol/server-postgres \
  postgresql://loop:loop@localhost:5432/loop

# Playwright — E2E tests AND the browser-automation execution engine for
# demoing an automation that actually clicks through a real web app.
claude mcp add playwright -- npx -y @playwright/mcp@latest

# Filesystem — scoped file access outside the repo (for seed data, recordings).
claude mcp add filesystem -- npx -y @modelcontextprotocol/server-filesystem ~/loop-data

# GitHub — branches, PRs, issues. Set GITHUB_TOKEN in your shell first.
claude mcp add github -- npx -y @modelcontextprotocol/server-github

# Fetch — pulling reference docs and sample data during the build.
claude mcp add fetch -- npx -y @modelcontextprotocol/server-fetch
```

Verify with:

```bash
claude mcp list
```

**Optional but nice:**

```bash
# shadcn/ui component registry — Claude installs components correctly first try
npx shadcn@latest mcp init --client claude

# Sequential thinking — helps on the clustering/pattern-mining algorithms
claude mcp add sequential-thinking -- npx -y @modelcontextprotocol/server-sequential-thinking
```

## 1.2 Local prerequisites

```bash
node -v      # need >= 20
python3 -V   # need >= 3.11
docker -v    # for Postgres
pnpm -v      # npm i -g pnpm
uv --version # curl -LsSf https://astral.sh/uv/install.sh | sh
```

## 1.3 Claude Code settings

Turn these on in your session:

- **Plan Mode** (`Shift+Tab` twice) — use it for Phase 0. Never let it start writing code before you've read the plan.
- **Subagents** — the master prompt tells Claude when to spawn them.
- `/init` — run once after the first scaffold so Claude writes its own `CLAUDE.md` additions.

---

# PART 2 — `CLAUDE.md`

Create this file at your repo root **before** the first prompt. Claude Code reads it on every turn, so it stops re-explaining conventions and stops drifting.

````markdown
# LOOP — Workflow Intelligence Platform

## What this is
Detects repetitive enterprise workflows from activity logs, converts them into
automations, and safely promotes those automations from "suggested" to
"autonomous" through a measured trust ladder.

Hackathon project. Optimise for a working demo, not for scale.

## Stack — locked, do not substitute
- Monorepo: pnpm workspaces + Turborepo
- Frontend: Next.js 15 (App Router), TypeScript strict, Tailwind v4, shadcn/ui,
  TanStack Query v5, Recharts, Zustand
- Backend: Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2.0 (async), Alembic
- DB: PostgreSQL 16 via Docker Compose
- LLM: Anthropic Python SDK, structured output via tool-use
- ML: sentence-transformers (all-MiniLM-L6-v2, local), scikit-learn, rapidfuzz
- Package managers: pnpm (JS), uv (Python)

## Non-negotiable rules
1. NO placeholder code. No `# TODO: implement`, no `pass`, no mock returns
   where real logic belongs. If a function is in the plan, it is fully written.
2. NO hardcoded secrets. Everything through `.env`, documented in `.env.example`.
3. Every API endpoint gets a Pydantic request AND response model.
4. Every DB model gets an Alembic migration.
5. Frontend never calls `fetch` directly — always through `lib/api/` typed clients.
6. Type errors are build failures. `tsc --noEmit` and `mypy` must pass.
7. Prefer boring, correct code over clever code.

## Conventions
- Python: snake_case, full type hints, Google-style docstrings on public fns
- TypeScript: named exports only (no default exports except Next.js pages)
- API routes: `/api/v1/<resource>`, plural nouns, kebab-case multiword
- All timestamps UTC, ISO 8601, stored as `TIMESTAMPTZ`
- All money in minor units (paise/cents) as integers, never floats

## Commands
```bash
make dev        # everything up
make seed       # regenerate synthetic data
make test       # pytest + vitest
make check      # ruff + mypy + tsc + eslint
make demo       # reset to a known-good demo state
```

## Before you finish any task
Run `make check`. If it fails, fix it. Do not report done on a red build.
````

---

# PART 3 — The Master Build Prompt

> Start Claude Code in **Plan Mode**. Paste everything between the lines.
> Read the plan it produces, correct it, *then* let it build.

---
---

You are building **LOOP**, an AI-powered workflow intelligence platform, for a hackathon. Read `CLAUDE.md` in the repo root first — the stack listed there is locked.

## The problem we're solving

Employees spend huge amounts of time on repetitive workflows: data entry, email follow-ups, report preparation, document processing, moving information between systems. LOOP ingests activity logs, finds the repetitive patterns, converts them into real automations, and — this is the differentiator — **safely earns the right to run them autonomously** instead of demanding blind trust on day one.

The judging brief is: move from *"this task is repetitive"* to *"this task can now be automated."* Detection alone is not a product. The automation must actually run.

## Locked scope — the demo domain

**Finance operations at a fictional company, "Northwind Industries."** Five workflow types across 14 employees, 90 days of synthetic activity logs. Do not broaden this. Everything is demoed against this dataset.

The five workflows in the seed data:
1. `invoice_to_ledger` — invoice email arrives → extract fields → append to sheet → send confirmation *(the hero workflow, most polished)*
2. `weekly_vendor_report` — pull rows → aggregate → format → email to 3 recipients
3. `po_matching` — match purchase order to invoice → flag mismatches
4. `expense_approval` — read expense claim → check policy → approve or route
5. `customer_escalation` — high variance, judgement-heavy → **must be flagged as DO-NOT-AUTOMATE**

Workflow 5 exists specifically so the system can demonstrate restraint. Make sure the variance detector actually catches it from the data, rather than it being hardcoded.

---

## The eight features

### F1 — Ingestion & normalisation
Accept activity logs as CSV/JSONL upload, plus a plain-English workflow description as a fallback input path. Normalise everything into a single canonical event stream.

```
Event {
  id, user_id, timestamp, app, action, object_type,
  object_id, duration_ms, payload: JSONB, session_id
}
```

`app` ∈ {gmail, sheets, erp, drive, slack, browser}
`action` ∈ {read, create, update, delete, send, extract, search, navigate}

Include a `POST /api/v1/ingest/describe` endpoint that takes prose ("every Monday I download the vendor report, filter for overdue rows, and email finance") and uses the LLM to synthesise a plausible event sequence. This is the fallback demo path if the log upload misbehaves on stage.

### F2 — Workflow DNA (cross-employee pattern mining)

This is the core algorithmic contribution. Do not shortcut it into a single LLM call.

**Step 1 — Sessionise.** Group events into task instances. Split on gaps > 15 min idle, or on a hard context reset.

**Step 2 — Signature.** Reduce each instance to a canonical sequence with all specific values stripped:
```
[gmail:read:invoice_email] → [pdf:extract:fields]
  → [sheets:append:row] → [gmail:send:confirmation]
```

**Step 3 — Cluster.** Two-stage:
- Fast pass: exact signature hash match
- Fuzzy pass: normalised Levenshtein on the step sequence (rapidfuzz) with threshold 0.82, plus cosine similarity on sentence-transformer embeddings of the signature string. Combine as `0.6 * sequence_sim + 0.4 * embedding_sim`. Agglomerative clustering, average linkage.

**Step 4 — Aggregate.** For each cluster: distinct users, total instances, median duration, frequency per user per week, and the projected annual hours:
```
annual_hours = median_duration_hrs × instances_per_user_per_week × 48 × distinct_users
```

A cluster spanning **> 3 distinct users** gets promoted to an *organisational* opportunity and rendered differently in the UI. This is what turns "saves you 2 hrs/week" into "saves Finance 738 hrs/year."

Write real unit tests for the clustering: identical sequences must cluster, sequences differing by one optional step must cluster, structurally different sequences must not.

### F3 — Scoring, prioritisation & Interruption Tax

For each cluster compute:

- **Time cost** = annual_hours
- **Interruption Tax** — detect context switches (app A → app B → back to A within 10 min). Cost per switch from `INTERRUPTION_COST_MINUTES` env var (default 4). Report separately from raw time; a 4-minute task causing 9 switches/day costs far more than 36 minutes.
- **Automatability score** (0–1) — inverse of variance:
  - step-order entropy across cluster instances
  - parameter value spread
  - distinct branch count
  - free-text/judgement content ratio (LLM-scored, 0–1)
- **Build effort** (1–5, LLM-estimated from step count and integration complexity)
- **Priority** = `(time_cost + interruption_tax) × automatability / build_effort`

Any cluster with `automatability < 0.4` is flagged **DO NOT AUTOMATE** with generated reasoning ("step order varies across 78% of instances; outcome depends on tone and relationship judgement"). Surface these as a first-class list, not an error state.

### F4 — Automation generation + SOP

From a cluster, generate a runnable flow definition:

```json
{
  "id": "auto_inv_ledger_01",
  "trigger": { "type": "email_received", "filter": {...} },
  "steps": [
    { "id": "s1", "type": "extract", "connector": "pdf",
      "inputs": {...}, "outputs": ["vendor","amount","date","po_number"],
      "depends_on": ["email.attachment"] }
  ],
  "guards": { "requires_approval_if": "amount > 1000000",
              "irreversible": ["send_email"] }
}
```

Use Anthropic tool-use for structured output — never parse JSON out of free-form text.

Each `step` **must** declare `depends_on` (field names, selectors, schema keys). F8 self-healing depends entirely on these declarations existing.

Simultaneously generate a **Standard Operating Procedure** markdown doc for the cluster: purpose, trigger, systems touched, numbered steps, known exceptions, owner, estimated duration. Downloadable. This delivers value before any automation runs and is a strong slide on its own.

### F5 — Execution engine (build once, use three ways)

One engine, three modes. This is the architectural insight that makes the scope achievable — say so in the README.

| Mode | Side effects | Compared against |
|------|-------------|------------------|
| `replay` | mocked | historical log |
| `shadow` | mocked | live human actions |
| `live` | real | nothing |

Connectors implement a common interface with a real and a mock implementation, switched by `ENABLE_MOCK_CONNECTORS`:
```python
class Connector(Protocol):
    async def execute(self, step: Step, ctx: Context) -> StepResult: ...
```

Ship: `GmailConnector`, `SheetsConnector`, `PdfConnector`, `ErpConnector`, `BrowserConnector`. For the hackathon all five can be mock-only, but the interface must be real — a judge asking "could this hit real Gmail?" should get "yes, swap one class."

### F6 — Replay dry-run (backtest)

`POST /api/v1/automations/{id}/replay?days=30`

Pull historical trigger events, execute each in `replay` mode, diff against what the human actually did in the log. Return:

```json
{ "total": 50, "correct": 47, "accuracy": 0.94,
  "failures": [
    { "event_id": "e_12", "reason": "multi-currency, no EUR rule",
      "expected": {...}, "predicted": {...}, "diff_fields": ["amount"] }
  ] }
```

Do not round accuracy up and do not hide the failures — naming your three failure modes before a judge finds them reads as maturity, not weakness.

### F7 — Trust Ladder & Shadow Mode ⭐ *the centrepiece*

Five levels: `OBSERVE → SUGGEST → SHADOW → ASSIST → AUTONOMOUS`

In `SHADOW`, when a trigger fires the automation predicts what it *would* do and records it. The human does the task for real. Diff the two:

```python
ShadowRun {
  automation_id, trigger_event_id,
  predicted: dict, observed: dict,
  field_matches: dict[str, bool],
  score: float,          # weighted; critical fields count double
  critical_mismatch: bool
}
```

Promotion policy, configurable via env:
```
rolling_window = 5
promote_if  avg(score) >= SHADOW_PROMOTION_THRESHOLD (default 0.90)
        AND critical_mismatch_count == 0
        AND runs >= 5
demote_if   any critical_mismatch in last 3 runs
```

Expose promotion state over **SSE** at `/api/v1/automations/{id}/stream` so the frontend confidence bar animates live. This is the stage moment: the bar fills, the greyed-out "Promote to Autonomous" button turns blue. Build a `POST /api/v1/demo/simulate-shadow-run` endpoint so this can be triggered on cue during the pitch.

Demotion matters as much as promotion — a system that can only go up isn't a safety mechanism.

### F8 — Self-healing + exception learning

**Drift detection.** When a step fails or a `depends_on` field resolves null, capture the *current* schema (actual column headers / API response shape / DOM) and ask the LLM to propose a remapping with a confidence score. Emit a patch:

```json
{ "step_id": "s3", "field": "source_field",
  "from": "Vendor", "to": "Supplier Name",
  "confidence": 0.94, "auto_applicable": true }
```

Auto-apply if `confidence > 0.9` AND the step is non-destructive. Otherwise queue for approval. Render as a diff in the UI. **Include a `POST /api/v1/demo/break-schema` endpoint that renames a column in the seed data**, so this can be triggered live on stage.

**Exception learning.** Executions below confidence threshold route to a human queue with a generated reason. Capture `(input_features → human_decision)`. After ≥3 similar exceptions, propose a branch rule:
```
IF amount > 1000000 THEN route to manager approval
[Accept] [Modify] [Dismiss]
```
Accepted rules patch the flow definition. Track **coverage %** per automation over time and chart it — a rising line is what makes the system look alive rather than static.

---

## Backend structure

```
apps/api/
  app/
    main.py
    config.py                 # pydantic-settings, reads .env
    db/ {session.py, base.py}
    models/                   # events, workflows, clusters, automations,
                              # shadow_runs, executions, exceptions, patches
    schemas/                  # Pydantic v2 request/response
    api/v1/
      ingest.py  clusters.py  automations.py  shadow.py
      executions.py  exceptions.py  patches.py  demo.py  stream.py
    services/
      normaliser.py           # F1
      sessioniser.py          # F2 step 1
      signature.py            # F2 step 2
      clustering.py           # F2 step 3
      scoring.py              # F3 + interruption tax
      generator.py            # F4 flow + SOP
      engine.py               # F5 execution engine
      replay.py               # F6
      trust.py                # F7 promotion policy
      healing.py              # F8 drift + patches
      exceptions.py           # F8 rule learning
    connectors/
      base.py  gmail.py  sheets.py  pdf.py  erp.py  browser.py
      mock/                   # mirror implementations
    llm/
      client.py               # Anthropic wrapper: retry, cost log, caching
      tools.py                # tool-use schemas for structured output
      prompts/                # .md files, NOT inline f-strings
  alembic/
  tests/
  pyproject.toml
```

Put every LLM prompt in `llm/prompts/*.md` and load them at runtime. Prompts buried in f-strings are impossible to iterate on under time pressure.

Wrap the Anthropic client with retry-with-backoff, a token/cost counter written to a log, and an in-memory response cache keyed on prompt hash. During a hackathon you will re-run the same analysis fifty times; the cache saves both money and demo latency.

## API surface

```
POST   /api/v1/ingest/upload
POST   /api/v1/ingest/describe
GET    /api/v1/clusters
GET    /api/v1/clusters/{id}
GET    /api/v1/clusters/{id}/sop
POST   /api/v1/clusters/{id}/generate-automation
GET    /api/v1/automations
GET    /api/v1/automations/{id}
POST   /api/v1/automations/{id}/replay
POST   /api/v1/automations/{id}/promote
POST   /api/v1/automations/{id}/demote
GET    /api/v1/automations/{id}/shadow-runs
GET    /api/v1/automations/{id}/stream        # SSE
GET    /api/v1/exceptions
POST   /api/v1/exceptions/{id}/resolve
GET    /api/v1/patches
POST   /api/v1/patches/{id}/apply
GET    /api/v1/analytics/roi
POST   /api/v1/demo/reset
POST   /api/v1/demo/simulate-shadow-run
POST   /api/v1/demo/break-schema
```

## Frontend structure & screens

```
apps/web/
  app/
    (dashboard)/
      page.tsx                    # 1. Discovery
      clusters/[id]/page.tsx      # 2. Workflow detail
      automations/page.tsx        # 3. Automation list
      automations/[id]/page.tsx   # 4. Trust ladder ⭐
      exceptions/page.tsx         # 5. Exception queue
      roi/page.tsx                # 6. ROI dashboard
  components/
    trust-ladder/                 # the flagship component
    workflow-graph/               # step visualisation
    ui/                           # shadcn
  lib/api/                        # typed clients — nothing calls fetch directly
```

**Screen 1 — Discovery.** Detected clusters as cards, sorted by priority. Org-level clusters (>3 users) visually distinct with a stacked-avatar row. Separate collapsed section: "Not recommended for automation" with reasoning.

**Screen 2 — Workflow detail.** Step-sequence graph, the users who perform it, time + interruption tax breakdown, automatability gauge, SOP download, "Generate automation" CTA.

**Screen 3/4 — Trust ladder.** The five rungs as a horizontal stepper, current level highlighted. Live confidence bar fed by SSE. Shadow-run history table with per-field ✓/✗. Promote button disabled with a tooltip explaining exactly what's still required ("needs 2 more runs above 90%"). Replay results panel with the failure list expanded by default.

**Screen 5 — Exceptions.** Queue with the AI's stated reason for uncertainty, resolve action, and suggested-rule cards.

**Screen 6 — ROI.** Hours saved (actual vs projected), interruption tax recovered, coverage trend line per automation, automations by trust level.

Design: dark theme default, clean and dense, `Inter`, generous whitespace, subtle motion on state transitions only. It should look like a product, not a dashboard template. No emoji in the UI.

## Seed data generator

`scripts/seed.py` — deterministic (fixed seed), regenerable, and it must produce data with real structure, not noise:

- 14 users across 3 teams (AP, AR, FP&A)
- 90 days, ~12,000 events
- 5 workflow types with **realistic variance**: optional steps that appear 30% of the time, occasional out-of-order steps, a handful of genuine anomalies
- Workflow 1 performed by 6 users → must cluster as organisational
- Workflow 5 with genuinely high step-order entropy → must be caught by the variance detector, **not** hardcoded as do-not-automate
- Interleaved context switches so the Interruption Tax has something real to measure
- A schema-change event at day 60 (`Vendor` → `Supplier Name`) so self-healing has a genuine drift to find

The demo's credibility rests on this file. If the patterns are fake, the detection is theatre. Spend real effort here.

## Required deliverables

- `README.md` — problem, solution, architecture diagram (mermaid), the eight features with screenshots-placeholders, full setup, API table, "how the three execution modes share one engine" section, demo script with timings, known limitations, what's next
- `.env.example` — every variable, commented, with safe defaults
- `docker-compose.yml` — postgres + api + web
- `Makefile` — `dev`, `seed`, `test`, `check`, `demo`, `clean`
- `DEMO.md` — minute-by-minute presentation script with the exact commands to run and what to say
- `ARCHITECTURE.md` — data flow, why each design decision was made
- Tests: pytest for clustering, scoring, trust policy, replay diff; vitest for the trust-ladder component
- Working `docker compose up` from a clean clone

---

## Build order — checkpoint after each phase

**Phase 0 — Plan.** Do not write code. Produce a written plan: file tree, DB schema, API contracts, open questions. Flag anything ambiguous. Wait for my approval.

**Phase 1 — Foundation.** Monorepo, Docker Compose, FastAPI skeleton with `/health`, Next.js skeleton, DB models, Alembic initial migration, `.env.example`, Makefile. Checkpoint: `make dev` works, both apps serve.

**Phase 2 — Data & detection.** Seed generator, ingestion, normaliser, sessioniser, signature, clustering, scoring, interruption tax. Unit tests for clustering. Checkpoint: `make seed` produces data, `GET /clusters` returns correct clusters including the do-not-automate flag on workflow 5.

**Phase 3 — Discovery UI.** Screens 1 and 2, typed API clients, SOP generation and download. Checkpoint: clusters visible and browsable, SOP downloads.

**Phase 4 — Generation & engine.** Flow generation via tool-use, connector interfaces, mock connectors, execution engine, replay. Checkpoint: replay on the hero workflow returns realistic accuracy with named failures.

**Phase 5 — Trust ladder.** ⭐ Shadow runs, scoring, promotion policy, SSE, screens 3 and 4, demo simulate endpoint. Checkpoint: confidence bar animates live and the promote button unlocks.

**Phase 6 — Healing & exceptions.** Drift detection, patch generation and diff UI, exception queue, rule learning, coverage tracking. Checkpoint: `break-schema` triggers a patch proposal within seconds.

**Phase 7 — ROI, docs, polish.** Screen 6, README, DEMO.md, ARCHITECTURE.md, `make demo` reset, full `make check` green.

**Use subagents** for independent work — e.g. seed generator, clustering algorithm, and the frontend shell can be built in parallel. Do not parallelise anything that shares a file.

## Definition of done for every task

1. `make check` passes — ruff, mypy, tsc, eslint all clean
2. No `TODO`, no `pass`, no placeholder returns
3. New env vars added to `.env.example` with comments
4. New endpoints have Pydantic request AND response models
5. New models have a migration
6. It actually runs — you tested it, you didn't assume

Start with Phase 0. Give me the plan.

---
---

# PART 4 — Phase follow-up prompts

Paste these one at a time as you clear checkpoints.

**After approving the plan:**
> Plan approved. Execute Phase 1. Stop at the checkpoint and show me the output of `make dev` and `make check`.

**Phase 2:**
> Phase 1 verified. Execute Phase 2. The seed generator is the highest-stakes file in the project — the patterns must be genuinely detectable, not hardcoded. Write it first, then write the clustering tests against it, then make them pass. Show me `GET /api/v1/clusters` output at the checkpoint.

**Phase 3:**
> Phase 2 verified. Execute Phase 3. Discovery UI. Use the shadcn MCP for components. Dark theme, dense, product-grade — no template look. Screenshot the discovery screen when done.

**Phase 4:**
> Phase 3 verified. Execute Phase 4. Remember: ONE execution engine with three modes, not three engines. If you find yourself writing similar code twice, stop and refactor to the shared engine.

**Phase 5:**
> Phase 4 verified. Execute Phase 5 — this is the centrepiece, spend proportionally more effort here. The confidence bar animating live over SSE is the moment the demo is won or lost. Build the demo simulate endpoint so I can trigger runs on cue during the pitch.

**Phase 6:**
> Phase 5 verified. Execute Phase 6. Verify by calling `break-schema` and confirming a patch appears in the UI within 5 seconds.

**Phase 7:**
> Phase 6 verified. Execute Phase 7. The README should be good enough that a judge who never sees the demo still understands why this beats a detection-only tool. DEMO.md needs exact commands and exact timings for a 5-minute pitch.

---

# PART 5 — Troubleshooting prompts

**Outdated code:**
> Use the Context7 MCP to fetch current docs for <library> before fixing this. You're writing a deprecated pattern.

**Scope creep:**
> Stop. Re-read the locked scope in CLAUDE.md. Remove anything not in the eight features and finish Phase N first.

**Placeholder code appears:**
> There are placeholder implementations in <files>. CLAUDE.md rule 1 forbids these. Implement them fully now.

**Time pressure — the cut list, in this order:**
> We have N hours left. Cut in this order and tell me what you cut: Screen 6 ROI page → exception rule learning (keep the queue) → PO matching + expense workflows in seed (keep 3) → browser connector → E2E tests. Never cut: Workflow DNA clustering, replay, trust ladder, self-healing.

**Demo prep:**
> Freeze features. Run through DEMO.md end to end three times, fix anything that breaks or is slow, and make `make demo` reliably reset to the exact starting state.

---

## One warning

Claude Code will happily build all eight features and leave you with an impressive repo you cannot demo. **Phase 5 is the project.** If you have to choose between polishing anything else and making the trust ladder flawless, choose the trust ladder every time.
