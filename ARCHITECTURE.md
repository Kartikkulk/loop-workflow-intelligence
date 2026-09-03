# How Kriyā AI Works

Kriyā AI watches how people work, spots the tasks they repeat, and turns the safe
ones into automations. This doc follows the data from start to finish, in plain
language.

## The one-line version

```
Watch work  →  Find repeated tasks  →  Score them  →  Build an automation  →  Prove it's safe  →  Let it run
```

Everything is built from one thing: a stream of **events** (small records of "who
did what, where"). Every screen and number in the app is calculated from those
events. Nothing else is stored as the "truth".

## Step 1 — Where the data comes from

Kriyā AI collects **events**. An event is just: a user, a time, an app, and an
action. For example:

```
Priya  ·  10:02  ·  gmail   ·  read an invoice email
Priya  ·  10:03  ·  pdf     ·  extracted the fields
Priya  ·  10:04  ·  sheets  ·  created a new row
Priya  ·  10:05  ·  gmail   ·  sent a confirmation
```

Events arrive four ways:
- **Browser extension** — watches activity in Chrome/Edge (the main way)
- **File upload** — a CSV or JSONL activity log
- **Plain English** — you describe a task and the AI turns it into events
- **Demo data** — synthetic events so the app has something to show

Privacy note: Kriyā AI records the *name* of a field (like "amount"), never the
value you typed. It's metadata, not surveillance.

## Step 2 — Group events into tasks

A raw event stream is just noise until you cut it into individual **task
instances** — one run of one task. Kriyā AI splits the stream when:
- the person is idle for more than 15 minutes, or
- they clearly switch to something unrelated (new tab, different app).

So the four events above become **one task instance**: "handle an invoice email".

## Step 3 — Turn each task into a fingerprint

Each task instance is boiled down to a **signature** — the sequence of steps with
all the specific details stripped out:

```
gmail:read  →  pdf:extract  →  sheets:create  →  gmail:send
```

Two people doing the same task in slightly different ways still produce very
similar fingerprints.

## Step 4 — Find the repeats (this is the core AI/algorithm)

Kriyā AI compares all the fingerprints and groups the matching ones into a
**workflow**. It does this in two passes:
1. Exact matches get grouped instantly.
2. Near-matches (same steps, slightly different order) get grouped by comparing
   how similar the sequences are.

A group only counts as a real workflow if it happened **at least 8 times** and
has **at least 3 steps**. That filters out one-off noise.

Result: from thousands of messy events, Kriyā AI surfaces a handful of clear,
repeated workflows — without anyone telling it what to look for.

## Step 5 — Score each workflow

For every workflow Kriyā AI calculates:

- **Time cost** — how many hours a year this eats:
  `hours = task length × how often × 48 weeks × number of people`
- **Automatability (0 to 1)** — how *consistent* the workflow is. If people do
  it the same way every time, it scores high. If the steps jump around or it
  needs human judgement, it scores low.

If automatability drops below 0.4, Kriyā AI flags it **DO NOT AUTOMATE** — and it
reaches that conclusion from the data, not from a label someone set. Knowing when
*not* to automate is a feature, not a gap.

## Step 6 — Build the automation

For workflows worth automating, the AI writes a **flow definition** — a runnable
recipe of the steps, what each step reads, and safety guards (e.g. "anything over
₹10,000 must be approved by a human"). It also writes a plain-English **SOP** you
could hand a new employee.

The AI is kept on a leash here:
- Output must match a fixed JSON shape, so it can't produce garbage.
- Steps that send or delete anything are automatically marked "irreversible".
- If no AI model is running, a built-in fallback still produces the flow. The app
  works completely offline.

## Step 7 — Prove it's safe (the trust ladder)

This is the heart of Kriyā AI. A new automation does **not** get to act. It climbs a
ladder, one rung at a time:

```
OBSERVE  →  SUGGEST  →  SHADOW  →  ASSIST  →  AUTONOMOUS
```

- **Replay** — run the automation against past history and check how often it
  would have matched what the human actually did. The accuracy shown is honest,
  never rounded up.
- **Shadow** — the automation quietly predicts what it *would* do while the human
  does the real task, and the two are compared field by field.
- **Promote** — only after 5 recent runs score above 90% with zero critical
  mistakes.

Two rules make it trustworthy:
- **Promotion is manual, demotion is automatic.** One serious mistake drops it
  back down instantly, no human needed.
- A single wrong amount on a ledger outvotes a great average score.

## Step 8 — Keep it working

Automations don't usually fail on day one — they fail weeks later when someone
renames a column. Kriyā AI handles that:

- **Self-healing** — if a field stops matching, Kriyā AI looks at the current data,
  guesses the new name, and auto-fixes it *only* if it's confident and the step
  is safe.
- **Learning from exceptions** — when the automation stops and asks a human, Kriyā AI
  watches the answers. After a few similar cases it suggests a rule to handle them
  — but a human always approves it.

## The pieces, at a glance

```
Browser / upload / prose  ──►  EVENTS  ──►  task instances  ──►  workflows
                                                                    │
                                              score & rank ◄────────┘
                                                    │
                                          build automation + SOP
                                                    │
                                    replay → shadow → promote (trust ladder)
                                                    │
                                        self-healing + rule learning
```

## What's real and what's mocked (honest limitations)

- **Detection is real.** The workflow-finding runs on actual event data.
- **Execution connectors are mocked.** The plumbing to really touch Gmail or an
  ERP is written but hasn't run against a live system.
- **Demo data is synthetic** — deliberately realistic, but not a real company's.
- **No login/authentication** — it's a single-user, local app.

## For developers: the tech

- **Backend:** Python, FastAPI, SQLAlchemy, SQLite by default (Postgres via
  Docker). Live updates over SSE.
- **Frontend:** Next.js 15, React, TypeScript, Tailwind. All API calls go through
  one file (`lib/api/client.ts`).
- **AI:** a local model via Ollama, with a deterministic fallback for every
  feature so nothing breaks offline.
- **Data model:** the important tables are `events` (the source of truth),
  `clusters` (detected workflows), `automations` (flow + trust level), and
  `shadow_runs` (prediction vs reality).
