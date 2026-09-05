# Kriyā AI

**From Repetitive Work to Intelligent Action.**

Kriyā AI watches how work actually gets done, discovers the business processes
people repeat, chooses the right way to automate each one, builds it, validates
it — and waits for a human to approve before anything runs.

It does not ask people to describe their repetitive work. People are poor
witnesses to their own habits, and the person doing a task most often is the
least likely to report it away. Kriyā AI reads the activity log instead.

```
Observe → Discover → Review → Build → Validate → Approve → Automate
                                                     ↑
                                          nothing runs before here
```

---

## Try it live

| | |
|---|---|
| **Console** | https://loop-web-780535802644.asia-south1.run.app |
| **API** | https://loop-api-780535802644.asia-south1.run.app |
| **API reference** (OpenAPI/Swagger) | https://loop-api-780535802644.asia-south1.run.app/docs |
| **Health** | https://loop-api-780535802644.asia-south1.run.app/health |
| **n8n** (executes approved automations) | https://loop-n8n-780535802644.asia-south1.run.app |

Running on Google Cloud Run in `asia-south1` (Mumbai), with Cloud SQL for
Postgres behind it. All three services scale to zero, so the **first request
after an idle period takes a few seconds** while a container starts.

### Signing in

The landing page goes straight to the console. **Sources**, **Discoveries** and
**Automations** ask who you are, because each person gets their own database —
one person's uploads, discoveries and automations are invisible to everyone
else. Pick a name from the dropdown:

`Vijay` · `Kavita Joshi` · `Anushree` · `Kartik Kulkarni` · `Anirudh Zalki` ·
`Gouri Kulkarni` · `Pradyumna`

The password is shared across all seven and is the `LOOP_DEMO_PASSWORD` default
in [`apps/api/app/config.py`](apps/api/app/config.py).

This is deliberately not an identity system, and the code says so in as many
words. One password for everyone means the separation is **between colleagues,
not against an attacker** — it exists so seven people can be handed one URL and
still not tread on each other's data.

---

## Run it locally

**Requirements:** Python 3.11+, Node 18+, `make`. Nothing else is mandatory —
no Docker, no API keys, no model.

```bash
git clone https://github.com/Kartikkulk/loop-workflow-intelligence.git
cd loop-workflow-intelligence

cp .env.example .env      # every value is already a working default
make setup                # creates the Python venv, installs both workspaces
make seed                 # generates demo activity and runs detection
make dev                  # API on :8000, console on :3000
```

Open **http://localhost:3000**.

That is the whole setup. Every AI feature has a deterministic fallback, so
Kriyā AI runs fully with no model installed — the prose is plainer, the numbers
are identical.

<details>
<summary><b>If a port is busy</b></summary>

`make dev` needs 3000 and 8000. Docker Desktop is a common squatter:

```bash
lsof -ti:3000 -ti:8000        # see what holds them
docker compose down           # if a previous stack is still up
```
</details>

<details>
<summary><b>Every command</b></summary>

```bash
make setup        # install everything
make dev          # API on :8000, console on :3000
make api          # API only
make web          # console only
make web-mock     # console from committed fixtures — no Python needed
make seed         # regenerate synthetic activity and run detection
make demo         # reset to the known-good demo starting state
make collectors   # build the browser extension into collectors/dist/
make check        # ruff + tsc + eslint + pytest + contract — what CI runs
make test         # tests only
make clean        # remove build artefacts, caches and the local database
```

`make help` lists them with descriptions.
</details>

---

## The five-minute demo

This is the story the product exists to tell: Kriyā AI finds a repetitive
process in historical activity, decides how to automate it, and stops for
approval.

1. **Sources → Add activity data → Download an example CSV.**
   Five recorded support escalations — the same process, different customers.
2. **Upload that CSV back.** It goes through exactly the same normalisation,
   sessionisation and clustering as a live collector. There is no separate
   demo path.
3. **Discoveries** now shows one workflow: *5 occurrences, ~91% similarity*,
   spanning `browser → jira`, with the variables it detected
   (`{{customer}}`, `{{issue}}`, `{{ticket}}`) and the one field that never
   changed — `priority = High`.
4. **Build the automation.** Kriyā AI recommends **Hybrid** and says why: the
   support portal has no usable API so a browser is the only way in, while Jira
   has one and an API call survives a redesign that would break a click.
