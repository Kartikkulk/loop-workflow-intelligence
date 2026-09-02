/**
 * Tests content.js by injecting it into real pages in real Chrome, with a
 * stubbed chrome API.
 *
 * Injection rather than a loaded extension: Chrome 137+ removed
 * `--load-extension`, so an unpacked MV3 extension cannot be side-loaded from
 * the command line at all. This still exercises the actual shipped file — its
 * selectors, label extraction, SPA history patching, clipboard hashing and URL
 * sanitisation — against a real DOM in a real browser.
 */
import { chromium } from "playwright-core";
import fs from "node:fs";
import crypto from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CONTENT = fs.readFileSync(
  path.join(HERE, "..", "shared", "content.js"),
  "utf8",
);

const APP = `<!doctype html><title>Invoice INV-8899 from Kaveri Logistics</title>
<body><h1>Invoice INV-8899</h1>
<p>Amount due: <span id="amt">92,400.00</span></p>
<form id="f">
  <input name="vendor" placeholder="vendor" />
  <input name="amount" placeholder="amount" />
  <input type="search" name="q" placeholder="search rows" />
  <input name="secret" type="password" />
  <input name="coalesce_field" />
  <input name="waffle-rich-text-editor" />
  <input name="A1" />
  <button type="submit">Save</button>
</form>
<button id="reply" aria-label="Send reply">Reply</button>
<button id="del">Delete row</button>
<a href="#x" id="lnk">Open details</a>
</body>`;

const browser = await chromium.launch({ channel: "chrome", headless: true });
const context = await browser.newContext();
await context.route("https://mail.google.com/**", (r) =>
  r.fulfill({ contentType: "text/html", body: APP }),
);
await context.route("https://docs.google.com/**", (r) =>
  r.fulfill({ contentType: "text/html", body: APP }),
);
const page = await context.newPage();

// Signals are collected in Node, not on the page. Submitting the form navigates,
// which would wipe a page-side array — and the submit is one of the things being
// tested, so it cannot simply be avoided.
const signals = [];
await page.exposeFunction("__loopEmit", (signal) => {
  signals.push(signal);
});

// Stub the chrome API before content.js runs.
await page.addInitScript(() => {
  window.chrome = {
    runtime: {
      sendMessage: (message) => {
        if (message?.type === "loop:signal") window.__loopEmit(message.signal);
      },
    },
    // Default scope: metadata only, so titles must be withheld.
    storage: {
      local: { get: (_keys, cb) => cb({ loop_config: { capturePageTitles: false } }) },
      onChanged: { addListener: () => {} },
    },
  };
});
await page.goto("https://mail.google.com/mail/u/0/#inbox/INV8899");
// Wrapped in an outer expression: passing the file's own IIFE string straight
// to evaluate() makes Playwright treat it as a function to pass rather than an
// expression to run, and the script silently never executes.
async function inject() {
  const result = await page.evaluate(
    `(() => { try { ${CONTENT.replace(/^\s*\/\*\*[\s\S]*?\*\/\s*/, "")} ; return "ran"; } catch (e) { return "threw: " + e.message; } })()`,
  );
  if (result !== "ran") throw new Error(`content.js failed to inject: ${result}`);
}
await inject();
await page.waitForTimeout(200);

// ── act ──────────────────────────────────────────────────────────────────
await page.evaluate(() => {
  const range = document.createRange();
  range.selectNodeContents(document.getElementById("amt"));
  getSelection().removeAllRanges();
  getSelection().addRange(range);
  document.dispatchEvent(new Event("copy", { bubbles: true }));
});
await page.waitForTimeout(150);

await page.evaluate(() => {
  const input = document.querySelector('input[name="coalesce_field"]');
  input.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
  input.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
  input.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
});

// Paste is a distinct action and must flush, not swallow, the pending edit.
await page.evaluate(() => {
  const input = document.querySelector('input[name="amount"]');
  input.focus();
  const dt = new DataTransfer();
  dt.setData("text", "92,400.00");
  input.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, clipboardData: dt }));
});
// A later edit beyond the inactivity boundary must remain a separate event.
await page.waitForTimeout(3100);
await page.evaluate(() => {
  const input = document.querySelector('input[name="coalesce_field"]');
  input.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
});
await page.waitForTimeout(3100);
await page.fill('input[name="vendor"]', "Kaveri Logistics");
await page.fill('input[name="q"]', "overdue");
await page.fill('input[name="secret"]', "hunter2");
await page.click('input[name="amount"]');
await page.click("#reply");
await page.click("#del");
await page.click("#lnk");
await page.click('button[type="submit"]');
await page.waitForTimeout(500);

