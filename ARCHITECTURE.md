# Architecture

How data moves through LOOP, and why each decision was made the way it was.

---

## 1. The shape of the system

Everything downstream of the event log is **derived**. The event stream is the
only authoritative store; clusters, scores, automations and SOPs are all pure
functions of it. That single property buys three things:

- `make demo` is a truncate plus a re-run, not a restore from a fixture.
- Re-running detection is idempotent, so the console can never show a state
  that the log does not justify.
- Adding an ingestion source cannot corrupt detection, because detection never
  learns where an event came from.

```
ingestion adapter ─→ canonical events ─→ task instances ─→ clusters ─→ scores
                                                                 │
                                          ┌──────────────────────┤
                                          ▼                      ▼
                                    flow definition            SOP
                                          │
                          ┌───────────────┼───────────────┐
                          ▼               ▼               ▼
                     replay mode     shadow mode      live mode
                          │               │
                          └──── field-level diff ──── trust ladder
                                          │
                                    drift + rule learning
```

---

## 2. Observation (F0)

Detection is downstream of a harder problem: seeing the work at all.

### 2.1 Sources are rows, not strings

A `Source` is a first-class table rather than a string on each event, because
three things must be true *per source* and are meaningless globally:

- **consent** has to be recorded and revocable — ingestion checks
  `consent_granted_at` and returns 403 without it;
- **capture** has to be pausable by the person being observed;
- **coverage** has to be reportable, so an operator knows what LOOP cannot see.

Coverage is reported as the **best connected tier, not the sum**. The tiers
overlap heavily — a browser extension and a Google Workspace connector see much
of the same activity — so adding them would claim more than is true.

### 2.2 Interpretation is server-side

The collector sends near-raw signals: `interaction`, `url`, `label`, `role`,
`field_name`. Everything interpretive — which application, which verb, which
object type — happens in `services/web_activity.py`.

That split is deliberate. Interpretation heuristics improve constantly, and
pushing a new one to a server is a deploy; pushing one to an installed extension
is a release cycle across every laptop in the company.

### 2.3 Applications onboard themselves

`canonical_app_for_host` resolves a hostname to an app key, falling back to the
registrable brand rather than a generic `browser` bucket. Multi-label public
suffixes are handled explicitly, because getting that wrong names the app after
a country code:

```
app.northwind-erp.co.in   → northwind-erp   (not "co")
portal.northwind.com.au   → northwind       (not "com")
finance-tool.internal     → finance-tool
```

Combined with the app vocabulary being a **table**, this means an employee
onboards an unanticipated internal tool simply by using it — no code change, no
migration, no configuration.

### 2.4 The copy-paste bridge

The brief names "moving information between systems" directly, and this is how
LOOP sees it. The collector hashes copied text in the content script; the hash
leaves, the text does not. The server correlates a hash seen with `extract` in
one app against the same hash seen with `create` in another:

```
copy  in gmail   digest a1b2c3d4…
paste in sheets  digest a1b2c3d4…    within 10 minutes, different app
                 → transferred_from: gmail, transferred_to: sheets
```

Two details matter. The window is anchored to the **batch's own earliest event**,
not to wall-clock now: a collector queues offline and may flush activity from
twenty minutes ago, and anchoring to now silently dropped every transfer in such
a batch. And the window is re-checked **between the pair itself**, so two
unrelated copies of the same value hours apart are not linked.

### 2.5 Privacy as implemented

Not a policy — the mechanics.

| Guarantee | Where it lives |
|---|---|
| Metadata-only default | `CaptureScope.METADATA_ONLY`; field *names* recorded, values never |
| URL values stripped | `content.js` `sanitiseUrl` **and** `web_activity.sanitise_url` |
| Page titles withheld | `content.js` reads the scope from storage; `background.js` re-strips |
| Consent enforced | `Source.can_ingest` gates `/collect/events` |
| Pause governed centrally | collector polls `/collect/config`; ingest returns `423` |
| Revocation deletes | `DELETE /sources/{id}` removes every event with that `source_id` |
| Denylist enforced twice | locally in `background.js`, again in `sources.is_denied` |