5. **Validate.** Nine checks against the observed activity — a step naming a
   system nobody used is reported as a fabrication, not accepted.
6. **Dry run.** Ten steps, zero side effects. The engine forces mock connectors
   in replay mode, so this cannot touch a real system.
7. **Approve.** Only now is anything permitted to run, and the automation is
   exported to n8n.

Nobody has to perform the task five times on stage. The CSV is the five
historical observations.

Locally, `make demo` returns everything to the known-good starting state.

---

## Optional extras

None of these are needed to run or evaluate Kriyā AI.

<details>
<summary><b>Watch your own activity (browser extension)</b></summary>

`collectors/` holds a Chrome/Edge extension. It records which application was
used and what kind of action was taken — never what was typed. Field *names*
are collected, values are not; URLs are stripped of parameter values; copied
text is hashed in the page, so a copy can be matched to a paste without the
text ever being transmitted.

```bash
make collectors     # builds into collectors/dist/chrome and collectors/dist/edge
```

Then `chrome://extensions` → Developer mode → **Load unpacked** →
`collectors/dist/chrome`, and paste the token from **Sources**.

Signals post about a second after you stop interacting, so activity appears in
the console almost immediately. The extension also keeps a 30-second alarm as a
backstop, because Chrome evicts an idle service worker and `chrome.alarms` will
not fire faster than that.
</details>

<details>
<summary><b>Run the AI on a local model</b></summary>

Better prose and better workflow naming. Nothing leaves the machine.

```bash
brew install ollama
ollama serve
ollama pull qwen2.5:7b-instruct     # or qwen2.5:1.5b-instruct on a small machine
```

Set `LOOP_LLM_MODEL` in `.env` to match. If Ollama cannot answer and
`LOOP_OPENAI_API_KEY` is set, Kriyā AI tries OpenAI next; with neither, it falls
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

Create an API key in n8n (Settings → n8n API) and put it in `LOOP_N8N_API_KEY`.
Exported workflows arrive **switched off** — you wire up accounts and enable
them in n8n yourself.
</details>

<details>
<summary><b>Run the whole stack in Docker</b></summary>

```bash
docker compose up --build           # console :3000, API :8000, Postgres, n8n
```

The containers use Postgres, not the local SQLite file — the two hold different
data.
</details>

---

## Deploying to Google Cloud

Cloud Run, because it scales to zero: the service costs nothing while nobody is
looking at it, and the always-free tier covers demo traffic outright. Both
images honour `$PORT`, so they run there unmodified.

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com sqladmin.googleapis.com
gcloud artifacts repositories create loop --repository-format=docker --location=asia-south1
```

Builds go through Cloud Build rather than `gcloud run deploy --source`. This is
a monorepo, so the build context has to be the repository root while the
Dockerfile lives under `apps/`, and `--source` assumes those are the same
directory. The two configs in [`deploy/`](deploy/) do the split.

**1. Database.** A `db-f1-micro` Cloud SQL instance, which is the smallest
Postgres Google sells:

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

**3. Console**, passing the API URL in as a *build* argument:

```bash
IMG=asia-south1-docker.pkg.dev/$PROJECT/loop/loop-web:v1
gcloud builds submit --config deploy/cloudbuild-web.yaml \
  --substitutions _IMAGE=$IMG,_API_BASE=https://loop-api-xxxx.run.app .
gcloud run deploy loop-web --image $IMG --region asia-south1 --allow-unauthenticated
```

**4. Let the API accept the console's origin**, or every request fails as a
browser CORS error with a perfectly working API behind it:

```bash
gcloud run services update loop-api --region asia-south1 \
  --set-env-vars "LOOP_CONSOLE_URL=https://loop-web-xxxx.run.app"
