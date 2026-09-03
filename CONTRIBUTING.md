# Working on Kriyā AI

Three people, one repo, four days. This document exists so nobody blocks anybody.

## Get running in five minutes

```bash
git clone <repo> && cd AI-Pilot
make setup        # venv + npm install + .env
make seed         # 8.5k synthetic events, detection, starting automations
make dev          # API :8000 (docs at /docs), console :3000
```

Requirements: Node ≥ 18.18, Python ≥ 3.11, [uv](https://docs.astral.sh/uv/).
No Docker, no Postgres, **no API key** — every AI feature has a deterministic
fallback.

## Frontend without a backend

The frontend developer does not need Python installed at all.

```bash
make web-mock     # console on :3000, served from committed fixtures
```

Fixtures live in `apps/web/lib/api/fixtures.json` and are captured from the real
API, so the shapes are real rather than hand-written guesses that drift. Reads
work; **mutations deliberately throw** rather than faking success, because a
mocked mutation makes the UI look correct while being wrong.

Regenerate them after a backend response shape changes:

```bash
make api          # in one terminal
make fixtures     # in another
```

## Who owns what

**The rule that keeps us mergeable: you own a folder, and you only edit that
folder.** If you need something from outside it, open an issue rather than
reaching in.

| Who | Owns |
|---|---|
| **Kartik** | Core platform — `apps/api/app/services`, `app/api`, `app/llm`, `apps/web`, `collectors/shared` |
| **Anirudh** | `apps/api/app/domains/finance.py`, `customer_support.py` |
| **Vijay** | `apps/api/app/domains/sales.py` **or** `hr.py` — pick one |
| **Anushree** | `collectors/chrome/` |
| **Gouri** | `collectors/edge/` |

| Path | Owner | Rule |
|---|---|---|
| `apps/api/` | backend | Frontend does not edit. Open an issue instead. |
| `apps/web/` | frontend | Backend does not edit. |
| `collectors/shared/` | Kartik | Message before editing — shared by both browsers. |
| `contracts/openapi.json` | both | **Generated.** Never hand-edit. |
| `Makefile`, `docker-compose.yml`, `.github/` | integration | |
| docs at the root | integration | |

`.github/CODEOWNERS` auto-requests the right reviewer. **Put real GitHub handles
in it before the first PR** or it is silently inert.

### Domain owners (Anirudh, Vijay)

A team's repetitive work is one file in `apps/api/app/domains/`. Read that
folder's `README.md` — it is the whole API you need. Replace the `steps` with
the real ones you observed, set `is_template=False` when it reflects reality,
and run `make demo && make dev` to check your workflow appears on Discovery.
**Do not touch `app/services/`** — if a domain needs something the core cannot
express, open an issue.

Keep `customer_support.py` freeform: it is the pack that proves the platform
knows when *not* to automate, and a test fails if it stops being caught. If your
real support work is highly repetitive, add it as a second domain instead.

### Collector owners (Anushree, Gouri)

Chrome and Edge are both Chromium on Manifest V3, so the observing logic is
identical and lives once in `collectors/shared/`. Your folder holds only what
genuinely differs (today, just the manifest). The work is not "write it twice":

1. Get it loaded and reporting — `make collectors`, then load `dist/<yours>`
   unpacked. This is the unverified part: Chrome 137 removed `--load-extension`,
   so the browser plumbing has never been confirmed.
2. Find where your browser actually differs (permissions, service-worker
   lifecycle, `chrome.*` vs `browser.*`, packaging) and put that in your folder.
3. Report what breaks — a precise bug report is worth more than code.

If something must change in `collectors/shared/`, message Kartik rather than
editing it.

## The API boundary

`contracts/openapi.json` is the contract, and it is committed. CI regenerates it
and **fails if the committed copy is stale**.

That check is the whole mechanism. It means a backend change that alters the API
surface cannot merge without the contract diff being visible in the same pull
request — so the frontend developer sees a breaking change in a review, not at
runtime on the morning of the demo.

**Backend: changing a response shape**

```bash
make contract     # regenerate contracts/openapi.json
make fixtures     # regenerate the frontend fixtures
# commit both, and say so in the PR description
```

Then either update `apps/web/lib/api/types.ts` in the same PR, or open an issue
assigned to the frontend owner. Do not leave it implicit.

**Frontend: needing a field that does not exist**

Open an issue with the exact shape you want. Do not add it to `types.ts`
speculatively — a type that lies is worse than a type that is missing, because
`tsc` then stops protecting you.

## Branches and commits

```
main                      protected; green CI; always demoable
feat/<area>-<thing>       feat/web-roi-skeletons, feat/api-graph-connector
fix/<area>-<thing>
docs/<thing>
```

Small PRs. A 400-line PR on day three gets rubber-stamped, which is the same as
not reviewing it.

Commit messages: imperative, and say *why* when it is not obvious.

```
add currency conversion rule to the invoice flow

Replay named 56 foreign-currency failures out of 782. This closes the
largest single failure mode rather than the easiest one.
```

## Before every PR

```bash
make check              # ruff + tsc + eslint + pytest — must be green
make test-collector     # only if you touched collectors/
```

`main` must stay demoable. If `make demo && make dev` is broken on `main`, that
is the highest-priority bug in the repo regardless of what else is open.

## House rules

These are in `CLAUDE.md` too, and they are not stylistic preferences.

1. **No placeholders.** No `# TODO: implement`, no bare `pass`, no mock return
   where real logic belongs. If it is in the plan, it is written.
2. **Never inflate a number.** If accuracy is 0.9271, report 0.9271. If a metric
   cannot be computed honestly, fix the metric rather than the wording. Coverage
   counts guard holds against itself for exactly this reason.
3. **No secrets in the repo.** Everything through `.env`, documented in
   `.env.example`.
4. **The frontend never calls `fetch` directly** — always through `lib/api/`.
5. **Comments explain why, never what.** A comment that restates the code is
   noise that goes stale.
6. **Money in minor units** (paise) as integers. Timestamps UTC, ISO 8601.

## Architectural invariants — breaking these breaks the product

- Detection is a pure function of the event log. Re-running it produces the same
  clusters. Nothing downstream of the log is authoritative.
- The seed generator **never labels a workflow do-not-automate.** That conclusion
  is earned by the variance detector from the data, or it is not a feature.
- `replay` and `shadow` force mock connectors **in the engine**, not in each
  connector, so a new connector cannot forget to be safe.
- Guard expressions are evaluated by a restricted comparator, **never `eval`**.
  Flow definitions are partly model-generated and are untrusted input.
- Promotion is manual; demotion is automatic.
- The collector transmits field *names*, never field *values* — and URLs are
  stripped of query values on both sides, because a GET form puts every field
  into the URL.

## Where things are

```
apps/api/app/services/     the algorithms — sessioniser, clustering, scoring,
                           engine, replay, trust, healing, web_activity
apps/api/app/llm/prompts/   every prompt, on disk, never in an f-string
apps/web/lib/api/           typed clients; nothing else calls fetch
apps/web/components/        trust-ladder and workflow-graph are the flagships
collectors/browser-extension/  the ~70% coverage observation tier
```

`ARCHITECTURE.md` explains why each design decision was made. Read section 4
(Workflow DNA) before touching clustering — the threshold and the three
similarity signals were chosen empirically and there are tests asserting the
separation margin stays wide.