**Why URL sanitisation is not optional.** A GET form puts every field straight
into the query string, so `?vendor=Kaveri+Logistics&secret=hunter2` is a
completely ordinary URL. A collector that reports `location.href` therefore
leaks exactly the values it promises not to read. Parameter *names* are kept
because they are useful schema signal; values are dropped. It is applied on both
sides: the collector is the right place (a value stripped there never crosses
the network), but an old or third-party collector cannot be trusted to have done
it. A test submits a real GET form and asserts no value appears in any signal —
which is how the leak was found in the first place.

**The organisational threshold is a privacy mechanism.** A cluster becomes an
organisational opportunity only above three distinct users. Reporting work at
the level of a group rather than an individual is what separates a process tool
from a surveillance tool, and it happens to be the same threshold that makes the
finding worth acting on.

### 2.6 Collector reliability

`chrome.storage.local` has no atomic read-modify-write, and signals arrive in
bursts. The original `enqueue` read the queue, appended, and wrote it back; two
overlapping calls each read the same array and wrote back their own copy, so one
was **silently lost** — event loss under exactly the bursty conditions the
collector exists to observe. Every mutation now passes through a promise chain,
and `flush` removes sent items *by count* from the front rather than replacing
the queue with a stale remainder, so anything enqueued mid-request survives.
The network call happens outside the lock: holding it across a round trip would
stall every enqueue for the duration.

---

## 3. Ingestion (F1)

Four input paths, one output type.

| Adapter | Input | Notes |
|---|---|---|
| CSV | `.csv` upload | Bad rows are reported per-line, never fatal |
| JSONL | `.jsonl` / `.ndjson` | Same |
| Describe | Plain English | LLM tool use, with a keyword-ordering fallback |

**Why the prose path is not a gimmick.** Most teams have no usable activity log.
Asking them to instrument their tools before they can evaluate the product is a
non-starter, and "describe your Monday morning" is an input anyone can provide.
It doubles as the stage fallback if a file upload misbehaves.

**Vocabulary normalisation.** `app` and `action` are stored in **registry
tables**, not Python enums. Onboarding Outlook, Teams or SAP must not require a
code change plus a migration touching every service. An alias table maps common
real-world labels (`Excel` → `sheets`, `Microsoft Exchange` → `outlook`,
`opened` → `read`, `append` → `create`) onto the canonical vocabulary.

Unrecognised columns are swept into `payload` rather than dropped. Real exports
always carry extra fields, and drift detection needs them.

---

## 4. Workflow DNA (F2)

### 4.1 Sessionising — deciding what "one task" means

Get this wrong and no amount of downstream cleverness recovers: too coarse and
every task merges into one blob, too fine and one workflow shatters.

An instance ends on any of:
- an idle gap > 15 minutes (configurable),
- an explicit `session_id` change, when the source supplied one,
- a **hard context reset** — a Slack read or a browser navigation, which
  demonstrates the user has left the task.

Instances of fewer than two events are discarded: a single observed action is
not a workflow.

### 4.2 Signature — and the interruption collapse

A signature strips all specific values, leaving ordered `app:action:object_type`
tokens:

```
gmail:read:invoice_email → pdf:extract:fields → sheets:create:row → gmail:send:confirmation
```

Then two patterns are removed:
- an immediately repeated step, and
- an `A → B → A` bounce, where the user left a step and came straight back.

**Why this matters more than it sounds.** A workflow's *identity* should not
change because somebody glanced at the ERP halfway through. Measured on the seed
data, without this collapse the workflows fragmented into **227 near-identical
clusters** — one per place an interruption happened to land. With it: **5**.

The interruptions are not thrown away. `count_context_switches` reads them
straight off the events, so the Interruption Tax still charges for every one.
The collapse changes what counts as the *same workflow*; it does not change what
counts as *cost*.

### 4.3 Clustering — two stages, three signals