```

Then open the console and **Sources → Download an example CSV → upload it**.
Discovery runs in well under a second and the database starts empty, so there
is no seeding step.

<details>
<summary><b>Running n8n alongside it</b></summary>

n8n is a third Cloud Run service. Two things it will not tell you it needs:

- **Postgres, not its bundled SQLite.** Cloud Run's disk is ephemeral, so with
  the default database every workflow disappears on the next cold start. Point
  `DB_TYPE=postgresdb` at the same Cloud SQL instance and create the schema
  first (`CREATE SCHEMA n8n`) — n8n will not create one. If you use a pooled
  hosted Postgres instead, use its *direct* endpoint: n8n's migrations take
  advisory locks that PgBouncer does not carry, and they fail with
  `Connection terminated`.
- **`--no-cpu-throttling` for the first boot.** Cloud Run gives an idle
  container almost no CPU, and n8n's ~100 startup migrations are not driven by
  a request, so they starve and time out. Once migrated it can go back to
  `--min-instances 0`.

Set `N8N_ENCRYPTION_KEY` explicitly too — n8n generates a random one per boot
otherwise, and then cannot decrypt what the previous instance stored.
</details>

<details>
<summary><b>Cost</b></summary>

At demo traffic this stays inside the always-free tier apart from Cloud SQL,
which bills by the hour whether or not anyone is connected. Set a hard ceiling
anyway, so a scraper cannot spend your credit:

```bash
gcloud run services update loop-api --region asia-south1 --max-instances 3
gcloud run services update loop-web --region asia-south1 --max-instances 3
```

Ollama cannot run here — it needs several GB of RAM and a much larger instance.
Leave it unset and every AI feature falls back to its deterministic path
(identical numbers, plainer prose), or set `LOOP_OPENAI_API_KEY` as a secret.
</details>

---

## Tests

```bash
make check          # ruff, tsc, eslint, pytest, API contract — what CI runs
make check-all      # the above, plus the browser-collector tests
make test           # tests only
```

279 Python tests and 21 collector checks. `make check` must pass before
anything is merged.

---

## How it works

| Stage | Where |
|---|---|
| Normalise any activity source into canonical events | [`services/normaliser.py`](apps/api/app/services/normaliser.py) |
| Group events into task instances | [`services/sessioniser.py`](apps/api/app/services/sessioniser.py) |
| Cluster instances into repeated workflows | [`services/clustering.py`](apps/api/app/services/clustering.py) |
| Score effort, variance and automatability | [`services/scoring.py`](apps/api/app/services/scoring.py) |
| Tell inputs from constants (`{{customer}}` vs a guard) | [`services/variables.py`](apps/api/app/services/variables.py) |
| Turn a cluster into a runnable flow | [`services/generator.py`](apps/api/app/services/generator.py) |
| Choose n8n / Playwright / Python / Hybrid | [`services/execution_planner.py`](apps/api/app/services/execution_planner.py) |
| Emit the runnable artefact | [`services/codegen/`](apps/api/app/services/codegen/) |
| Check it against what was observed | [`services/validation.py`](apps/api/app/services/validation.py) |
| Run it — replay, shadow or live | [`services/engine.py`](apps/api/app/services/engine.py) |

[`ARCHITECTURE.md`](ARCHITECTURE.md) explains the design decisions behind these.
[`CONTRIBUTING.md`](CONTRIBUTING.md) covers conventions and the review bar.

---

## Layout

```
apps/api/        FastAPI backend, detection pipeline, code generators
apps/api/scripts/  Seeding and demo-data generators
apps/web/        Next.js console and landing page
collectors/      Browser extension and desktop recorder
contracts/       Committed OpenAPI contract — regenerate with `make contract`
deploy/          Cloud Build configs for the two images
```

---

## Known limitations

Stated plainly, because a demo that hides them is worth less than one that does
not.

- **Selectors cannot be generated.** An activity log records *that* a control
  was used, not how to find it again. Generated browser automations ship with a
  named selector table to fill in, and refuse to run on a placeholder rather
  than clicking the wrong thing.
- **Connected accounts are polled once a minute, not per second.** Gmail and
  Jira are rate-limited APIs with no push channel here; asking every second
  would be throttled long before it was useful. The browser extension is the
  near-real-time half.
- **Detection holds a long transaction.** Scoring makes one model call per
  cluster inside a database transaction. SQLite runs in WAL mode so reads and
  other writers are not blocked, but this should be restructured before real
  concurrency.
- **Low-occurrence discovery is a demo setting.** `LOOP_DISCOVERY_MODE=demo`
  lowers the *detection* floor so a handful of repeats is visible. It changes no
  safety gate. Production keeps the full statistical floor.
- **A small local model degrades quality, not safety.** Weak models invent step
  names and drop guards; the validator catches both, and the guard the
  observation earned is restored rather than lost.
