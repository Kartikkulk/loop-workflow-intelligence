# Kriyā AI

**From Repetitive Work to Intelligent Action.**

Kriyā AI watches how work actually gets done, discovers the business processes people
repeat, chooses the right way to automate each one, builds it, validates it — and
waits for a human to approve before anything runs.

It does not ask people to describe their repetitive work. People are poor
witnesses to their own habits, and the person doing a task most often is the
least likely to report it away. Kriyā AI reads the activity log instead.

```
Observe → Discover → Review → Build → Validate → Approve → Automate
                                                     ↑
                                          nothing runs before here
```

---

## Quick start

**Requirements:** Python 3.11+, Node 18+, `make`. Nothing else is mandatory —
no Docker, no API keys, no model.

```bash
git clone <this-repo> && cd AI-Pilot
cp .env.example .env      # every value is already the default; you can change nothing
make setup                # creates the Python venv, installs both workspaces
make seed                 # generates demo activity and runs detection
make dev                  # API on :8000, console on :3000
```

Open **http://localhost:3000**.

That is the whole setup. Every AI feature has a deterministic fallback, so Kriyā AI
runs fully with no model installed — the prose is plainer, the numbers are
identical.

### If a port is busy

`make dev` needs 3000 and 8000. Docker Desktop is a common squatter:

```bash
lsof -ti:3000 -ti:8000        # see what holds them
docker compose down           # if a previous stack is still up
```

---

## The five-minute demo

This is the story the product exists to tell: Kriyā AI finds a repetitive process
in historical activity, decides how to automate it, and stops for approval.

```bash
make dev                      # leave running
```

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
7. **Approve.** Only now is anything permitted to run.

Nobody has to perform the task five times on stage. The CSV is the five
historical observations.

### Reset between runs

```bash
make demo                     # back to the known-good starting state
```

---

## Optional extras

None of these are needed to run or evaluate Kriyā AI.

<details>
<summary><b>Run the AI on a local model</b></summary>

Better prose and better task naming. Nothing leaves the machine.

```bash
brew install ollama
ollama serve
ollama pull qwen2.5:7b-instruct     # or qwen3:8b
```

Set `LOOP_LLM_MODEL` in `.env` to match. If Ollama cannot answer and
`LOOP_OPENAI_API_KEY` is set, Kriyā AI tries OpenAI next; with neither, it falls
back to a deterministic heuristic. The **System** page shows which is live.

</details>

<details>
<summary><b>Execute approved automations in n8n</b></summary>

Kriyā AI works out *what* repeats and whether handing it over is safe. n8n already
has the connectors and the credential handling, so an approved automation is
exported into it rather than growing a twelfth connector here.

```bash
docker compose up -d n8n            # http://localhost:5678
```

Create an API key in n8n (Settings → n8n API), put it in `LOOP_N8N_API_KEY`.
Exported workflows arrive **switched off** — you wire up accounts and enable
them in n8n yourself.

</details>

<details>
<summary><b>Run the whole stack in Docker</b></summary>

```bash
docker compose up --build           # console :3000, API :8000, Postgres, n8n
```

Note the containers use Postgres, not the local SQLite file — the two hold
different data.

</details>

<details>
<summary><b>Watch your own activity</b></summary>

`collectors/` holds a Chrome/Edge extension. It records which application was
used and what kind of action was taken — never what was typed. Field *names*
are collected, values are not; URLs are stripped of parameter values; copied
text is hashed in the page so a copy can be matched to a paste without the text
ever being transmitted.

```bash
make collectors                     # builds into collectors/dist/
```

Then load it unpacked and paste the token from **Sources**.

</details>

---

## Deploying to Google Cloud

Cloud Run, because it scales to zero — the service costs nothing while nobody is
looking at it, and the always-free tier covers demo traffic outright. Both
images honour `$PORT`, so they run there unmodified.

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com
```

**1. Database.** Cloud SQL bills by the hour even when idle, so use a free
Postgres instead — [Neon](https://neon.tech) or [Supabase](https://supabase.com).
Take the connection string; Kriyā AI rewrites the driver prefix itself.

**2. Deploy the API**, from the repository root:

```bash
gcloud run deploy loop-api \
  --source . --dockerfile apps/api/Dockerfile \
  --region asia-south1 --allow-unauthenticated \
  --set-env-vars "LOOP_DATABASE_URL=postgresql://...,LOOP_ENABLE_MOCK_CONNECTORS=true"