**Stage 1** buckets instances by exact signature hash. Cheap, and it resolves
most instances, because repetitive work really is often identical.

**Stage 2** runs agglomerative clustering (average linkage, precomputed
distances) over the bucket representatives, blending:

| Signal | What it catches | What it misses alone |
|---|---|---|
| Normalised Levenshtein on the token sequence | order-sensitive structure | synonymous steps |
| **Jaccard on the token set** | **same steps, different order** | structure entirely |
| Cosine on a signature-text embedding | vocabulary similarity | merges workflows sharing words |

Levenshtein operates on sequences as **lists of tokens**, not concatenated
strings, so one substituted step costs exactly one edit rather than a number of
edits proportional to how long that step's name happens to be.

**Why the set-overlap term earns its place.** A genuinely high-variance workflow
performs the same handful of steps in a different order every time. Under
order-sensitive similarity alone, it shatters into singleton clusters and never
clears the minimum-instance floor — so the system stays **silent about exactly
the workflows a human most needs warning about**. On the seed data,
`customer_escalation` went from a largest cluster of 2 instances (invisible) to
87 (a first-class do-not-automate finding). Detecting that a task should *not*
be automated is a headline result, and it depends on this term.

**Threshold selection.** 0.35, chosen by sweeping it against ground truth rather
than by intuition. At that value: 5 clusters, 99.9% purity, all five seeded
workflows recovered. Same-workflow pairs score ≥ 0.82 and different-workflow
pairs ≤ 0.09, so the operating point sits in a wide empty margin — and a test
asserts that margin stays wider than 0.3, so a future weight change cannot leave
the threshold on a knife edge.

**Embeddings.** `sentence-transformers` when installed; otherwise a
character-n-gram (3–5, `char_wb`) TF-IDF projection. Character n-grams beat word
tokens here because word tokenisation splits on the colons in
`app:action:object`. The fallback keeps a clean clone installable without a 2GB
torch download, and on strings this short and templated it performs comparably.

**Floors.** A cluster needs ≥ 8 instances and ≥ 3 steps. The step floor exists
because a two-token signature is almost always a truncation artefact — a longer
workflow cut in half by an unrelated event — and surfacing those double-counts
the same work and clutters the ranking with two-hour "workflows".

**Representative.** The medoid (highest total similarity to all members), not
the modal signature, because the medoid degrades gracefully when no variant
dominates. Capped at a 200-signature sample: medoid selection is O(n²) and
precision beyond that does not change the choice.

---

## 5. Scoring (F3)

```
annual_hours   = median_duration_hrs × instances_per_user_per_week × 48 × distinct_users
priority       = (annual_hours + interruption_tax_hours) × automatability ÷ build_effort
automatability = 1 − (0.35·entropy + 0.20·spread + 0.20·branch_penalty + 0.25·judgement)
```

### Interruption Tax

A context switch is an `A → B → A` bounce within 10 minutes — **not** any
application change. Moving from email to a spreadsheet once, deliberately, is
not an interruption; bouncing back to what you were doing is. Counting every app
change would overstate the tax by roughly a factor of three on this dataset.

Reported **separately** from raw task time, deliberately. It is the softest
number in the product — the 4 minutes/switch is a conservative literature
estimate, not a measurement of this organisation — so it is presented where it
can be argued with rather than blended into a headline figure.

### Automatability = 1 − variance

Four inputs, weighted so that the **measured, structural** signals dominate and
the model-scored one carries the least:

| Component | Weight | Source |
|---|---|---|
| Step-order entropy (normalised Shannon over distinct signatures) | 0.35 | measured |
| Parameter value spread (mean normalised cardinality per payload key) | 0.20 | measured |
| Branch penalty (positions with > 1 observed token, ÷ step count) | 0.20 | measured |
| Judgement ratio | 0.25 | LLM, with a free-text-ratio fallback |

Below 0.4 → **DO NOT AUTOMATE**, with generated reasoning citing the actual
numbers. Surfaced as a first-class list in the console, never as an error state.

