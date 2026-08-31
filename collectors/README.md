# Collectors — how LOOP gets to observe

Detection is only as good as what LOOP can see. A platform that can only be
*fed* activity logs is a report generator; one that can *observe* is a product.

This directory holds the collectors. There is one canonical event schema, so
every collector's only job is to produce `Event`s — detection never learns where
an event came from.

---

## The tiers, honestly

| Tier | Coverage | Effort | Intrusiveness | Status |
|---|---|---|---|---|
| Describe a task in prose | ~10% | seconds | none | ✅ built |
| Upload an activity log | ~25% | minutes | none | ✅ built |
| **Browser extension** | **~70%** | **~2 min/person** | **low** | **✅ built** |
| Connect an app account (OAuth) | ~45% | hours + admin | medium | ⬜ interfaces declared |
| Desktop agent | ~95% | days + IT rollout | high | ⬜ not built |
| Screen recording | ~100% | minutes, doesn't scale | very high | ⚠️ needs an API key |

Coverage figures are estimates of a typical knowledge worker's app activity, and
they **do not add up** — the tiers overlap heavily. The console reports the best
connected tier, not the sum, because summing them would claim more than is true.

The browser extension is the highest-leverage tier by a wide margin: most
enterprise work now happens in a browser, and it is the only tier that sees
**data being copied from one system and pasted into another** — which is
literally the problem statement.

---

## Browser extension

### Install

```bash
# 1. In the LOOP console: Observation → Browser extension → Connect.
#    Copy the token it shows once.
# 2. chrome://extensions → enable Developer mode → Load unpacked
#    → select collectors/browser-extension
# 3. The options page opens. Paste the token, set the API address, save.
```

Chrome removed `--load-extension` in M137, so there is no command-line install
path any more. Loading it unpacked from `chrome://extensions` is the supported
route for an unsigned extension.

### What it collects

| Collected | Not collected |
|---|---|
| Application (derived from hostname) | Page content |
| Kind of action (read, create, send, search…) | Field **values** |
| Kind of object acted on | Message bodies |
| The **names** of fields you filled | Passwords |
| Duration and context switches | Page titles (unless explicitly scoped) |
| A **hash** of copied text | The copied text itself |

### The copy-paste bridge

The single most valuable thing a browser collector can see, and the reason this
tier matters:

```
copy in gmail   → sha256("48,250.00")[:16] = "a1b2c3d4e5f6a7b8"
paste in sheets → sha256("48,250.00")[:16] = "a1b2c3d4e5f6a7b8"
                  ↓ same hash, different app, within 10 minutes
        transferred_from: gmail  ·  transferred_to: sheets
```

Matching on a hash means LOOP can prove that *the same value moved from
application A to application B* without ever receiving the value. That is a
genuinely privacy-preserving way to detect "moving information between systems",
rather than a privacy-adjacent one.

### Onboarding an application nobody configured

The app vocabulary is a **database table**, not a Python enum. The first time
someone opens an unanticipated internal tool, its hostname is resolved to a
brand name and registered automatically:

```
https://app.northwind-erp.co.in/vendors/8812  →  app "northwind-erp"
https://finance-tool.internal/ledger          →  app "finance-tool"
```

Multi-label public suffixes are handled, so `northwind.com.au` does not become
an app called `com`. No code change, no migration, no configuration file: an
employee onboards a tool by using it.

---

## Privacy, as implemented

Not a policy document — this is what the code does.

**Consent is a row, not an assumption.** A source with no `consent_granted_at`
cannot ingest; the endpoint returns 403.

**Metadata-only is the default.** `capture_scope` defaults to `metadata_only`,
which records that a field named `amount` was filled and never what was typed
into it. Capturing values is a deliberate opt-in per source.

**URLs are stripped of values, on both sides.** This one is easy to get wrong
and expensive to get wrong: a GET form puts every field straight into the query
string, so `?vendor=Kaveri+Logistics&secret=hunter2` is a completely routine
URL. The collector rewrites it to `?vendor=&secret=`, keeping parameter *names*
(useful schema signal) and dropping values. Path segments that look like free
text or an email address are replaced with `_`. The server re-applies the same
sanitisation, because an old or third-party collector cannot be trusted to have
done it.

**Pause is real and it is governed centrally.** The collector polls
`/api/v1/collect/config` every 30 seconds, so pausing from the console stops
capture without the person touching the extension. A paused source's ingest
returns `423`, and the collector then discards what it had queued — replaying
activity captured before a pause would defeat the pause.

**Revoking deletes.** `DELETE /api/v1/sources/{id}` invalidates the token *and*
deletes every event that source reported, by default rather than behind a flag.
Consent that cannot be fully withdrawn is not consent.

