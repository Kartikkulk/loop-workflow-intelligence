# Manual demo — AWS invoices, filed by an automation LOOP found on its own

Roughly four minutes, driven by hand. Nothing here is scripted playback: the
PDFs are real files, the automation is generated from the activity log at run
time, and the filing genuinely moves things on disk.

---

## Before you walk in

Two terminals and a browser.

```bash
# terminal 1 — leave it running
make api

# terminal 2 — leave it running
make web

# terminal 2, once, to get to the starting state
make invoices
```

Browser tabs, in this order:

1. `http://localhost:3000/discovery`
2. `http://localhost:3000/automations`
3. A Finder window at `~/LOOP-Invoices`

Check before you start: **96 PDFs in `Inbox`, no year folders yet.**

```bash
ls ~/LOOP-Invoices/Inbox | wc -l     # 96
ls ~/LOOP-Invoices                   # just: Inbox
```

---

## 0:00 — the mess

**Show the Finder window.** 96 invoice PDFs in one flat folder.

> "Twelve months of AWS invoices. Eight linked accounts, billed separately
> every month. Somebody on the finance team opens each one, reads the total,
> works out which month it belongs to, drops it in the right folder, and notes
> it on that month's ticket. Nobody enjoys this."

Open one PDF. It is a real invoice — account number, billing period, charges by
service, a total.

---

## 0:40 — what LOOP found

**Tab 1, Discovery.**

> "We never told LOOP what these people do. We gave it their activity log —
> 384 events — and it found this."

Point at the workflow:

```
files:read → pdf:extract → files:create → jira:send
96 runs · 3 people · 94.4% automatable · effort 2/5
```

> "Four steps, done the same way 96 times by three different people. It scores
> 94% automatable because the order almost never varies — and that number comes
> out of the log, not out of a config file."

Say the honest part before anyone asks:

> "Six hours a year. It is a monthly job, so it cannot be a big number, and we
> are not going to dress it up as one."

---

## 1:30 — the automation

**Tab 2, Automations.** Open the one automation.

> "LOOP wrote this from the observed steps. Read the file, pull the total out
> of the PDF, file it under year and month, add a note to the ticket."

Point at the guard:

> "It also decided this one step reaches outside the machine, so it is marked
> irreversible — and anything over ten thousand rupees stops and asks a person.
> Nobody configured that threshold for this workflow; it was attached because
> the workflow actually carries an amount."

Point at the trust level: **SUGGEST**.

> "It has not been allowed to do anything yet."

---

## 2:15 — the dry run

**Terminal 2.**

```bash
LOOP_FILES_ROOT=~/LOOP-Invoices \
  apps/api/.venv/bin/python apps/api/scripts/file_invoices.py
```

```
filed 80 | guard held 16 | failed 0
```

> "That is the whole run, with nothing touched. Eighty it would complete on its
> own. Sixteen it refuses to *finish* — they are over the limit, and they are
> the production accounts. It files them, then stops before telling anyone."

**Show the Finder window again.** Still 96 files in Inbox. Nothing moved.

---

## 2:50 — let it run

```bash
LOOP_FILES_ROOT=~/LOOP-Invoices \
  apps/api/.venv/bin/python apps/api/scripts/file_invoices.py --yes
```

**Switch to Finder and refresh.** Year folders appear. Open `2025/10`.

> "Those are the same files. They have actually moved. This is not a preview of
> what it would do."

```bash
find ~/LOOP-Invoices -name '*.pdf' -not -path '*/Inbox/*' | wc -l   # 96
find ~/LOOP-Invoices/Inbox -name '*.pdf' | wc -l                   # 0
```

All 96 are filed, including the 16 the run reported as held. That is correct,
and it is worth saying out loud rather than hoping nobody notices:

> "Every invoice got filed, including the expensive ones. The guard does not
> stop the filing — moving a file is reversible, so it is not what needs
> protecting. What it stopped is the last step: those sixteen never got their
> note posted to the ticket. They are waiting for a person to approve the part
> that reaches outside this machine."