**Why the weighting is not cosmetic.** A workflow is flagged because its
instances genuinely disagree with each other in the log — a fact — not because a
model was asked for an opinion about it. With no API key, the judgement term
falls back to a measured free-text ratio and the flag still fires correctly.

---

## 6. Generation (F4)

Flow definitions come from **Anthropic tool use**, so the shape is guaranteed by
the schema. Free-form JSON parsing is never used: a malformed response becomes
impossible rather than merely unlikely.

Model output is then **sanitised against invariants we enforce ourselves**:

- a step may never depend on a field no earlier step produces (otherwise the
  automation fails on its first run for a reason that *looks* like drift);
- every step whose action is `send` or `delete` is added to
  `guards.irreversible`, whatever the model said;
- step outputs are unioned with the payload keys **actually observed** on that
  step in the log.

**That last rule was a real bug, and it is worth recording.** An early version
emitted generic outputs (`subject`, `sender`, `body`) from a fixed
action-to-field map. Those fields did not exist in the source data, so the
replay diff found nothing comparable and reported an accuracy of 0.128 — a
number that measured neither the automation nor anything else. Generating
against observed reality is what makes the backtest a measurement.

Every prompt lives in `app/llm/prompts/*.md` and is loaded at runtime. Prompts
buried in f-strings cannot be iterated on under time pressure.

The Anthropic client wraps retry-with-backoff, a token/cost counter, and an
in-memory cache keyed on prompt hash. During a hackathon the same analysis runs
fifty times; the cache saves both money and demo latency.

**Every call site supplies a `fallback` callable.** With no API key — or after
all retries fail — the fallback runs. A network problem on stage degrades output
quality rather than breaking the demo, and the whole product is demonstrable
offline.

---

## 7. Execution engine (F5)

One engine. Two switches: whether side effects are real, and what the result is
compared against.

| Mode | Side effects | Compared against |
|---|---|---|
| `replay` | mocked | the historical log |
| `shadow` | mocked | live human actions |
| `live` | real | nothing |

**This is the decision that made the scope achievable.** Because the comparison
lives *outside* the engine, shadow mode cost almost nothing once replay existed
— and the trust ladder, the product's centrepiece, is built entirely out of that
comparison.

**Where the safety guarantee lives.** The engine forces mock connectors for
`replay` and `shadow`, once, in `Engine.run`. Not in each connector. A newly
added connector therefore cannot forget to be safe.

**Guards are not `eval`.** A flow definition is partly model-generated and is
therefore untrusted input. Conditions are matched against
`field <op> literal` by a regex and compared by a restricted comparator. An
unparseable guard returns `False` — **failing closed**, so a malformed guard
never silently permits an action.

**Mock connectors are not stubs.** They perform the real dependency resolution
a live connector would, reporting exactly which `depends_on` fields failed to
resolve — because that resolution *is* the drift signal. A mock that always
succeeded would make self-healing undetectable and untestable.

**`None` outputs are retained.** Dropping a field the automation failed to
produce would let the diff score it as "not compared" instead of "wrong".
Dependency resolution already refuses to be satisfied by a `None`, so keeping
them cannot mask a real failure.

---

## 8. Diffing, replay and the trust ladder (F6, F7)

### One comparator

Replay and shadow mode ask the same question — did the automation do what the
human did? — so they share one comparator. Critical fields (`amount`, `vendor`,
`po_number`, `recipient`, `status`, …) are **weighted double**: a wrong vendor
name and a wrong ledger amount are not equally forgivable.

Only fields present in **both** dictionaries are scored. Penalising the
automation for fields the log never recorded would make accuracy a measure of
log completeness. Instances with **no** comparable fields are reported as their
own `not_comparable` category — counting them as correct would inflate accuracy,
counting them as failures would blame the automation for gaps in the log.

### What replay is allowed to see

`trigger_payload` is restricted to the **first event** of the instance. Letting
the automation read the whole instance would leak the human's later decisions
into its own prediction and inflate accuracy to a meaningless 100%.
`source_payload` additionally excludes decision fields (`status`, `amount_inr`,
`approval`, `note`) — anything that exists only because a person decided
something.

