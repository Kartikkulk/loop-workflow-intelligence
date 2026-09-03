# Collectors

How Kriyā AI observes real activity.

```
collectors/
  shared/       the observing logic — ONE copy, owned by Kartik
  chrome/       Anushree — Chrome-specific files (today: the manifest)
  edge/         Gouri — Edge-specific files
  tests/        33 checks over the shared logic
  build.mjs     assembles dist/chrome and dist/edge
```

## Build and load

```bash
make collectors        # or: node collectors/build.mjs chrome
```

Then `chrome://extensions` or `edge://extensions` → **Developer mode** →
**Load unpacked** → `collectors/dist/<browser>`.

Get a token from the console: **Observation → Browser extension → Connect**.
Paste it into the extension's options page.

## Why shared/ and not two copies

Chrome and Edge are both Chromium and both run Manifest V3, so the content
script and service worker are byte-identical. Two copies would mean every fix
had to be made twice, and eventually one of them wouldn't be. The build copies
`shared/` into each browser's output, then copies that browser's own folder on
top — so **a browser can override any shared file simply by having its own
copy of it.** Start with the manifest; add more only when you find a real
difference.

## What it collects

| Collected | Not collected |
|---|---|
| Which application (from the hostname) | Page content |
| What kind of action | Field **values** |
| What kind of object | Message bodies |
| The **names** of fields filled | Passwords |
| Duration and context switches | Page titles, unless explicitly scoped |
| A **hash** of copied text | The copied text itself |

### The copy-paste bridge

The most valuable thing a browser collector sees, and the reason this tier
matters:

```
copy in gmail   → sha256("48,250.00")[:16] = a1b2c3d4e5f6a7b8
paste in sheets → sha256("48,250.00")[:16] = a1b2c3d4e5f6a7b8
                  ↓ same hash, different app, within 10 minutes
        transferred_from: gmail · transferred_to: sheets
```

Matching a hash proves the same value moved between two systems **without ever
receiving the value**.

### Applications onboard themselves

The app vocabulary is a database table, not an enum, so an internal tool nobody
configured registers on first sight:

```
https://app.northwind-erp.co.in/vendors/8812  →  app "northwind-erp"
https://finance-tool.internal/ledger          →  app "finance-tool"
```

## Privacy, as implemented

Not a policy — what the code does.

- **Metadata only by default.** Field *names*, never values.
- **URLs stripped of values on both sides.** A GET form puts every field into
  the query string, so `?vendor=Kaveri&secret=hunter2` is a routine URL. The
  collector rewrites it to `?vendor=&secret=`. The server re-applies the same
  stripping, because an old collector cannot be trusted to have done it.
- **Consent is a row.** A source without it gets 403.
- **Pause is central.** The collector polls `/api/v1/collect/config` every 30
  seconds, so pausing from the console stops capture without touching the
  extension.
- **Revoking deletes** every event that source reported, by default.
- **Denylists enforced twice** — locally and server-side.

## Testing

```bash
npm run test:collector
```

- `tests/background.test.mjs` — 12 checks. Runs the shipped service worker in a
  VM: batching, durability across a network failure, honouring a server-side
  pause, discarding a revoked token, queue capping, title stripping.
- `tests/content.test.mjs` — 21 checks. Injects the shipped content script into
  real Chrome and asserts on what it emits, including that no field value, page
  title or query-string value ever appears in a transmitted signal.

### Two bugs these caught

**Lost signals under bursts.** `enqueue` did an unserialised read-modify-write
on `chrome.storage.local`, which has no atomic update, so two overlapping
enqueues each read the same queue and one was silently lost. Every mutation now
goes through a promise chain.

**Field values leaking through URLs.** A test submitted a GET form and asserted
no value appeared in any signal. It failed — the values were in
`location.href`. Hence the sanitiser.

## Not verified

The extension has **never been confirmed working as a loaded extension**.
Chrome 137 removed `--load-extension`, so it could not be automated. Both
shipped files are tested directly and the collector API is tested end to end,
but the browser's own plumbing is unverified. That is the first task for
whoever owns a browser.