```

Note the URL it prints.

**3. Deploy the console**, passing that URL in as a *build* argument. Next
inlines `NEXT_PUBLIC_*` at build time, so setting it as a runtime variable does
nothing — the bundle would still be calling `localhost:8000`:

```bash
gcloud run deploy loop-web \
  --source . --dockerfile apps/web/Dockerfile \
  --region asia-south1 --allow-unauthenticated \
  --build-env-vars "NEXT_PUBLIC_API_BASE=https://loop-api-xxxx.run.app"
```

**4. Let the API accept the console's origin**, or every request fails as a
browser CORS error with a working API behind it:

```bash
gcloud run services update loop-api --region asia-south1 \
  --set-env-vars "LOOP_CONSOLE_URL=https://loop-web-xxxx.run.app"
```

Open the console URL, then **Sources → Download an example CSV → upload it**.
Discovery runs in well under a second and the database starts empty, so there
is no seeding step.

### Running n8n alongside it

n8n is a third Cloud Run service. Two things it will not tell you it needs:

- **Postgres, not its bundled SQLite.** Cloud Run's disk is ephemeral, so with
  the default database every workflow disappears on the next cold start. Point
  `DB_TYPE=postgresdb` at a free Neon database — and use Neon's *direct*
  endpoint, not the `-pooler` one: n8n's migrations take advisory locks that
  PgBouncer does not carry, and they fail with `Connection terminated`. Create
  the schema first (`CREATE SCHEMA n8n`); n8n will not create one.
- **`--no-cpu-throttling` for the first boot.** Cloud Run gives an idle
  container almost no CPU, and n8n's ~100 startup migrations are not driven by
  a request, so they starve and time out. Once migrated it can go back to
  `--min-instances 0`, where a cold start is a few seconds and the workflows
  live safely in Postgres.

Set `N8N_ENCRYPTION_KEY` explicitly too — n8n generates a random one per boot
otherwise and cannot decrypt what the last instance stored.

### Cost

At demo traffic this stays inside the always-free tier. Set a hard ceiling
anyway, so a scraper cannot spend your credit:

```bash
gcloud run services update loop-api --region asia-south1 --max-instances 3
gcloud run services update loop-web --region asia-south1 --max-instances 3
```

Ollama cannot run here — it needs several GB of RAM and a much larger instance.
Leave it unset and every AI feature falls back to its deterministic path
(identical numbers, plainer prose), or set `LOOP_OPENAI_API_KEY` as a secret.

---

## Tests

```bash
make check          # ruff, tsc, eslint, pytest, API contract — what CI runs
make test           # pytest only
```

278 tests. `make check` must pass before anything is merged.

---

## How it works

| Stage | Where |
|---|---|
| Normalise any activity source into canonical events | `apps/api/app/services/normaliser.py` |
| Group events into task instances | `services/sessioniser.py` |
| Cluster instances into repeated workflows | `services/clustering.py` |
| Score effort, variance and automatability | `services/scoring.py` |
| Tell inputs from constants (`{{customer}}` vs a guard) | `services/variables.py` |
| Turn a cluster into a runnable flow | `services/generator.py` |
| Choose n8n / Playwright / Python / Hybrid | `services/execution_planner.py` |
| Emit the runnable artefact | `services/codegen/` |
| Check it against what was observed | `services/validation.py` |
| Run it — replay, shadow or live | `services/engine.py` |

`ARCHITECTURE.md` explains the design decisions behind these.
`CONTRIBUTING.md` covers conventions and the review bar.

---

## Layout

```
apps/api/        FastAPI backend, detection pipeline, code generators
apps/web/        Next.js console and landing page
collectors/      Browser extension and desktop recorder
contracts/       Committed OpenAPI contract — regenerate with `make contract`
scripts/         Demo and data-generation helpers
```

---

## Known limitations

Stated plainly, because a demo that hides them is worth less than one that
does not.

- **Selectors cannot be generated.** An activity log records *that* a control
  was used, not how to find it again. Generated browser automations ship with a
  named selector table to fill in, and refuse to run on a placeholder rather
  than clicking the wrong thing.
- **Detection holds a long transaction.** Scoring makes one model call per
  cluster inside a database transaction. SQLite is in WAL mode so reads and
  other writers are not blocked, but this should be restructured before real
  concurrency.
- **Low-occurrence discovery is a demo setting.** `LOOP_DISCOVERY_MODE=demo`
  lowers the *detection* floor so a handful of repeats is visible. It changes no
  safety gate. Production keeps the full statistical floor.
- **A small local model degrades quality, not safety.** Weak models invent step
  names and drop guards; the validator catches both, and the guard the
  observation earned is restored rather than lost.
