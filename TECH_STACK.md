# LOOP Tech Stack And Working

LOOP is a workflow intelligence platform that finds repetitive work from activity
logs, generates automation candidates, and promotes automations through a trust
ladder before they are allowed to run unattended.

## 1. Tech Stack

### Backend

- Python 3.11
- FastAPI for the API server
- SQLAlchemy async ORM
- SQLite by default using `aiosqlite`
- Postgres optional through Docker using `asyncpg`
- Pydantic and `pydantic-settings` for schemas and configuration
- scikit-learn, NumPy and RapidFuzz for clustering and similarity scoring
- Local Ollama API for optional LLM-backed generation
- `sse-starlette` for live server-sent event updates

### Frontend

- Next.js 15
- React 19
- TypeScript
- Tailwind CSS
- TanStack React Query
- Recharts
- Zustand

### Browser Collectors

- Chrome extension
- Edge extension
- JavaScript content scripts and background scripts
- Metadata-first activity capture with consent, pause and revoke support

### Tooling And Infrastructure

- Makefile commands for setup, seed, demo, dev and checks
- Docker Compose for Postgres, API and web console
- Pytest for backend tests
- Ruff for Python linting
- MyPy for Python type checking
- TypeScript checking for frontend
- OpenAPI contract export

## 2. Model Used

The application is configured to use a free local open-source model through
Ollama.

```env
LOOP_LLM_PROVIDER=ollama
LOOP_LLM_MODEL=qwen2.5:7b-instruct
LOOP_OLLAMA_BASE_URL=http://localhost:11434
LOOP_OLLAMA_VISION_MODEL=
```

The same default exists in the backend configuration:

```python
llm_provider: str = "ollama"
llm_model: str = "qwen2.5:7b-instruct"
ollama_base_url: str = "http://localhost:11434"
ollama_vision_model: str = ""
```

The model is optional. LOOP can run without Ollama because every text
LLM-backed feature has a deterministic fallback.

If Ollama is running and the configured model has been pulled, LOOP calls the
local model using Ollama's `/api/chat` endpoint. If Ollama is not running, the
model is missing, or the call fails after retries, LOOP uses local heuristic
logic instead.

LLM-backed features include:

- flow definition generation
- SOP generation
- workflow variance scoring
- field remapping after schema drift
- exception rule proposal
- screen-recording frame interpretation

The one feature that genuinely needs a vision model is reading screen-recording
frames. The rest of the system still works without a model.

Recommended local setup:

```bash
brew install ollama
ollama serve
ollama pull qwen2.5:7b-instruct
ollama pull gemma3:4b
```

To enable screen-recording ingestion after pulling the vision model, set:

```env
LOOP_OLLAMA_VISION_MODEL=gemma3:4b
```

## 3. How The Application Works

LOOP turns activity data into automation opportunities.

```text
CSV / JSONL / prose / browser collector
        ↓
canonical event stream
        ↓
task instances
        ↓
workflow signatures
        ↓
workflow clusters
        ↓
scoring and ROI calculation
        ↓
automation flow + SOP generation
        ↓
replay / shadow / live execution
        ↓
trust ladder promotion or demotion
```

### Step 1: Ingest Activity

The system can receive activity from:

- CSV uploads
- JSONL uploads
- plain-English workflow descriptions
- browser extension events
- synthetic demo data

All inputs are normalized into a canonical event stream.

Example event idea:

```text
gmail read invoice_email
pdf extract fields
sheets create row
gmail send confirmation
```

## 4. Workflow Detection

LOOP groups events into task instances using:

- idle time gaps
- explicit session changes
- hard context resets such as navigation or unrelated app activity

Each task instance becomes a workflow signature.

Example:

```text
gmail:read:invoice_email → pdf:extract:fields → sheets:create:row → gmail:send:confirmation
```

The clustering system compares workflow signatures using:

- sequence similarity
- set overlap
- embedding similarity or TF-IDF fallback

This helps the system detect repeated workflows even when people do the same
task with small variations.

## 5. Scoring

Each detected workflow is scored for business value and automation suitability.

The scoring includes:

- number of observed instances
- number of distinct users
- annual hours estimate
- context-switching cost
- interruption tax
- variance
- automatability
- priority
- whether the workflow should not be automated

If a workflow is too variable or judgment-heavy, LOOP can mark it as:

```text
DO NOT AUTOMATE
```

This is important because not every repetitive-looking process is a good
automation candidate.

## 6. Automation Generation

For good candidates, LOOP generates:

- a runnable flow definition
- a human-readable SOP
- triggers
- steps
- dependencies
- approval guards
- irreversible-action checks

If the local LLM is available, the flow and SOP can be generated with Ollama. If
not, the backend generates them from the observed workflow signature and event
fields.

## 7. Execution Modes

LOOP supports three execution modes.

### Replay

The automation is tested against historical events. This checks how well the
automation would have performed in the past.

### Shadow

The automation runs beside the human and compares its output with the human's
real decisions. It does not take action directly.

### Live

The automation can take real action, but only after it has earned trust.

## 8. Trust Ladder

The trust ladder controls how much autonomy an automation is allowed to have.

```text
OBSERVE → SUGGEST → SHADOW → ASSIST → AUTONOMOUS
```

Promotion depends on measured agreement during shadow runs.

Important settings:

```env
LOOP_SHADOW_WINDOW=5
LOOP_SHADOW_PROMOTION_THRESHOLD=0.90
LOOP_SHADOW_MIN_RUNS=5
LOOP_DEMOTION_LOOKBACK=3
```

If recent runs show critical mismatches, the automation is demoted.

## 9. Privacy And Safety

LOOP is designed to avoid becoming a monitoring tool.

Privacy and safety features include:

- metadata-only capture by default
- field names captured, not field values
- URL query values stripped
- consent enforced before ingestion
- pause support
- source revocation deletes related events
- reporting at group level using the organisational user threshold
- mock connectors enabled by default

The default connector setting is:

```env
LOOP_ENABLE_MOCK_CONNECTORS=true
```

When this is true, connectors have no real side effects.

## 10. Database

By default, LOOP uses SQLite:

```env
LOOP_DATABASE_URL=sqlite+aiosqlite:///./loop.db
```

Docker Compose uses Postgres:

```text
postgresql+asyncpg://loop:loop@postgres:5432/loop
```

## 11. Frontend Configuration

The Next.js console talks to the API using:

```env
NEXT_PUBLIC_API_BASE=http://localhost:8000
```

The frontend can also run from committed fixtures:

```env
NEXT_PUBLIC_API_MOCK=1
```

This allows frontend development without running the Python backend.

## 12. Main Commands

Install everything:

```bash
make setup
```

Generate demo data:

```bash
make seed
```

Run API and frontend:

```bash
make dev
```

Reset to demo state:

```bash
make demo
```

Run with Docker:

```bash
docker compose up --build
```

Run checks:

```bash
make check
```

## 13. Local URLs

```text
API:     http://localhost:8000
Docs:    http://localhost:8000/docs
Console: http://localhost:3000
```

## 14. Summary

LOOP is built as a local-first full-stack application:

- FastAPI backend
- Next.js frontend
- SQLite default database
- optional Postgres through Docker
- optional local Ollama integration
- browser collector for real work observation
- deterministic fallback logic for offline demos

The core idea is to move from observed human work to trusted automation:

```text
Observe work → detect workflows → score opportunities → generate automation
→ replay → shadow → promote only when reliable
```
