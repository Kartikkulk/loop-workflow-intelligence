# Team plan — submission Friday 4 September

Three people. Today is Monday 31 August, so there are **four and a half working
days**. The product already works end to end; these four days are about
hardening, the gaps that will get asked about, and the artefact.

## Roles

| Who | Owns | Does not touch |
|---|---|---|
| **Kartik** | `collectors/`, docs, demo, integration, release | — |
| **Backend dev** | `apps/api/` | `apps/web/` |
| **Frontend dev** | `apps/web/` | `apps/api/` |

The frontend developer is **not blocked on the backend at any point**:
`make web-mock` serves the whole console from committed fixtures with no Python
installed.

## Where things stand

Green today: detection recovers all 5 seeded workflows at 99.9% purity, replay
reports 92.71% with three named failure modes, the trust ladder promotes and
auto-demotes, schema drift self-heals, rule learning closes the loop, the browser
collector observes real activity and detects a workflow from it. 131 backend
tests + 33 collector checks, `make check` clean.

So this is not a build sprint. It is a *close the credible gaps* sprint.

---

## Day by day

### Monday 31 Aug (today, partial) — setup

**All three**
- Clone, `make setup && make seed && make dev`, confirm the console loads.
- Read `CONTRIBUTING.md`. Skim `ARCHITECTURE.md` sections 2 and 4.
- Put your real GitHub handle in `.github/CODEOWNERS`.

**Kartik**
- Repo created, CI green, both devs added as collaborators.
- Install the extension unpacked and confirm it reports — this is the only part
  of the collector never verified in a loaded-extension environment.

### Tuesday 1 Sep — the biggest gaps

**Backend — one live API connector (the top gap)**
Everything execution-side is mocked. One real read-only connector changes the
answer to "could this touch production?" from an argument to a demo.
- Microsoft Graph is the best target: `/me/messages/delta` needs only delegated
  consent, no tenant admin.
- Land it as an *ingestion* adapter first (read mail metadata → canonical
  events), not an execution connector. Lower risk, and it feeds Observation.
- Acceptance: a real mailbox produces canonical events visible on Observation.

**Frontend — loading and empty states**
- Replace every `<Loading label="…" />` with a skeleton matching the real layout.
  Six screens currently flash a text spinner.
- Empty states: `/automations` and `/exceptions` with zero rows should teach the
  next action, not just say "nothing here".
- Acceptance: no layout shift when data lands.

**Kartik**
- Rehearse `DEMO.md` once end to end. Time it. Note anything slow or fragile.

### Wednesday 2 Sep — hardening

**Backend**
- Verify the Postgres path: `docker compose up --build` from a clean clone. This
  is the least-tested route in the repo and it is what a judge may run.
- Persist replay failures so `/analytics/roi` can trend failure modes over time
  (currently returned but not stored).
- Acceptance: `docker compose up` works from a fresh clone; ROI shows a failure
  trend.

**Frontend**
- Responsive pass. The console is desktop-only; below ~1100px the stat grids and
  the flow-definition table break.
- Keyboard and focus pass: the trust ladder, the promote button and the exception
  queue are the paths a judge is most likely to drive by keyboard.
- Acceptance: usable at 1024px; every interactive control reachable by Tab with a
  visible focus ring.

**Kartik**
- Screenshots for the README (there are placeholders).
- Second rehearsal, with the fixes from Tuesday.

### Thursday 3 Sep — freeze

**Feature freeze at 12:00.** After that, only bug fixes.

**Backend**
- Alembic initial migration (currently `create_all`). Only if Wednesday's work
  landed cleanly — this is a nice-to-have, not a blocker.
- Re-run the full suite against Postgres as well as SQLite.

**Frontend**
- Polish only. No new components.
- `make build` must be clean with zero warnings.

**All three**
- Full run-through together. Each person drives `DEMO.md` once.
- Fix whatever breaks. Nothing else.

### Friday 4 Sep — submit

- Morning: `make demo` → full rehearsal → submit.
- Nothing merges after the rehearsal except a demo-breaking fix.

---

## The cut list

If time runs short, cut in this order and say what you cut:

1. Alembic migrations
2. ROI failure-mode trend
3. Responsive breakpoints below 1024px
4. The live Graph connector *(cut this only if it is genuinely not working — it
   is the highest-value item on the list)*

**Never cut:** the clustering, replay, the trust ladder, self-healing, or the
do-not-automate detection. Those five are the product.

## Definition of done, per task

1. `make check` green.
2. No `TODO`, no bare `pass`, no placeholder return.
3. New env vars in `.env.example` with a comment.
4. If the API surface changed: `make contract` and `make fixtures` re-run and
   committed.
5. You ran it. "Tests pass" is not verification of a UI change.

## Risks worth naming now

**The extension is the one thing never verified as a loaded extension.** Chrome
137+ removed `--load-extension`, so it could not be automated. Both shipped
files are tested directly and the collector API is tested end to end, but
Chrome's own plumbing is unverified. **Kartik should install it manually on day
one**, not day four.

**`docker compose up` is the least-tested path.** If a judge runs anything, it
is that. Wednesday's job.

**No API key is set.** Everything works without one by design, but the LLM-backed
paths (flow generation, SOP prose, drift remapping) produce better output with
one, and screen-recording ingestion needs one. Decide by Wednesday whether to
demo with a key, and if so rehearse with it — the outputs differ.

**Three people, one `main`.** The contract check and CODEOWNERS handle the
frontend/backend boundary. The real risk is `main` going red and nobody noticing
before the rehearsal. Whoever breaks it fixes it before starting anything else.