Accuracy is **truncated, not rounded**. Reporting 0.94 when the figure is 0.9384
is a small lie a reviewer is entitled to catch.

### The ladder

```
OBSERVE → SUGGEST → SHADOW → ASSIST → AUTONOMOUS

promote if   avg(score) over last 5 ≥ 0.90  AND  criticals == 0  AND  runs ≥ 5
demote  if   any critical mismatch in the last 3 runs
```

Three deliberate asymmetries:

1. **Promotion is manual; demotion is automatic.** A system that waits for
   permission to become safer is not a safety mechanism.
2. **One critical mismatch outvotes a perfect average.** No amount of good
   aggregate scoring buys past a wrong amount on a ledger.
3. **Demotion looks only at a 3-run window.** Otherwise an automation could
   never recover from a single historical failure, and the ladder would be
   one-way in the other direction.

Confidence is damped by `min(1, runs / required)` while the window fills, so one
perfect run does not read as full confidence.

A forced promotion is permitted, and is **recorded in the audit trail as an
override**. An override that left no trace would defeat the point of having a
ladder.

Promotion state is pushed over **SSE** (`/automations/{id}/stream`), emitting
only on change plus a keepalive. The stream uses its own short-lived sessions
rather than the request-scoped dependency, because a streaming response outlives
the transaction that dependency would hold open. Demotion is enforced inside the
stream too, so a critical mismatch is reflected on screen without a refresh.

---

## 9. Self-healing and exception learning (F8)

### Drift

When a `depends_on` field stops resolving, LOOP reads the schema **as it exists
now** from recent events — derived from data, not declared in config, which is
what makes drift genuinely *detectable* rather than merely configurable — and
proposes a remapping via three rules in descending order of evidential strength:

| Rule | Confidence | Why this order |
|---|---|---|
| Known synonym (`Vendor` ↔ `Supplier Name`) | 0.94 | Semantically identical but share almost no characters; no string metric would find them |
| **Token containment** (`Vendor` → `Vendor Legal Name`) | 0.92 | A renamed column that gained a qualifier keeps every original token. Generalises to `amount` → `Net Amount`, `date` → `Invoice Date` |
| Fuzzy `token_set_ratio` | ≤ 0.88 | Deliberately capped **below** the auto-apply threshold, so a merely plausible string match always reaches a human |

Auto-applies when confidence ≥ 0.9 **and** the step is non-destructive. A rename
on a step that sends email or writes a ledger is never auto-applied, however
confident the proposal — the wrong guess could not be undone.

Healing **iterates**. The engine halts at the first hard failure, so one pass
reveals only the first broken step; a rename usually breaks several, and healing
one of them is not healing the automation. Bounded at 8 passes.

### Rule learning

Guard holds and low-confidence executions route to a human queue with a stated
reason. Each resolution stores an `(input features → human decision)` pair,
grouped by a **signature key** that buckets the *shape* of the input
(`amount_over_10k`, `foreign_currency`, `unresolved_dependency`) rather than raw
values — grouping on raw amounts would never find three matching cases.

At ≥ 3 matching cases, a branch rule is proposed. **Learned rules are never
auto-applied**: a rule changes what the automation *decides*, not merely where
it reads a field from, so a human always signs off.

### Coverage

Coverage is the share of triggers handled without involving a person, measured
from the largest available sample — a 773-trigger backtest is far better
evidence than five shadow runs.

**Guard holds count against coverage.** An automation that stops and asks on 15%
of invoices covers 85% of the work; reporting 100% while the backtest openly
shows 113 withheld runs would be an internal contradiction a reviewer would
rightly catch.

**Learned rules earn coverage back — but only when their action resolves the
case without a person.** A rule that routes to a manager automates the *routing
decision*, which is real value, but the manager still has to act. Crediting it
as autonomous coverage would inflate the number in precisely the direction that
flatters us.

---

## 10. The seed generator

