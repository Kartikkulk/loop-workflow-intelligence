# Getting Started on Windows — Step by Step

A complete, from-scratch guide to installing and running **LOOP** on Windows
(PowerShell), then using the application screen by screen.

This guide uses **plain Python + pip** instead of `uv`, and Windows-style paths
(`.venv\Scripts\python.exe`), so you don't need the `make` targets — those assume
a Unix shell and won't run on Windows as-is.

> Everything runs locally. No Docker, no Postgres, and **no API key** required.
> Every AI feature has a deterministic fallback that works offline.

---

## 0. Prerequisites

Check what you have. Open PowerShell in the project root
(`d:\AI_Agent_loop\loop-workflow-intelligence`) and run:

```powershell
python --version   # need 3.11 or newer (3.14 works)
node --version     # need 18.18 or newer
```

- **Python** — from [python.org](https://www.python.org/downloads/) or the
  Microsoft Store. Make sure "Add to PATH" is checked during install.
- **Node.js** — from [nodejs.org](https://nodejs.org/) (LTS is fine).

You do **not** need `uv`, Docker, or an Anthropic API key.

---

## 1. Install the backend (API)

The backend is a FastAPI app in `apps\api`. Create a virtual environment and
install its dependencies **once**.

```powershell
# from the project root
cd apps\api

# create the virtual environment
python -m venv .venv

# upgrade pip (optional but recommended)
.venv\Scripts\python.exe -m pip install --upgrade pip

# install the API and its dev dependencies (editable install)
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

This pulls in FastAPI, SQLAlchemy, scikit-learn, numpy, anthropic, and the test
tools. It takes a few minutes the first time.

> **Why `.venv\Scripts\python.exe` and not `.venv\Scripts\activate`?**
> Calling the interpreter directly always works, even if PowerShell's execution
> policy blocks the activation script. If you'd rather activate:
> `.venv\Scripts\Activate.ps1` (then you can just type `python`).

---

## 2. Create the environment file

```powershell
# still in apps\api's parent — run from the project root
cd ..\..
Copy-Item .env.example .env
```

The defaults work out of the box (SQLite + mock connectors + deterministic AI).

**Optional** — to enable richer LLM-generated output, add your key:

```powershell
Add-Content .env "ANTHROPIC_API_KEY=sk-ant-..."
```

The console's **System** page shows which path is active and any spend.

---

## 3. Install the frontend (console)

The console is a Next.js app. Install its dependencies from the project root:

```powershell
# from the project root
npm install
```

---

## 4. Seed the database

This generates ~9,000 synthetic events, runs workflow detection, and builds the
starting automations. Run it from `apps\api`:

```powershell
cd apps\api
.venv\Scripts\python.exe scripts\seed.py --export
cd ..\..
```

You should see something like:

```
seeded: 9141 events, 4 workflows detected (1 flagged do-not-automate),
        628 projected annual hours, 3 automation(s) generated.
```

This creates `apps\api\loop.db`. To reset to a clean known-good state later, just
re-run this command (it rebuilds the database).

---

## 5. Run the application

You need **two terminals** — one for the API, one for the console. On Windows
there is no `make dev` to run both at once.

**Terminal 1 — API** (from `apps\api`):

```powershell
cd apps\api
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Leave it running. The API is now at:
- API base: <http://localhost:8000>
- Interactive docs: <http://localhost:8000/docs>

**Terminal 2 — console** (from the project root):

```powershell
npm run dev --workspace apps/web
```

Leave it running too. Then open the console:

- **<http://localhost:3000>**

> **Frontend only, no Python?** If you just want to browse the UI against
> fixture data, skip the API and run:
> `$env:NEXT_PUBLIC_API_MOCK=1; npm run dev --workspace apps/web`

To stop either server, press `Ctrl+C` in its terminal.

---

## 6. Using the application, screen by screen

The console has seven screens. Here's a guided tour that walks the full product
story — from "where does the data come from" to "this automation earned the
right to run unattended."

### Observation — where the data comes from
The tiers of data source (prose, log upload, browser extension, OAuth, desktop
agent, screen recording), what each can and cannot see, and per-source
pause/revoke. Metadata only: it records that a field named `amount` was filled,
never the value you typed.

### 1. Discovery — what LOOP found
The landing screen. Four stat tiles summarise detected work (hours/year,
interruption tax, etc.). Below, detected workflows are ranked by priority.

- Look for the collapsed **"Not recommended for automation"** section and expand
  it. The **Escalation handling** workflow is flagged **DO NOT AUTOMATE**, with
  the reasoning shown (high step-order variance, many branch points, high
  judgement content). The variance detector reaches this on its own.

### 2. Workflow detail — from workflow to automation
Click a workflow like **Invoice email to confirmation** (the hero, ~819
instances, 6 people).

- The **step graph** shows the observed sequence; marked steps are positions that
  varied between instances.
- The **automatability gauge** exposes all five variance components — nothing is
  hidden.
- Click **Preview SOP** to see the human-readable standard operating procedure.
- Click **Generate / Open automation** to build a runnable flow.

### 3. Automations — the inventory
Every automation with its current trust rung and confidence.

### 4. Trust ladder ⭐ — the centrepiece
Open an automation to reach the ladder: `OBSERVE → SUGGEST → SHADOW → ASSIST →
AUTONOMOUS`.

1. **Run backtest** (90 days) — replays the flow against real historical triggers
   with side effects mocked, and reports honest accuracy with named failure
   modes (e.g. foreign-currency invoices with no conversion rule).
2. **Simulate shadow run** — click it five times. Watch the confidence bar fill
   live (over SSE). In shadow mode the automation records what it *would* do
   while the human does the task for real, then the two are diffed field by
   field (critical fields weighted double).
3. **Promote** — the button unlocks only after 5 runs above 90% with zero
   critical mismatches. The disabled button always states what's still missing.
4. **Force a critical mismatch** (demo control) — the automation demotes itself
   immediately. Promotion is manual; demotion is automatic.
5. Expand any shadow-run row to audit predicted-vs-observed values per field, and
   see the rung-change audit trail.

### 5. Review queue — exceptions and self-healing
- **Break the source schema** (demo control) renames a column across stored
  events, for real. LOOP detects the drift, proposes a remapping, and
  auto-applies it if confidence is high and the step is non-destructive —
  otherwise it waits here for a human.
- Guard holds (e.g. invoices over a threshold) land here with a stated reason.
  Resolve three the same way (e.g. **route_to_manager**) and LOOP proposes a
  branch rule; accept it and the flow is patched.

### 6. Impact — the payoff
Projected vs realised hours, interruption tax recovered, coverage trend, and
automations grouped by trust level. Coverage is measured honestly — an automation
that stops and asks on 15% of cases reports 85%, not 100%.

### System — the connector inventory
Every connector, the live API it would call, and the credentials it would need.
Note: all **execution** connectors are mocked; the interfaces are real.

---

## 7. Driving from the terminal (optional)

You can exercise the whole arc via the API instead of the UI. With the API
running, from PowerShell:

```powershell
# find the highest-value automation id
$AID = (Invoke-RestMethod http://localhost:8000/api/v1/automations).items |
       Sort-Object annual_hours -Descending | Select-Object -First 1 -ExpandProperty id

# honest backtest over 90 days
Invoke-RestMethod -Method Post http://localhost:8000/api/v1/automations/$AID/replay `
  -ContentType application/json -Body '{"days":90}'

# fire five shadow runs
Invoke-RestMethod -Method Post http://localhost:8000/api/v1/demo/simulate-shadow-run `
  -ContentType application/json -Body "{`"automation_id`":`"$AID`",`"count`":5}"

# promote one rung
Invoke-RestMethod -Method Post http://localhost:8000/api/v1/automations/$AID/promote `
  -ContentType application/json -Body '{}'

# force a critical mismatch (auto-demotes)
Invoke-RestMethod -Method Post http://localhost:8000/api/v1/demo/simulate-shadow-run `
  -ContentType application/json -Body "{`"automation_id`":`"$AID`",`"count`":1,`"force_mismatch`":true}"

# break the schema (triggers self-healing)
Invoke-RestMethod -Method Post http://localhost:8000/api/v1/demo/break-schema `
  -ContentType application/json -Body '{}'
```

Full API reference is in the main [README](README.md#api) and the interactive
docs at <http://localhost:8000/docs>.

---

## 8. Everyday commands (after first-time setup)

You only do steps 1–4 once. Day to day:

```powershell
# reset to a clean demo state (rebuilds the database)
cd apps\api; .venv\Scripts\python.exe scripts\seed.py; cd ..\..

# Terminal 1: API
cd apps\api; .venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

# Terminal 2: console (from project root)
npm run dev --workspace apps/web

# run the backend tests
cd apps\api; .venv\Scripts\python.exe -m pytest -q; cd ..\..
```

---

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| `The module '.venv' could not be loaded` | The venv doesn't exist yet, or you're in the wrong folder. Run step 1 from inside `apps\api`. |
| `python` not found | Python isn't on PATH. Reinstall with "Add to PATH", or use `py` instead of `python`. |
| Console shows "Cannot reach the API" | The API isn't running. Start Terminal 1 (step 5). |
| `break-schema` returns 409 | Already broken this session. Re-seed: `cd apps\api; .venv\Scripts\python.exe scripts\seed.py`. |
| Numbers look wrong or state is messy | Re-seed to reset — it's deterministic. |
| `Activate.ps1 cannot be loaded` (execution policy) | Skip activation; call `.venv\Scripts\python.exe` directly, or run `Set-ExecutionPolicy -Scope Process RemoteSigned`. |
| Port 8000 or 3000 already in use | Stop the other process, or change the port (`--port 8001` for the API). |

---

## 10. Docker alternative

If you have Docker Desktop, you can skip all of the above and run the full stack
(Postgres + API + console, seeded on first boot):

```powershell
docker compose up --build
```

Then open <http://localhost:3000>.
