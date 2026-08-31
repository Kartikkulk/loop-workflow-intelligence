/**
 * Tests background.js by running the shipped file in a VM with a stubbed
 * chrome API and a stubbed fetch.
 *
 * The service worker is where the reliability behaviour lives — batching,
 * queue durability, honouring a server-side pause, reacting to a revoked
 * token — and none of that is exercised by testing the content script.
 */
import vm from "node:vm";
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";

const HERE = path.dirname(new URL(import.meta.url).pathname);
const SOURCE = fs.readFileSync(path.join(HERE, "..", "shared", "background.js"), "utf8");

/** Boot background.js in isolation, returning handles to poke at it. */
function boot({ fetchImpl } = {}) {
  const store = {};
  const listeners = { message: [], alarm: [] };
  const calls = [];

  const chrome = {
    storage: {
      local: {
        async get(keys) {
          const wanted = Array.isArray(keys) ? keys : [keys];
          return Object.fromEntries(
            wanted.filter((k) => k in store).map((k) => [k, store[k]]),
          );
        },
        async set(patch) {
          Object.assign(store, patch);
        },
      },
    },
    runtime: {
      onMessage: { addListener: (fn) => listeners.message.push(fn) },
      onInstalled: { addListener: () => {} },
      openOptionsPage: () => {},
    },
    alarms: {
      create: () => {},
      onAlarm: { addListener: (fn) => listeners.alarm.push(fn) },
    },
  };

  const fetchStub =
    fetchImpl ??
    (async (url, init) => {
      calls.push({ url, body: JSON.parse(init.body) });
      return {
        ok: true,
        status: 200,
        json: async () => ({ accepted: JSON.parse(init.body).signals.length, rejected: 0, transfers_linked: 1 }),
        text: async () => "",
      };
    });

  const context = vm.createContext({ chrome, fetch: fetchStub, console, URL, TextEncoder });
  vm.runInContext(SOURCE, context);

  const send = (message) =>
    new Promise((resolve) => {
      let settled = false;
      for (const listener of listeners.message) {
        const isAsync = listener(message, {}, (value) => {
          settled = true;
          resolve(value);
        });
        if (!isAsync && !settled) resolve(undefined);
      }
      if (!listeners.message.length) resolve(undefined);
    });

  return { store, send, calls, fireAlarm: () => listeners.alarm[0]?.({ name: "loop_flush" }) };
}

const signal = (over = {}) => ({
  interaction: "pageview",
  url: "https://mail.google.com/mail/u/0",
  title: "Invoice from Kaveri",
  occurred_at: new Date().toISOString(),
  ...over,
});

const results = [];
async function test(name, fn) {
  try {
    await fn();
    results.push({ name, ok: true });
  } catch (error) {
    results.push({ name, ok: false, detail: error.message });
  }
}

const settle = () => new Promise((r) => setTimeout(r, 30));

await test("drops signals when no token is configured", async () => {
  const app = boot();
  await app.send({ type: "loop:signal", signal: signal() });
  await settle();
  const { stats } = await app.send({ type: "loop:status" });
  assert.equal(stats.queued, 0);
});

await test("queues signals once connected", async () => {
  const app = boot();
  await app.send({ type: "loop:settings", patch: { token: "loop_src_x", apiBase: "http://api" } });
  await app.send({ type: "loop:signal", signal: signal() });
  await app.send({ type: "loop:signal", signal: signal({ interaction: "click" }) });
  await settle();
  const { stats } = await app.send({ type: "loop:status" });
  assert.equal(stats.queued, 2);
});

await test("queues nothing while paused", async () => {
  const app = boot();
  await app.send({ type: "loop:settings", patch: { token: "loop_src_x", paused: true } });
  await app.send({ type: "loop:signal", signal: signal() });
  await settle();
  const { stats } = await app.send({ type: "loop:status" });
  assert.equal(stats.queued, 0);
});

await test("never queues a denylisted url", async () => {
  const app = boot();
  await app.send({
    type: "loop:settings",
    patch: { token: "loop_src_x", denylist: ["bank.example.com", "payroll"] },
  });
  await app.send({ type: "loop:signal", signal: signal({ url: "https://bank.example.com/a" }) });
  await app.send({ type: "loop:signal", signal: signal({ url: "https://payroll.internal/x" }) });
  await app.send({ type: "loop:signal", signal: signal() });
  await settle();
  const { stats } = await app.send({ type: "loop:status" });
  assert.equal(stats.queued, 1, "only the non-denylisted signal should queue");
});

