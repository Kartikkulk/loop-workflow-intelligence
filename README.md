# LOOP — Workflow Intelligence

**Turn the work people repeat into work that runs itself.**

LOOP watches how work actually gets done, discovers the business processes people
repeat, chooses the right way to automate each one, builds it, validates it — and
waits for a human to approve before anything runs.

It does not ask people to describe their repetitive work. People are poor
witnesses to their own habits, and the person doing a task most often is the
least likely to report it away. LOOP reads the activity log instead.

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

That is the whole setup. Every AI feature has a deterministic fallback, so LOOP
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

This is the story the product exists to tell: LOOP finds a repetitive process
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
4. **Build the automation.** LOOP recommends **Hybrid** and says why: the
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

None of these are needed to run or evaluate LOOP.

<details>
<summary><b>Run the AI on a local model</b></summary>

Better prose and better task naming. Nothing leaves the machine.

```bash
brew install ollama
ollama serve
ollama pull qwen2.5:7b-instruct     # or qwen3:8b
```

Set `LOOP_LLM_MODEL` in `.env` to match. If Ollama cannot answer and
`LOOP_OPENAI_API_KEY` is set, LOOP tries OpenAI next; with neither, it falls
back to a deterministic heuristic. The **System** page shows which is live.

</details>

<details>
<summary><b>Execute approved automations in n8n</b></summary>

LOOP works out *what* repeats and whether handing it over is safe. n8n already
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
