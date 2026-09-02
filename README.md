# LOOP — Workflow Intelligence Platform

LOOP watches how people actually work, finds the tasks they repeat, turns the
good candidates into runnable automations — and then makes each automation
**earn** the right to run unattended, one measured rung at a time.

Finding repetitive work is the easy half. The hard half is switching the
automation on, and nobody signs off on that because a dashboard claimed 94%
accuracy. So the centre of LOOP is the **trust ladder**: an automation proves
itself against real human work before it gets more autonomy, and is demoted
automatically the moment it stops proving itself.

---

## Quick start with Docker

**You need:** [Docker Desktop](https://www.docker.com/products/docker-desktop/)
(and nothing else — no Python, no Node, no API keys).

```bash
git clone https://github.com/Kartikkulk/loop-workflow-intelligence.git
cd loop-workflow-intelligence
cp .env.example .env
docker compose up -d --build
```

Then open **<http://localhost:3000>**.

The first build takes a few minutes (it compiles the console and installs the
Python API). On first boot the API generates the demo dataset and runs detection
by itself, so there is data on screen the moment it comes up.

Watch it come up:

```bash
docker compose logs -f api
```

It is ready when you see `LOOP api ready`.

### What you get

| Service | URL | What it is |
|---|---|---|
| **Console** | <http://localhost:3000> | The app — start here |
| API | <http://localhost:8000/docs> | Interactive API docs |
| n8n | <http://localhost:5678> | Where automations actually run |
| Postgres | `localhost:5432` | `loop` / `loop` / `loop` |

### Everyday commands

```bash
docker compose logs -f api      # follow the API logs
docker compose restart api      # restart after changing .env
docker compose down             # stop everything (keeps the data)
docker compose down -v          # stop and wipe the database too
docker compose up -d --build    # rebuild after changing code
```

---

## First look

1. **Discovery** — the workflows LOOP found, ranked by how much time they cost.
   Note the *"Not recommended for automation"* section at the bottom: that one is
   flagged from the data, not from a label.
2. Open a workflow → the step graph, who does it, and an automatability score
   with every component of the variance shown.
3. **Automations → Trust ladder** — the five rungs, the live confidence bar, and
   the replay panel with its failures open by default.
4. **Impact** — projected hours against hours actually recovered.

For a scripted five-minute walkthrough, see **[DEMO.md](DEMO.md)**.

---

## Running without Docker

Slightly faster for development, since both sides hot-reload.

**You need:** Node ≥ 18.18, Python ≥ 3.11, and
[uv](https://docs.astral.sh/uv/).

```bash
make setup     # create the venv, install everything, write .env
make seed      # generate the demo data and run detection
make dev       # API on :8000, console on :3000
```

This path uses SQLite, so there is no database to install. `make demo` resets
everything to the known-good starting state.

---

## Optional: run the AI on a local model

Every AI-backed feature has a deterministic fallback, so **the whole product
works with no model installed** — the wording is plainer, the numbers are
identical. You will see `llm exhausted retries, using fallback` in the API logs
when this is happening. That is the designed behaviour, not an error.

For better prose, run an open-source model locally. Nothing leaves your machine:

```bash
brew install ollama
ollama serve
ollama pull qwen2.5:7b-instruct
```

**If you are running the Docker stack**, start Ollama so the container can reach
it — by default it listens only on loopback, which the API container cannot see:

```bash
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

The console's **System** page shows whether the local model is being reached.

---

## Optional: let automations run in n8n

LOOP works out *what* repeats and whether it is safe to hand over; n8n already
has the connectors and credential handling, so an approved automation is
exported into it rather than growing a twelfth connector here.

1. Open <http://localhost:5678> and create an account (local only).
2. Go to **Settings → n8n API** and create an API key.
3. Put it in `.env` as `LOOP_N8N_API_KEY=...`, then `docker compose restart api`.

The key is deliberately separate from every other credential, so pushing a
workflow never borrows access that was granted for reading data.

Automations that touch files are confined to one root, `LOOP_FILES_ROOT`
(default `~/LOOP-Invoices`). A path that escapes it is refused rather than
quietly clamped back inside — a flow definition is partly model-generated, and
clamping turns a wrong path into a plausible-looking right one. Compose mounts
that same directory into both the API and n8n, so a file step resolves
identically on both sides of an export. `LOOP_FILES_DRY_RUN=true` (the default)
means steps report what they *would* have done and move nothing.

---

## What's in the demo data

90 days of synthetic activity across 7 teams. From a seeded, reproducible run:

- **18,273 events** → **7 workflows detected**
- **6 recommended**, **1 flagged DO NOT AUTOMATE**
- **1,248 projected annual hours** of repetitive task time

The flagged one earns that flag from the data — step order varies across
virtually every instance, and the content is judgement-laden. Nothing in the
seed specification labels it unautomatable; the variance detector has to reach
that conclusion on its own. A system that recommends automating everything is
not giving advice, it is selling software.

**Backtests are reported honestly.** The invoice automation replayed against
history:

```
214 triggers · 200 correct · accuracy 0.9345 · 17 withheld by guard · 0 errors

   6×  invoice denominated in AED; the flow has no currency-conversion rule
   5×  invoice denominated in USD; the flow has no currency-conversion rule
   3×  invoice denominated in EUR; the flow has no currency-conversion rule
```

Accuracy is truncated, never rounded up, and the failure modes are printed next
to it. Naming your own three failure modes is more convincing than a
suspiciously round 100%.

---

## Adding a team's workflow

The platform is domain-agnostic. A team's repetitive work is **one file** in
`apps/api/app/domains/`:

```python
DOMAIN = DomainPack(
    key="sales", label="Sales",
    tools=["gmail", "crm", "sheets"],
    people=["u_rohit", "u_neha", "u_imran", "u_divya"],
    workflow_name="Inbound lead to CRM record",
    per_person_per_week=9.0,
    steps=[
        Step("gmail", "read",   "enquiry_email",    50, fields=["sender"]),
        Step("crm",   "search", "existing_contact", 55, fields=["customer"]),
        Step("crm",   "create", "lead_record",      95, fields=["customer"]),
        Step("gmail", "send",   "acknowledgement",  40, fields=["recipient"]),
    ],
)
```

The registry finds it automatically — there is no list to edit, so two people
adding a domain on the same day do not conflict. See
[`apps/api/app/domains/README.md`](apps/api/app/domains/README.md).

---

## Tests

```bash
make check              # ruff + tsc + eslint + pytest + API contract check
npm run test:collector  # the browser collector, in real Chrome
```

187 backend tests and 33 collector checks. The ones worth knowing about: guard
expressions are not evaluated as code (`__import__('os').system(...)` returns
`False`); `replay` and `shadow` can never produce a real side effect; a critical
mismatch blocks promotion even at >90% average; and no field value, page title
or query-string value ever appears in a transmitted collector signal.

---

## How LOOP observes

A platform that can only be *fed* logs is a report generator. LOOP can also
watch, through onboarded sources:

| Source | Coverage | Effort | Status |
|---|---|---|---|
| Describe a task in prose | ~10% | seconds | ✅ |
| Upload an activity log | ~25% | minutes | ✅ |
| **Browser extension** | **~70%** | **~2 min/person** | **✅** |
| Connect an app account (OAuth) | ~45% | hours + admin | interfaces declared |
| Desktop agent | ~95% | days + IT rollout | not built |

The tiers overlap heavily, so the console reports the best connected tier rather
than the sum. The browser extension is the highest-leverage one: it is the only
tier that sees data **copied out of one system and pasted into another**, which
is the problem statement verbatim. It matches a *hash* of the copied value, so
it proves the value moved without ever receiving it.

**Privacy is implemented, not promised.** Metadata only by default (the *name*
of the field you filled, never its value); query values stripped from URLs on
both the collector and the server; consent stored as a row that ingestion
checks; pause honoured within 30 seconds; and revoking a source deletes every
event it reported. See **[collectors/README.md](collectors/README.md)** for
install steps and the collector API.

---

## Known limitations

Stated plainly, because a reviewer will find them anyway.

- **Execution connectors are mocked.** The interfaces are real and the live
  classes declare their APIs and credentials, but nothing has run against a
  production Gmail or ERP. *Observation* is separate — the browser collector
  does watch real activity.
- **The demo data is synthetic.** Deliberately structured — optional steps,
  occasional reordering, real anomalies, a genuine schema change at day 60 — but
  not a real company's log.
- **Shadow runs are drawn from history, not live observation.** The comparison
  is identical to what a live deployment performs; only the source of the "human
  action" differs.
- **The interruption cost (4 min/switch) is a conservative literature
  estimate**, not measured here. It is reported separately from raw task time
  precisely so it can be argued with.
- **Screen-recording ingestion needs a local vision model.** It is the one
  feature with no deterministic fallback, so it is disabled rather than faked.
- **Migrations use `create_all`, not Alembic**, so a clean clone runs in one
  command. The models are Alembic-compatible.
- **No authentication.** Single-tenant, single-user, local only.

---

## Layout

```
apps/api/                 FastAPI backend
  app/domains/            ONE FILE PER TEAM — add a workflow, change nothing else
  app/services/           detection, scoring, generation, engine, trust, healing
  app/connectors/         the Connector protocol, real + mock implementations
  app/llm/                Ollama client, prompts on disk, fallback contract
apps/web/                 Next.js 15 console
  lib/api/                typed clients — nothing else calls fetch
collectors/               the browser extension (one shared MV3 codebase)
docker-compose.yml        Postgres + n8n + API + console
```

**[ARCHITECTURE.md](ARCHITECTURE.md)** has the data flow and the reasoning
behind each design decision. **[DEMO.md](DEMO.md)** is the run sheet.
