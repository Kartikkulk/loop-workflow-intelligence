<div align="center">

# Kriyā AI

**From Repetitive Work to Intelligent Action.**

[**Live console**](https://loop-web-780535802644.asia-south1.run.app) ·
[API](https://loop-api-780535802644.asia-south1.run.app) ·
[API reference](https://loop-api-780535802644.asia-south1.run.app/docs) ·
[n8n](https://loop-n8n-780535802644.asia-south1.run.app)

</div>

---

Kriyā AI reads how work actually gets done, finds the processes people repeat,
picks the right way to automate each one, writes it, checks it against what was
observed — and stops for a human before anything runs.

It never asks people to describe their repetitive work. People are poor
witnesses to their own habits, and the person doing a task most often is the
least likely to report it away. The activity log is the witness instead.

```
Observe → Discover → Review → Build → Validate → Approve → Automate
                                                     ↑
                                          nothing runs before here
```

**Four ideas the rest of the system is built around:**

- **Detection is a pure function of the event log.** Re-run it and the same
  clusters come back. Nothing downstream of the log is authoritative.
- **The generator never decides a workflow is too risky to automate.** That
  conclusion is earned by the variance detector, from the data, or it is not a
  feature.
- **Guards are evaluated by a restricted comparator, never `eval`.** Flow
  definitions are partly model-generated, and therefore untrusted input.
- **Promotion is manual; demotion is automatic.** A system that waits for
  permission to become safer is not a safety mechanism.

---

## Try the deployment

Cloud Run in `asia-south1` (Mumbai), Cloud SQL behind it. Everything scales to
zero, so the **first request after an idle period takes a few seconds** while a
container starts.

The landing page opens the console directly. Sources, Discoveries and
Automations ask who you are, because **each person gets their own database** —
one person's uploads and automations are invisible to the other six. Pick a
name:

`Vijay` · `Kavita Joshi` · `Anushree` · `Kartik Kulkarni` · `Anirudh Zalki` ·
`Gouri Kulkarni` · `Pradyumna`

The password is shared, and is the `LOOP_DEMO_PASSWORD` default in
[`config.py`](apps/api/app/config.py). This is deliberately not an identity
system: one password for everyone means the separation is **between colleagues,
not against an attacker**. It exists so seven people can share one URL without
treading on each other's data.

Then **Sources → Download an example CSV → upload it back**. Five recorded
support escalations go through the same normalisation, sessionisation and
clustering a live collector would — there is no separate demo path — and
Discoveries shows one workflow at ~91% similarity across `browser → jira`, with
the variables it found (`{{customer}}`, `{{issue}}`, `{{ticket}}`) and the one
field that never changed (`priority = High`).

---

## Run it locally

**Requirements:** Python 3.11+, Node 18+, `make`. No Docker, no API key, no
model.

```bash
git clone https://github.com/Kartikkulk/loop-workflow-intelligence.git
cd loop-workflow-intelligence

cp .env.example .env      # every value is already a working default
make setup                # Python venv + both npm workspaces
make seed                 # synthetic activity, then detection
make dev                  # API on :8000, console on :3000
```

Every AI feature has a deterministic fallback, so this runs fully with no model
installed — the prose is plainer, the numbers are identical.

<details>
<summary><b>All commands</b></summary>

```bash
make dev          # API on :8000, console on :3000
make api          # API only
make web          # console only
make web-mock     # console from committed fixtures — no Python needed
make seed         # regenerate synthetic activity and run detection
make demo         # reset to the known-good demo starting state
make collectors   # build the browser extension into collectors/dist/
make check        # ruff + tsc + eslint + pytest + contract — what CI runs
make clean        # remove build artefacts, caches and the local database
```

`make help` lists them with descriptions. If `make dev` reports a busy port,
Docker Desktop is the usual squatter: `lsof -ti:3000 -ti:8000`.
</details>

<details>
<summary><b>Watch your own activity (browser extension)</b></summary>

`collectors/` holds a Chrome/Edge extension. It records which application was
used and what kind of action was taken — **never what was typed**. Field *names*
are collected, values are not; URLs are stripped of parameter values; copied
text is hashed in the page, so a copy can be matched to a paste without the text
ever being transmitted.

```bash
make collectors     # builds collectors/dist/chrome and collectors/dist/edge
```

`chrome://extensions` → Developer mode → **Load unpacked** →
`collectors/dist/chrome`, then paste the token from **Sources**.

Signals post about a second after you stop interacting, so activity appears in
the console almost immediately. A 30-second alarm stays as a backstop, because
Chrome evicts an idle service worker and `chrome.alarms` will not fire faster
than that.
</details>

<details>
<summary><b>Run the AI on a local model</b></summary>

Better prose and better workflow naming. Nothing leaves the machine.

```bash
brew install ollama && ollama serve
ollama pull qwen2.5:7b-instruct     # or qwen2.5:1.5b-instruct on a small machine
```

Set `LOOP_LLM_MODEL` in `.env` to match. If Ollama cannot answer and
`LOOP_OPENAI_API_KEY` is set, Kriyā AI tries OpenAI next; with neither it falls
back to a deterministic heuristic. The **System** page shows which is live.
</details>

<details>
<summary><b>Execute approved automations in n8n</b></summary>

Kriyā AI works out *what* repeats and whether handing it over is safe. n8n
already has the connectors and the credential handling, so an approved
automation is exported into it rather than growing a twelfth connector here.

```bash
docker compose up -d n8n            # http://localhost:5678
```

Create an API key (Settings → n8n API), put it in `LOOP_N8N_API_KEY`. Exported
workflows arrive **switched off** — you wire up accounts and enable them
yourself.

`docker compose up --build` runs the whole stack instead: console, API,
Postgres and n8n. Those containers use Postgres, not the local SQLite file, so
the two hold different data.
</details>

---

## How it works

| Stage | Where |
|---|---|
| Normalise any activity source into canonical events | [`normaliser.py`](apps/api/app/services/normaliser.py) |
| Group events into task instances | [`sessioniser.py`](apps/api/app/services/sessioniser.py) |
| Cluster instances into repeated workflows | [`clustering.py`](apps/api/app/services/clustering.py) |
| Score effort, variance and automatability | [`scoring.py`](apps/api/app/services/scoring.py) |
| Tell inputs from constants (`{{customer}}` vs a guard) | [`variables.py`](apps/api/app/services/variables.py) |
| Turn a cluster into a runnable flow | [`generator.py`](apps/api/app/services/generator.py) |
| Choose n8n / Playwright / Python / Hybrid | [`execution_planner.py`](apps/api/app/services/execution_planner.py) |
| Emit the runnable artefact | [`codegen/`](apps/api/app/services/codegen/) |
| Check it against what was observed | [`validation.py`](apps/api/app/services/validation.py) |
| Run it — replay, shadow or live | [`engine.py`](apps/api/app/services/engine.py) |

```
apps/api/        FastAPI backend, detection pipeline, code generators
apps/web/        Next.js console and landing page
collectors/      Browser extension and desktop recorder
contracts/       Committed OpenAPI contract — regenerate with `make contract`
deploy/          Cloud Build configs for the two images
```

[`ARCHITECTURE.md`](ARCHITECTURE.md) has the design decisions.
[`CONTRIBUTING.md`](CONTRIBUTING.md) has the conventions and the review bar.

---

## Tests

```bash
make check          # ruff, tsc, eslint, pytest, contract — what CI runs
make check-all      # the above, plus the browser-collector tests
```

279 Python tests and 21 collector checks. `make check` passes before anything
is merged.

---

## Deploying to Google Cloud

<details>
<summary><b>Full walkthrough</b></summary>

Cloud Run, because it scales to zero — the service costs nothing while nobody
is looking at it. Both images honour `$PORT`, so they run there unmodified.

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com sqladmin.googleapis.com
gcloud artifacts repositories create loop --repository-format=docker --location=asia-south1
```

Builds go through Cloud Build, not `gcloud run deploy --source`: this is a
monorepo, so the build context has to be the repository root while the
Dockerfile lives under `apps/`, and `--source` assumes those are one directory.
The configs in [`deploy/`](deploy/) do the split.

**1. Database** — `db-f1-micro`, the smallest Postgres Google sells:

```bash
gcloud sql instances create loop-db --database-version=POSTGRES_16 \
  --tier=db-f1-micro --region=asia-south1 --storage-size=10GB
gcloud sql databases create loop --instance=loop-db
```

The service account needs `roles/cloudsql.client`, or the container connects to
a socket that is not there and reports `ECONNREFUSED` — which reads like a
timing problem and is not one.

**2. API:**

```bash
IMG=asia-south1-docker.pkg.dev/$PROJECT/loop/loop-api:v1
gcloud builds submit --config deploy/cloudbuild-api.yaml --substitutions _IMAGE=$IMG .
gcloud run deploy loop-api --image $IMG --region asia-south1 --allow-unauthenticated \
  --add-cloudsql-instances $PROJECT:asia-south1:loop-db \
  --set-env-vars "LOOP_DATABASE_URL=postgresql+asyncpg://USER:PASS@/loop?host=/cloudsql/$PROJECT:asia-south1:loop-db"
```

**3. Console** — the API URL is a *build* argument. Next inlines every
`NEXT_PUBLIC_*` value into the bundle at compile time, so setting it on the
service afterwards changes nothing; the shipped JavaScript would still call
`localhost:8000` from the user's browser.

```bash
IMG=asia-south1-docker.pkg.dev/$PROJECT/loop/loop-web:v1
gcloud builds submit --config deploy/cloudbuild-web.yaml \
  --substitutions _IMAGE=$IMG,_API_BASE=https://loop-api-xxxx.run.app .
gcloud run deploy loop-web --image $IMG --region asia-south1 --allow-unauthenticated
```

**4. Let the API accept the console's origin**, or every request fails as a
browser CORS error with a working API behind it:

```bash
gcloud run services update loop-api --region asia-south1 \
  --set-env-vars "LOOP_CONSOLE_URL=https://loop-web-xxxx.run.app"
```

**n8n** is a third service, with two needs it will not announce. It must use
Postgres rather than its bundled SQLite — Cloud Run's disk is ephemeral, so
every workflow would vanish on the next cold start; create the schema yourself
(`CREATE SCHEMA n8n`), n8n will not. And it needs `--no-cpu-throttling` for the
first boot, because Cloud Run gives an idle container almost no CPU and n8n's
~100 startup migrations are not driven by a request, so they starve and time
out. Set `N8N_ENCRYPTION_KEY` explicitly too, or it generates a random one per
boot and cannot decrypt what the last instance stored.

**Cost.** Everything but Cloud SQL stays inside the always-free tier at demo
traffic; Cloud SQL bills by the hour whether or not anyone connects. Cap the
services anyway, so a scraper cannot spend your credit:

```bash
gcloud run services update loop-api --region asia-south1 --max-instances 3
gcloud run services update loop-web --region asia-south1 --max-instances 3
```

Ollama cannot run here — it wants several GB of RAM and a much larger instance.
Leave it unset and every AI feature takes its deterministic path, or set
`LOOP_OPENAI_API_KEY` as a secret.
</details>

---

## Known limitations

Stated plainly, because a demo that hides them is worth less than one that does
not.

- **Selectors cannot be generated.** An activity log records *that* a control
  was used, not how to find it again. Generated browser automations ship with a
  named selector table to fill in, and refuse to run on a placeholder rather
  than clicking the wrong thing.
- **Connected accounts poll once a minute, not per second.** Gmail and Jira are
  rate-limited APIs with no push channel here, and asking every second would be
  throttled long before it was useful. The browser extension is the
  near-real-time half.
- **Detection holds a long transaction.** Scoring makes one model call per
  cluster inside a database transaction. SQLite runs in WAL mode so reads and
  other writers are not blocked, but this needs restructuring before real
  concurrency.
- **Low-occurrence discovery is a demo setting.** `LOOP_DISCOVERY_MODE=demo`
  lowers the *detection* floor so a handful of repeats is visible. It changes no
  safety gate. Production keeps the full statistical floor.
- **A small local model degrades quality, not safety.** Weak models invent step
  names and drop guards; the validator catches both, and the guard the
  observation earned is restored rather than lost.
