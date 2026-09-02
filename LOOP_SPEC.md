# LOOP — specification and build plan

> "LOOP found this workflow by watching how work gets done — you did not have
> to configure it first."

Everything below is measured against the repository as it stands, not against
a blank slate. Roughly two thirds of the pipeline already exists and works;
listing it as "to build" would waste the time we have.

---

## 1. The chain, and where the code for it already lives

| Stage | Status | Where |
|---|---|---|
| **OBSERVE** | partial | `collectors/` browser extension, `collectors/desktop/record.py`, `POST /api/v1/ingest/upload`, `activity_import.py` |
| **DETECT** | **done** | `sessioniser.py` → `clustering.py` → `pipeline.py`. Deterministic, rapidfuzz + TF-IDF, no LLM in the loop |
| **SCORE** | needs reshaping | `scoring.py` produces a 0–1 `automatability`; the spec wants an explainable 0–100 with named factors |
| **UNDERSTAND** | **done** | `llm/client.py` → Ollama `qwen2.5:7b-instruct`, JSON-schema output, deterministic fallback for every call |
| **RECOMMEND** | **done** | `clusters.py` endpoints, Discovery screen |
| **APPROVE** | **done** | Approvals screen, `POST /api/v1/automations/{id}/n8n` |
| **GENERATE** | **done** | `n8n_export.py` translator, pushes real workflows to n8n |
| **EXECUTE** | **done** | n8n in `docker-compose.yml`, port 5678 |
| **MEASURE** | partial | `GET /analytics/roi`, `GET /automations/{id}/n8n/runs`. No before/after panel |

**Do not rebuild the detection engine.** It already does what §5 and §6 ask
for: sessionise, normalise to action labels, sequence-compare with tolerance
for variation, cluster, require multiple occurrences, configurable threshold.

**Do not rebuild the LLM integration.** §8 asks for exactly what exists —
deterministic detection first, structured summary to Qwen second, JSON out, and
the model never executes anything.

---

## 2. Real gaps

1. **No Start/Pause Watching.** The desktop recorder exists but nothing in the
   UI starts it, and the product never says "watching this device". This is the
   first thing a judge looks for and it is missing.
2. **No Activity screen.** Events are stored and `GET /api/v1/ingest/events`
   serves them; nothing displays them.
3. **Automation Potential is the wrong shape.** A 0–1 score built from
   entropy/spread/branches, where the spec wants 0–100 from
   frequency · similarity · predictability · time · judgment · exceptions, with
   the arithmetic shown.
4. **Nine screens, not seven.** Plus a trust ladder the spec explicitly rules
   out of the UI.
5. **No before/after panel.**
6. **Demo mode is not labelled.** Synthetic and real activity are
   indistinguishable once ingested, which is the one thing that must never be
   ambiguous.

---

## 3. Screens — seven, no more

| Screen | Route | Change |
|---|---|---|
| Dashboard | `/` | Simplify. Watching status, Start/Pause, four numbers, recent discoveries |
| Activity | `/activity` | **new** — the raw event stream, so "it watched" is visible |
| Discoveries | `/discovery` | Keep; lead with why it is repetitive |
| Approval | `/approvals` | Keep. Already ends in n8n generation |
| Automation | `/automations` | Keep. Drop the trust ladder from the page |
| Connections | `/sources` | Rename. Add n8n and Ollama as connections |
| Settings | `/settings` | **new** — absorbs `/system`; thresholds, demo mode |

Retired from navigation: `/roi` (its two useful numbers move to Dashboard),
`/system` (into Settings). Both keep working as URLs — deleting them would
break links for no gain.

### On the trust ladder

The spec says no complicated trust ladders. `trust` is referenced across 28
files and 28 test assertions, and it is what makes demotion automatic.

**Decision: remove it from the UI, keep it in the backend.** The promotion and
demotion logic stays, tested and working; no screen shows a five-rung ladder or
asks anyone to understand one. Ripping out the mechanism to satisfy a UI note
would mean deleting a working safety feature and 28 tests, which §24 forbids.

---

## 4. Automation Potential — 0 to 100, arithmetic shown

Six factors, each read from measured data, plus two penalties:

| Factor | Source |
|---|---|
| Frequency | executions per person per week |
| Similarity | `1 − step_order_entropy` |
| Predictability | share of runs taking the most common path |
| Time impact | median duration × frequency, annualised |
| Systems involved | distinct applications |
| **Judgment penalty** | free-text ratio in the observed payloads |
| **Exception penalty** | share of runs the engine held or failed |

Displayed as the sum, with every line visible. Labelled **Automation
Potential**, never "accuracy" or "confidence" — it is a ranking heuristic, and
the screen will say so.

---

## 5. Order of work

Phase 1 is navigation. Everything after it is additive, so the app keeps
running at every step.

1. **Navigation → seven screens; trust ladder out of the UI** ← starts here
2. Activity screen on the existing events endpoint
3. Start/Pause Watching, wired to the real desktop collector
4. Automation Potential 0–100, with the breakdown shown
5. Discovery screen leads with "why this is repetitive"
6. Tool discovery on the Approval screen: which tools, which are connected
7. Before/after panel after a successful run
8. Demo mode labelled everywhere it appears
9. Connections screen covering n8n and Ollama

---

## 6. Rules this build keeps

- Detection is a pure function of the event log. Re-running it gives the same
  clusters.
- The LLM never executes anything. No shell, no generated code, no credentials.
- Guards are evaluated by a restricted comparator, never `eval`.
- No keystrokes, no passwords, no page contents. Metadata only.
- Never inflate a number. If it is 6.0 hours, it says 6.0 hours.
