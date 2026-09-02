# DEMO — five-minute run sheet

## Before you present

```bash
make demo        # ~15s: reset to the exact known-good state
make dev         # API :8000, console :3000
```

Open three browser tabs:

1. `http://localhost:3000` — Discovery
2. `http://localhost:3000/automations` — will become the trust ladder
3. `http://localhost:3000/exceptions` — Review queue

Verify the starting state before you walk on:

```bash
curl -s localhost:8000/api/v1/clusters | python3 -m json.tool | head -20
# expect: 5 workflows, 1 flagged do_not_automate
```

`make demo` is deterministic — same seed, same ids, same numbers every time — so
what you rehearse is what the audience sees.

---

## Optional cold open · 40s · "where does the data come from?"

If you expect this question — and you will get it — answer it first rather than
defending it later.

**Observation screen.**

> "Before any of this: how does LOOP see the work at all?"

> "Six ways, and we're honest about the trade. Describing a task takes seconds
> and sees almost nothing. A desktop agent sees everything and needs an IT
> rollout. The one in the middle that actually pays — a browser extension. Two
> minutes to install, and it sees about 70% of a knowledge worker's day."

Point at the Browser extension row.

> "Note the *blind to* column. We publish what each tier cannot see. A tool that
> only tells you what it can do is selling."

> "And note this: metadata only. It records that you filled a field called
> `amount`. It never records what you typed. When you copy a value out of email
> and paste it into a sheet, we hash it — so we can prove the same value moved
> between two systems without ever receiving the value."

> "Pause is one click. Revoke deletes every event that source ever reported."

---

## 0:00 – 0:35 · The problem

**Tab 1, Discovery.**

> "Twenty-one people across five teams. Ninety days of activity logs — 9,712
> events. Nobody told LOOP what these people do."

Point at the four stat tiles.

> "It found five distinct repetitive workflows. 646 hours a year of task time.
> And 195 hours lost switching between applications — the cost of bouncing
> between tabs to finish one job, which is invisible in a normal
> time-and-motion study because nobody's timer catches it."

---

## 0:35 – 1:20 · Detection is real, and it knows when to stop

Scroll to the collapsed section. Click **Show 1**.

> "This is the part I actually want to show you first."

> "Escalation handling. 97 instances. And LOOP says: **do not automate this.**"

Read the reasoning aloud from the screen.

> "Step order varies across 99% of instances — 97 distinct sequences in 97
> instances. Seven branch points. Judgement content 67%."

> "Nothing in our seed data labels this workflow unautomatable. It's generated
> with high step-order entropy and judgement-heavy free text, and the variance
> detector has to work that out on its own. There's a test that fails if it
> stops working it out."

> "A tool that recommends automating everything isn't giving you advice."

---

## 1:20 – 2:10 · From workflow to automation

Click **Invoice email to confirmation** (783 instances, 6 people).

> "Six people do this. That's above our threshold, so it's promoted from 'saves
> you two hours a week' to an organisational opportunity — 345 hours a year."

Point at the step graph.

> "This is the observed sequence. Note the marked step — that position varied
> between instances, which is exactly where an automation needs a rule rather
> than a guess."

Point at the automatability gauge.

> "65%, and you can see all five components that produced it. Nothing here is a
> vibe."

Click **Preview SOP**, scroll it briefly.

> "Before any automation runs, you already have this: a written procedure you
> could hand a new starter on Monday. For the escalation workflow we refused to
> automate, this document is the entire deliverable — and it's still worth
> having."

Click **Open automation**.

---

## 2:10 – 3:20 · The trust ladder ⭐

**This is the demo. Slow down here.**

Point at the flow definition table at the bottom.

> "LOOP generated this from the observed workflow. Five steps. Every step
> declares the fields it reads — `depends_on`. Hold onto that, it matters in a
> minute."

Click **Run backtest**, 90 days.

> "Now: how good is it actually? We replay it against every real historical
> trigger in the window — read the count off the screen — with all side effects
> mocked, and diff what it would have done against what the human actually did."

When it lands:

> "92.71%. Not 95, not 'about 93'. And here are the failures, by name: 56
> foreign-currency invoices where the human converted to rupees and the flow has
> no conversion rule."

> "I'd rather tell you my three failure modes than have you find them."

Now the ladder.

> "Here's the thing no detection tool solves. This automation is 92% accurate.
> Would you let it post to your ledger tomorrow?"

Pause.

> "Neither would I. So it doesn't get to. It's in **SHADOW**."

> "In shadow mode, every time a trigger fires, the automation records what it
> *would* have done — and then the human does the task for real. We diff them,
> field by field, with critical fields weighted double."

Press **Simulate shadow run** — click it five times, one at a time.

> "Watch the confidence bar."