await test("strips page titles unless scoped to values", async () => {
  const app = boot();
  await app.send({ type: "loop:settings", patch: { token: "loop_src_x", capturePageTitles: false } });
  await app.send({ type: "loop:signal", signal: signal() });
  await settle();
  const queued = app.store.loop_queue;
  assert.equal(queued.length, 1);
  assert.equal("title" in queued[0], false, "title must not be queued");
});

await test("keeps page titles when scoped to values", async () => {
  const app = boot();
  await app.send({ type: "loop:settings", patch: { token: "loop_src_x", capturePageTitles: true } });
  await app.send({ type: "loop:signal", signal: signal() });
  await settle();
  assert.equal(app.store.loop_queue[0].title, "Invoice from Kaveri");
});

await test("flushes a batch with a bearer token and clears the queue", async () => {
  const app = boot();
  await app.send({ type: "loop:settings", patch: { token: "loop_src_abc", apiBase: "http://api" } });
  for (let i = 0; i < 3; i++) await app.send({ type: "loop:signal", signal: signal({ label: `b${i}` }) });
  await settle();
  const stats = await app.send({ type: "loop:flush" });
  assert.equal(app.calls.length, 1);
  assert.equal(app.calls[0].url, "http://api/api/v1/collect/events");
  assert.equal(app.calls[0].body.signals.length, 3);
  assert.equal(stats.queued, 0);
  assert.equal(stats.sent, 3);
  assert.equal(stats.transfers, 1);
});

await test("keeps the queue when the network fails", async () => {
  const app = boot({
    fetchImpl: async () => {
      throw new Error("offline");
    },
  });
  await app.send({ type: "loop:settings", patch: { token: "loop_src_x", apiBase: "http://api" } });
  await app.send({ type: "loop:signal", signal: signal() });
  await settle();
  const stats = await app.send({ type: "loop:flush" });
  assert.equal(stats.queued, 1, "an unreachable API must not lose activity");
  assert.match(stats.lastError, /network/);
});

await test("honours a server-side pause and drops the batch", async () => {
  const app = boot({
    fetchImpl: async () => ({ ok: false, status: 423, text: async () => "", json: async () => ({}) }),
  });
  await app.send({ type: "loop:settings", patch: { token: "loop_src_x", apiBase: "http://api" } });
  await app.send({ type: "loop:signal", signal: signal() });
  await settle();
  await app.send({ type: "loop:flush" });
  const { settings, stats } = await app.send({ type: "loop:status" });
  assert.equal(settings.paused, true, "must pause locally");
  assert.equal(stats.queued, 0, "must not replay activity captured before the pause");
});

await test("stops permanently when the token is revoked", async () => {
  const app = boot({
    fetchImpl: async () => ({ ok: false, status: 401, text: async () => "", json: async () => ({}) }),
  });
  await app.send({ type: "loop:settings", patch: { token: "loop_src_dead", apiBase: "http://api" } });
  await app.send({ type: "loop:signal", signal: signal() });
  await settle();
  await app.send({ type: "loop:flush" });
  const { settings, stats } = await app.send({ type: "loop:status" });
  assert.equal(settings.token, "", "a revoked token must be discarded");
  assert.equal(settings.paused, true);
  assert.match(stats.lastError, /revoked/);
});

await test("caps the local queue rather than growing without bound", async () => {
  const app = boot();
  await app.send({ type: "loop:settings", patch: { token: "loop_src_x", maxQueueSize: 5 } });
  for (let i = 0; i < 12; i++) await app.send({ type: "loop:signal", signal: signal({ label: `s${i}` }) });
  await settle();
  const queued = app.store.loop_queue;
  assert.equal(queued.length, 5);
  // The newest signals are the ones kept.
  assert.equal(queued.at(-1).control ?? queued.at(-1).label, "s11");
});

await test("respects maxBatchSize and leaves the remainder queued", async () => {
  const app = boot();
  await app.send({
    type: "loop:settings",
    patch: { token: "loop_src_x", apiBase: "http://api", maxBatchSize: 2 },
  });
  for (let i = 0; i < 5; i++) await app.send({ type: "loop:signal", signal: signal({ label: `s${i}` }) });
  await settle();
  const stats = await app.send({ type: "loop:flush" });
  assert.equal(app.calls[0].body.signals.length, 2);
  assert.equal(stats.queued, 3);
});

let failed = 0;
for (const r of results) {
  if (!r.ok) failed++;
  console.log(`  ${r.ok ? "ok  " : "FAIL"} ${r.name}${r.detail ? ` — ${r.detail}` : ""}`);
}
console.log(`\n  ${results.length - failed}/${results.length} background checks passed`);
process.exit(failed ? 1 : 0);