The demo's credibility rests on this file, so its properties are explicit.

- **Deterministic.** Ids come from a counter salted with the seed, so the same
  seed produces byte-identical output. (Random ids were also colliding: 8,500
  events from a 4-byte space hit a birthday collision roughly 1 run in 120.)
- **Facts are drawn once per instance**, then projected into each step's payload.
  If each step drew its own random amount, one invoice would carry a different
  value at extraction than at ledger entry, and a backtest would be measuring
  the generator's inconsistency rather than the automation's accuracy. This was
  a real bug: it held replay accuracy at 13.9%.
- **Variance is real**: optional steps at 30%, occasional adjacent reordering,
  genuine anomalies, and interleaved `A → B → A` lookups so the Interruption Tax
  has something to measure.
- **Workflow 5 is never labelled.** It is generated freeform — a random subset
  of a step pool in a random order, with long judgement-laden notes — so the
  variance detector must reach the do-not-automate conclusion itself.
- **A genuine failure mode is planted**: ~8% of invoices arrive in a foreign
  currency, and the human converts before writing the ledger. The generated flow
  has no conversion rule, so replay finds these. An honest backtest needs real
  failures to name.
- **A genuine schema change at day 60**: `Vendor` → `Supplier Name`, so drift
  detection has something to discover in the data rather than in a fixture.

---

## 11. Data model

| Table | Holds |
|---|---|
| `sources` | Onboarded observers: kind, consent, capture scope, token hash, denylist |
| `app_registry`, `action_registry` | Source-agnostic vocabulary; new apps self-register |
| `events` | The canonical stream — the only authoritative store; `source_id` traces provenance for revocation |
| `task_instances` | Sessionised instances, with signature and hash |
| `clusters` | Mined workflows, aggregates, scores, variance breakdown, `observed_fields` |
| `automations` | Flow definition, trust level, confidence, replay sample, learned rules, audit trail |
| `executions` | Engine runs in any mode |
| `shadow_runs` | Prediction vs observation, per-field matches, score |
| `exception_cases` | Human queue, input features, decision |
| `patches` | Drift remappings and learned rules |

`ground_truth_workflow` is carried on events **and read by no detection
service**. It exists solely so tests can assert that detection independently
recovered the right answer.

JSON columns are always **reassigned, never mutated in place** — SQLAlchemy does
not mark an in-place mutation dirty, and the change would silently not persist.

---

## 12. Frontend

- **Next.js 15 App Router.** Every screen is a client component: this is a live
  operations console, and server rendering data that changes on every shadow run
  buys nothing.
- **One HTTP boundary.** `lib/api/client.ts` is the only place `fetch` is
  called. It unwraps FastAPI's nested validation detail into a readable string,
  because a toast that says `[object Object]` is worse than one that says
  nothing.
- **TanStack Query** with a 5-second stale time and no focus refetch. A demo must
  never show a stale number after an action, and a background refetch mid-pitch
  is a liability.
- **SSE via native `EventSource`.** The stream payload is treated as
  authoritative over the cached query while connected, so a demotion appears the
  instant it happens. `onerror` deliberately does not close the source —
  `EventSource` reconnects on its own.
- **Design.** Dark, dense, tabular figures on every compared number, motion only
  on state transitions, and a single restrained accent so semantic colour is
  reserved for state rather than decoration.

---

## 13. What we would change with more time

- **Alembic migrations.** `create_all` was chosen so a clean clone runs in one
  command; the models are written to be Alembic-compatible.
- **Store replay failures.** They are currently returned but not persisted, so
  the ROI page cannot trend failure modes over time.
- **Per-tenant trust.** Trust is per automation. In reality an automation may be
  trustworthy for one team's data and not another's.
- **Drift from live schemas.** Reading schemas from source APIs rather than
  inferring them from the event log would make the confidence scores
  considerably better founded.
- **Weight learning.** The automatability weights (0.35/0.20/0.20/0.25) are
  reasoned, not fitted. With labelled outcomes they should be learned.