The bar fills over SSE. The Promote button turns blue.

> "It needed five runs above 90% with zero critical mismatches. It's got them.
> Now — and only now — the button unlocks."

Expand a shadow-run row.

> "And you can audit any run: predicted, observed, field by field."

Click **Promote to ASSIST**.

---

## 3:20 – 4:00 · A ladder that only goes up is a progress bar

> "But promotion isn't the interesting half."

Click **Force a critical mismatch** in Demo controls.

> "That picked a run the automation genuinely gets wrong — one of the
> foreign-currency invoices."

The rung drops back to SHADOW on its own.

> "One critical mismatch and it demotes itself. Immediately. No human pressed
> anything."

Point at the audit trail.

> "Promotion is manual. Demotion is automatic. A system that waits for
> permission to become safer isn't a safety mechanism."

---

## 4:00 – 4:40 · It survives contact with reality

> "Last thing. Automations don't fail because the AI was wrong. They fail six
> weeks later because somebody renamed a spreadsheet column."

Click **Break the source schema**.

> "That just renamed a column across ~500 stored events. For real — it's a
> database write, not an animation."

Switch to **Tab 3, Review queue**.

> "Two steps stopped resolving. LOOP captured the schema as it exists *now*,
> proposed a remapping at 92% confidence, and applied it automatically — because
> it's above threshold and the step is non-destructive."

Point at the `−`/`+` diff.

> "If it had been a step that sends email, it would be sitting here waiting for
> a human, however confident it was."

Scroll to the exception queue.

> "And the other half: when the guard holds an invoice over ten thousand rupees,
> it comes here with a reason. Resolve three the same way—"

Resolve three with **route_to_manager**.

> "—and LOOP proposes the branch rule that would have handled them. Accept it,
> and it patches the flow."

Accept the rule patch.

---

## 4:40 – 5:00 · Close

Switch to **Impact**.

> "646 hours detected. Read the coverage figure off the screen rather than from
> this script — it is whatever the automation actually earned in the runs you
> just did. It will not be 100%, because it correctly stops and asks on the
> invoices it is unsure about, and we count those against ourselves."

> "The brief said: get from 'this task is repetitive' to 'this task can now be
> automated.' We think there's one more step, and it's the one that decides
> whether any of this ships: **'this task has earned the right to run without
> me watching.'**"

---

## Cheat sheet

| Moment | Where | Action |
|---|---|---|
| Do-not-automate | Discovery | **Show 1** in the collapsed section |
| SOP | Workflow detail | **Preview SOP** |
| Honest backtest | Automation | **Run backtest**, 90 days |
| Bar fills | Automation | **Simulate shadow run** ×5 |
| Button unlocks | Automation | **Promote to ASSIST** |
| Auto-demotion | Demo controls | **Force a critical mismatch** |
| Self-healing | Demo controls → Review queue | **Break the source schema** |
| Rule learning | Review queue | Resolve 3 → **Accept** |
| Payoff | Impact | — |
| Where the data comes from | Observation | — (optional cold open) |

## If something breaks on stage

| Symptom | Fix |
|---|---|
| Confidence bar frozen | SSE dropped; reload the page — state is server-side, nothing is lost |
| Console shows "Cannot reach the API" | `make api` in a spare terminal |
| Numbers look wrong | `make demo` — 15 seconds, fully deterministic |
| `break-schema` returns 409 | Already broken this session; `make demo` first |
| Upload misbehaves | Use **Add activity data → Use example** and describe the task in prose instead |

## Every command, in order

```bash
make demo
make dev

# starting state
curl -s localhost:8000/api/v1/clusters | python3 -m json.tool | head -20

# if you prefer driving from the terminal:
AID=$(curl -s localhost:8000/api/v1/automations \
  | python3 -c "import json,sys;d=json.load(sys.stdin)['items'];print(sorted(d,key=lambda a:-a['annual_hours'])[0]['id'])")

curl -s -X POST localhost:8000/api/v1/automations/$AID/replay \
  -H 'content-type: application/json' -d '{"days":90}' | python3 -m json.tool | head -20

curl -s -X POST localhost:8000/api/v1/demo/simulate-shadow-run \
  -H 'content-type: application/json' -d "{\"automation_id\":\"$AID\",\"count\":5}"

curl -s -X POST localhost:8000/api/v1/automations/$AID/promote \
  -H 'content-type: application/json' -d '{}'

curl -s -X POST localhost:8000/api/v1/demo/simulate-shadow-run \
  -H 'content-type: application/json' \
  -d "{\"automation_id\":\"$AID\",\"count\":1,\"force_mismatch\":true}"

curl -s -X POST localhost:8000/api/v1/demo/break-schema \
  -H 'content-type: application/json' -d '{}'
```