If someone pushes on it, that is the design: guards hold **irreversible** steps,
and the flow marks exactly one step irreversible — `s4`, the Jira note.

---

## 3:20 — it keeps working (the part people remember)

Leave this running in a terminal beside the Finder window:

```bash
make watch
```

> "That is the automation waiting for work. Same as it would be on a real
> machine — invoices do not arrive in batches of ninety-six, they turn up one
> at a time."

Now drop one in, in another terminal:

```bash
make invoice
```

Within two seconds the watcher prints the result and the file appears in its
year/month folder. Press `make invoice` a few more times.

```
  filed   AWS-202609-0082-backup-dr.pdf     ->  09
  held    AWS-202609-0074-ml-training.pdf   (over the policy limit — note not posted)
  filed   AWS-202609-0013-prod-platform.pdf ->  09
```

> "One of those was over the limit. It still filed it — that part is
> reversible. What it would not do is tell anyone, because that reaches outside
> the machine. It is waiting for a person on that one."

Roughly two in five drops land over the limit, so a couple of presses will
produce one. If you want to guarantee it, press it four or five times.

---

## 3:40 — where it runs for real (optional, needs Docker)

```bash
docker compose up -d n8n
```

Open `http://localhost:5678`, then:

```bash
apps/api/.venv/bin/python apps/api/scripts/push_to_n8n.py --schedule hourly
```

> "LOOP works out what repeats and whether it is safe to hand over. It does not
> need to own the connectors — n8n already has several hundred, with the OAuth
> already solved. So the discovered workflow gets exported into it."

Show the node list it prints. Point at **Within policy limit** — the guard
travels with the workflow, as an IF node in front of the Jira step.

> "It arrives switched off, with no credentials. You pick which Jira account
> each node uses, in n8n, and then you turn it on. Nothing gets connected to
> anybody's mailbox because a script pushed it."

Add `--push` to actually create it, once you have made an API key in
n8n (Settings → n8n API) and put it in `.env` as `LOOP_N8N_API_KEY`.

---

## 3:55 — close

> "Detection is a pure function of the activity log, so re-running it gives the
> same answer. Promotion up the trust ladder is manual; demotion is automatic.
> And Jira is still in dry run — moving a file is reversible, writing to
> somebody's tracker is not, so that one stays off until it is deliberately
> turned on."

---

## Reset, between runs

```bash
make invoices
```

Moves every filed invoice back to `Inbox`, clears the detected workflow and the
automation, regenerates, and rebuilds. Safe to run repeatedly.

| Command | What it does |
|---|---|
| `make invoices` | Reset to the starting state |
| `make watch` | File invoices as they arrive — leave on screen |
| `make invoice` | Drop one new invoice in, dated today |

---

## If it goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `make invoices` cannot reach the API | `make api` is not running | Start it, then re-run |
| Discovery is empty | The upload did not land | `make invoices` again |
| Every invoice fails on `s4` | Jira credentials are set but the site is wrong | `unset LOOP_JIRA_DRY_RUN`, or fix `.env` |
| Everything is held, nothing filed | The guard threshold was lowered | Check `requires_approval_if` on the automation |
| Files already in year folders | A previous run filed them | `make invoices` puts them back |

## What is not in this demo

Say it plainly if asked, rather than being caught out:

- **No Gmail.** The Gmail connection is metadata-only by design and cannot read
  message bodies or attachments, so invoices arrive as files in a folder, not
  as email.
- **Jira does not actually get written.** The connector is real and implemented,
  but it stays in dry run until `LOOP_JIRA_SITE_URL`, `LOOP_JIRA_EMAIL` and
  `LOOP_JIRA_API_TOKEN` are set and `LOOP_JIRA_DRY_RUN=false`.
- **The invoices are generated.** They are real PDFs with real totals that the
  extractor genuinely parses, but Amazon did not send them.
