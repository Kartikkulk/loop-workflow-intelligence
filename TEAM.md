# Team — who owns what

Six people, one repo, submission Friday 4 September.

**The rule that keeps us mergeable: you own a folder, and you only edit that
folder.** If you need something from outside it, open an issue rather than
reaching in.

| Who | Owns | Edits nothing else |
|---|---|---|
| **Kartik** | Core platform — `apps/api/app/services`, `app/api`, `app/llm`, `apps/web`, `collectors/shared` | — |
| **Anirudh** | `apps/api/app/domains/finance.py`, `customer_support.py` | ✓ |
| **Vijay** | `apps/api/app/domains/sales.py` **or** `hr.py` — pick one | ✓ |
| **Anushree** | `collectors/chrome/` | ✓ |
| **Gouri** | `collectors/edge/` | ✓ |

Nobody's daily work touches anybody else's files. That is deliberate.

---

## Everyone: first 15 minutes

```bash
git clone https://github.com/Kartikkulk/loop-workflow-intelligence.git
cd loop-workflow-intelligence
make setup      # venv + npm install + .env
make demo       # generate the synthetic activity log and run detection
make dev        # API on :8000 (docs at /docs), console on :3000
```

Needs Node ≥ 18.18, Python ≥ 3.11, [uv](https://docs.astral.sh/uv/).
**No Docker, no database, no API key.** If `make setup` fails, message Kartik —
do not spend an hour on it.

Open <http://localhost:3000>. You should see four detected workflows, one of
them flagged **do not automate**. That is the whole product in one screen.

Then: `git checkout -b <your-name>/<what-you-are-doing>`

---

## Anirudh — Finance and Customer Support

**Your files:** `apps/api/app/domains/finance.py`, `customer_support.py`

Both already work and produce detected workflows. Your job is to make them
reflect what you actually found, not what I guessed.

1. Read `apps/api/app/domains/README.md` — it is the whole API you need.
2. Open `finance.py`. Replace the `steps` with the real ones you observed.
3. Same for `customer_support.py`.
4. `make demo && make dev` — check your workflow appears on Discovery.

**Please keep `customer_support.py` freeform.** It is the pack that proves the
platform knows when *not* to automate, and there is a test that fails if it
stops being caught. If your real customer-support work turns out to be highly
repetitive, add it as a *second* domain rather than changing this one.

**Do not touch** anything under `app/services/` — that is the central
implementation. If a domain needs something the core cannot express, open an
issue.

---

## Vijay — Sales or HR

**Your files:** `apps/api/app/domains/sales.py` **or** `hr.py`

**Pick one.** Both are marked `is_template=True` today. One domain you can
explain end to end is worth more than two you half-understand — delete the
other file or leave it as a template.

1. Research which applications that team actually lives in.
2. Find one task they repeat. Not the most interesting one — the most
   *repetitive* one.
3. Write it down as observable steps: not "review the lead" but "open the
   enquiry email", "search the CRM", "create the record".
4. Set `is_template=False` when it reflects reality.

Same rule: your file only, and `README.md` in that folder is your guide.

---

## Anushree — Chrome · Gouri — Edge

**Your folders:** `collectors/chrome/` and `collectors/edge/`

```bash
make collectors     # assembles collectors/dist/chrome and dist/edge
```

Then in your browser: `chrome://extensions` (or `edge://extensions`) →
**Developer mode** → **Load unpacked** → point at `collectors/dist/<yours>`.

Get a token from the console: **Observation → Browser extension → Connect**.
Paste it into the extension's options page. Browse normally for a few minutes,
then check `/sources` — your events should appear.

**Read this before you start, it will save you a day:** Chrome and Edge are
both Chromium and both run Manifest V3, so *the observing logic is identical*.
It lives once in `collectors/shared/` and the build copies it into both. Your
folders hold only what genuinely differs — today that is just the manifest.

So the work is **not** "write the extension twice". It is:

1. **Get it loaded and reporting** in your browser. This is the part that has
   never been verified — Chrome 137 removed `--load-extension`, so it could not
   be automated. Both shipped files are unit-tested and the collector API is
   tested end to end, but nobody has confirmed the browser's own plumbing.
2. **Find where your browser actually differs.** Permission prompts, the
   service-worker lifecycle, whether `chrome.*` needs a `browser.*` shim,
   store-packaging requirements. Put those differences in your folder.
3. **Report what breaks.** A precise bug report here is worth more than code.

If you find something that has to change in `collectors/shared/`, message
Kartik rather than editing it — that file is shared with the other browser.

---

## The rules that keep five people mergeable

**Small PRs.** A 400-line PR on Thursday gets rubber-stamped, which is the same
as not being reviewed.

**Branch per task**, `<name>/<thing>`. Never commit to `main`.

**`main` must always demo.** Before you push:

```bash
make check              # ruff + tsc + eslint + pytest — must be green
make test-collector     # only if you touched collectors/
```

If you break `main`, fixing it is your highest priority regardless of what else
is open.

**Don't get stuck.** Thirty minutes on the same error means message the group.

---

## What already works, so you don't rebuild it

Detection, scoring, the Interruption Tax, flow generation, the SOP writer, the
execution engine, replay backtesting, the trust ladder, self-healing, exception
learning, the console, and the browser collector. 131 backend tests and 33
collector checks, all green.

Your job is not to build the platform. It is to make it true about a real
domain, and to get it observing a real browser.

Read `README.md` for what the platform does, `ARCHITECTURE.md` for why each
decision was made.