**Denylists are enforced twice.** Locally, so an excluded domain never reaches
the network at all; and server-side, so a stale extension cannot keep reporting
one.

**The organisational threshold is also a privacy feature.** A cluster is only
promoted to an organisational opportunity when more than three distinct people
perform it. Surfacing work at the level of a group rather than an individual is
what separates a process tool from a surveillance tool.

---

## Testing

```bash
npm run test:collector
```

- **`tests/background.test.mjs`** — 12 checks. Runs the shipped `background.js`
  in a VM with a stubbed `chrome` API: batching, queue durability across a
  network failure, honouring a server-side pause, discarding a revoked token,
  queue capping, and title stripping.
- **`tests/content.test.mjs`** — 21 checks. Injects the shipped `content.js`
  into real pages in real Chrome and asserts on what it emits: every interaction
  type including SPA route changes, a clipboard digest that matches the server's
  algorithm byte for byte, and the privacy contract (no field value, no page
  title, no query-string value ever appears in a transmitted signal).

Backend coverage is in `apps/api/tests/test_sources.py` — 41 tests over app
mapping, URL sanitisation, consent enforcement, denylist enforcement, transfer
linking, revocation-deletes-events, and detection running over collected
activity.

### Two bugs these tests caught

**Lost signals under bursts.** `enqueue` did an unserialised read-modify-write
on `chrome.storage.local`, which has no atomic update. Two overlapping enqueues
each read the same queue and wrote back their own copy, so one was silently
lost — event loss under exactly the bursty conditions the collector exists to
observe. Every storage mutation now goes through a promise chain, and `flush`
removes sent items *by count* so anything enqueued mid-request survives.

**Field values leaking through URLs.** The test submitted a GET form and then
asserted that no field value appeared in any signal. It failed: the values were
in `location.href`. Hence the sanitiser described above.

---

## Not built, and what it would take

**API connectors.** The interfaces and their exact API surfaces are declared in
`apps/api/app/connectors/real_connectors.py`, and the System screen lists the
credentials each needs. The real work is per-provider OAuth plus, for the
tenant-wide audit APIs, an administrator's consent:

- Microsoft 365 — Graph `/me/messages/delta`, `/me/events/delta` for one
  mailbox; the **Office 365 Management Activity API** for genuine cross-app
  action data across Exchange, SharePoint and Teams. The latter needs tenant
  admin consent, which is the actual blocker rather than the code.
- Google Workspace — Admin SDK Reports API `activities.list`, which covers
  Gmail, Drive and Calendar tenant-wide.
- Slack — audit logs API (Enterprise Grid only) or the Events API otherwise.
- Salesforce — `EventLogFile`; Jira — webhooks plus the audit log; SAP — change
  documents.

**Desktop agent.** The collector API it would post to is finished and
documented, so the agent is independent work: active-window polling via the
macOS Accessibility API or Windows UI Automation, plus clipboard events, posting
the same `RawSignal` shape to `/api/v1/collect/events`. It needs a signed
installer and a real consent conversation, and it is the only way to see Excel,
Outlook desktop, SAP GUI or anything inside Citrix.

---

## Collector API

Any collector — including one you write — talks to two endpoints.

```http
GET /api/v1/collect/config
Authorization: Bearer loop_src_…

→ { "status": "connected", "capture_scope": "metadata_only",
    "denylist": ["bank"], "batch_interval_seconds": 20,
    "capture_field_values": false, "capture_page_titles": false }
```

```http
POST /api/v1/collect/events
Authorization: Bearer loop_src_…

{ "session_id": "ses_abc",
  "signals": [
    { "interaction": "pageview",
      "url": "https://mail.google.com/mail/u/0/#inbox/X",
      "occurred_at": "2026-01-01T10:00:00Z",
      "duration_ms": 42000 },
    { "interaction": "copy", "url": "…", "payload_digest": "a1b2c3d4e5f6a7b8" },
    { "interaction": "paste", "url": "…", "field_name": "amount",
      "payload_digest": "a1b2c3d4e5f6a7b8" }
  ] }

→ { "accepted": 3, "rejected": 0, "transfers_linked": 1,
    "apps_discovered": ["northwind-erp"], "detection_suggested": false }
```

Signals are deliberately close to raw: `interaction`, `url`, `label`, `role`,
`field_name`. All interpretation — which application, which verb, which object
type — happens server-side in `app/services/web_activity.py`. That split is
intentional: interpretation rules improve constantly, and pushing a new
heuristic to a server is a deploy, while pushing one to an installed extension
is a release cycle across every laptop.

**Status codes a collector must handle:** `423` paused (stop and discard),
`401`/`403` revoked (stop permanently and discard the token), any other failure
(keep the queue and retry).