// The submit navigated, so Chrome would run the content script again on the new
// document. Re-inject to mirror that, then exercise the SPA history patch.
await inject();
const pageviewsBeforeSpa = signals.filter((s) => s.interaction === "pageview").length;
await page.evaluate(() => history.pushState({}, "", "/mail/u/0/#inbox/NEXT"));
await page.waitForTimeout(400);
const pageviewsAfterSpa = signals.filter((s) => s.interaction === "pageview").length;

// Sheets presents the same logical cell edit through both an internal editor
// and a cell coordinate. They should coalesce as one editing-surface event.
await page.goto("https://docs.google.com/spreadsheets/d/1AbC_def-GhIJkLmNopQRsTuvWXyZ/edit");
await inject();
const sheetsEditStart = signals.length;
await page.evaluate(() => {
  document
    .querySelector('input[name="waffle-rich-text-editor"]')
    .dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
  document
    .querySelector('input[name="A1"]')
    .dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
});
await page.click("#reply"); // flush the pending edit without waiting three seconds
await page.waitForTimeout(200);
const sheetsSignals = signals.slice(sheetsEditStart);

await page.waitForTimeout(400);
await browser.close();

// ── assert ───────────────────────────────────────────────────────────────
const expectedDigest = crypto
  .createHash("sha256")
  .update("92,400.00")
  .digest("hex")
  .slice(0, 16);

const kinds = signals.map((s) => s.interaction);
const checks = [];
const check = (name, ok, detail = "") => checks.push({ name, ok, detail });

check("emitted a pageview", kinds.includes("pageview"));
check("emitted a copy", kinds.includes("copy"));
check("emitted a paste", kinds.includes("paste"));
check("emitted field edits", kinds.includes("field_edit"));
check("emitted a search (typed vs edit)", kinds.includes("search"));
check("emitted clicks", kinds.includes("click"));
check("emitted a submit", kinds.includes("submit"));
check("emitted an SPA route_change", kinds.includes("route_change"));
check(
  "SPA route change does not emit a duplicate pageview",
  pageviewsAfterSpa === pageviewsBeforeSpa,
  `pageviews before ${pageviewsBeforeSpa}, after ${pageviewsAfterSpa}`,
);

const coalescedEdits = signals.filter(
  (s) => s.interaction === "field_edit" && s.field_name === "coalesce_field",
);
check(
  "nearby edit events collapse into one logical edit",
  coalescedEdits.length === 2,
  `expected one burst plus one post-pause edit, got ${coalescedEdits.length}`,
);
check(
  "edits separated by the inactivity boundary remain separate",
  coalescedEdits.length === 2 && coalescedEdits[0].occurred_at !== coalescedEdits[1].occurred_at,
);
check(
  "Sheets editor and cell blur collapse into one logical edit",
  sheetsSignals.filter((s) => s.interaction === "field_edit").length === 1,
);

const copy = signals.find((s) => s.interaction === "copy");
check(
  "copy digest matches the server algorithm",
  copy?.payload_digest === expectedDigest,
  `got ${copy?.payload_digest} want ${expectedDigest}`,
);

const paste = signals.find((s) => s.interaction === "paste");
check("paste carries the same digest", paste?.payload_digest === expectedDigest);
check("paste records the target field name", paste?.field_name === "amount");
check("paste is not swallowed by edit coalescing", Boolean(paste));

const reply = signals.find((s) => s.label === "Send reply");
check("reads aria-label for a control", Boolean(reply));
const del = signals.find((s) => s.label === "Delete row");
check("reads button caption text", Boolean(del));

// The privacy contract: no field value may appear anywhere in the payload.
const serialised = JSON.stringify(signals);
for (const secret of ["hunter2", "Kaveri Logistics", "92,400.00", "overdue"]) {
  check(`never transmits the value ${JSON.stringify(secret)}`, !serialised.includes(secret));
}
check(
  "password field name captured but not its value",
  signals.some((s) => s.field_name === "secret") && !serialised.includes("hunter2"),
);
check("every signal carries a url and timestamp",
  signals.every((s) => s.url && s.occurred_at));
check("withholds page titles in metadata-only scope",
  signals.every((s) => !s.title));
check("strips values from a GET form's query string",
  signals.every((s) => !/=[^&#]+/.test(new URL(s.url).search)));

// Show exactly where a leak came from.
for (const secret of ["hunter2", "Kaveri Logistics", "overdue"]) {
  const leaked = signals.filter((sig) => JSON.stringify(sig).includes(secret));
  if (leaked.length) console.log(`  LEAK ${JSON.stringify(secret)} in:`, JSON.stringify(leaked));
}

let failed = 0;
for (const c of checks) {
  if (!c.ok) failed++;
  console.log(`  ${c.ok ? "ok  " : "FAIL"} ${c.name}${c.detail ? ` — ${c.detail}` : ""}`);
}
console.log(`\n  ${signals.length} signals emitted · ${checks.length - failed}/${checks.length} checks passed`);
console.log("  kinds:", [...new Set(kinds)].join(", "));
process.exit(failed ? 1 : 0);
