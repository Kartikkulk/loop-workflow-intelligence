/**
 * Service worker: queues signals locally and flushes them in batches.
 *
 * Batching is not an optimisation, it is a requirement. A chatty collector that
 * posts on every click is both a performance problem on the page and a
 * reliability problem when the network drops mid-workflow — exactly when the
 * most interesting sequence is happening.
 *
 * The queue lives in chrome.storage.local because an MV3 service worker is
 * evicted aggressively; anything held in memory is lost within seconds of
 * going idle.
 */

const QUEUE_KEY = "loop_queue";
const CONFIG_KEY = "loop_config";
const STATS_KEY = "loop_stats";
const FLUSH_ALARM = "loop_flush";

const DEFAULTS = {
  apiBase: "http://localhost:8000",
  token: "",
  paused: false,
  denylist: [],
  batchIntervalSeconds: 20,
  maxBatchSize: 200,
  // Hard ceiling on the local queue. Dropping the oldest signals is better than
  // filling someone's disk because the API has been unreachable for a week.
  maxQueueSize: 5000,
  // Titles are withheld unless the console has scoped this source to values.
  capturePageTitles: false,
};

/**
 * Serialises storage mutations.
 *
 * chrome.storage.local has no atomic read-modify-write, and signals arrive in
 * bursts — a run of clicks, a paste followed immediately by a field edit. Two
 * overlapping enqueues each read the same queue and write back their own copy,
 * so one of them is silently lost. That is event loss under exactly the
 * conditions this collector exists to observe, so every mutation goes through
 * here.
 */
let writeChain = Promise.resolve();

function serialise(task) {
  const result = writeChain.then(task, task);
  // Keep the chain alive even if a task rejects.
  writeChain = result.then(
    () => undefined,
    () => undefined,
  );
  return result;
}

async function getSettings() {
  const stored = await chrome.storage.local.get([CONFIG_KEY]);
  return { ...DEFAULTS, ...(stored[CONFIG_KEY] || {}) };
}

function setSettings(patch) {
  return serialise(async () => {
    const current = await getSettings();
    const next = { ...current, ...patch };
    await chrome.storage.local.set({ [CONFIG_KEY]: next });
    return next;
  });
}

async function getStats() {
  const stored = await chrome.storage.local.get([STATS_KEY]);
  return {
    queued: 0,
    sent: 0,
    rejected: 0,
    transfers: 0,
    lastFlushAt: null,
    lastError: "",
    ...(stored[STATS_KEY] || {}),
  };
}

function setStats(patch) {
  return serialise(async () => {
    const next = { ...(await getStats()), ...patch };
    await chrome.storage.local.set({ [STATS_KEY]: next });
    return next;
  });
}

function isDenied(url, denylist) {
  const lowered = String(url || "").toLowerCase();
  return (denylist || []).some((entry) => entry.trim() && lowered.includes(entry.trim().toLowerCase()));
}

function enqueue(signal) {
  return serialise(async () => {
    const settings = await getSettings();
    if (settings.paused || !settings.token) return;
    // Enforced locally as well as on the server. A denylisted domain should
    // never reach the network at all, not merely be discarded on arrival.
    if (isDenied(signal.url, settings.denylist)) return;

    // A page title can carry the subject of an email or a customer's name, so
    // it is dropped unless the source is explicitly scoped to capture values.
    // Doing it here means it never crosses the network.
    const cleaned = { ...signal };
    if (!settings.capturePageTitles) delete cleaned.title;

    const stored = await chrome.storage.local.get([QUEUE_KEY]);
    const queue = stored[QUEUE_KEY] || [];
    queue.push(cleaned);
    // Drop the oldest rather than filling someone's disk if the API has been
    // unreachable for a week.
    const trimmed =
      queue.length > settings.maxQueueSize ? queue.slice(-settings.maxQueueSize) : queue;

    const stats = { ...(await getStats()), queued: trimmed.length };
    await chrome.storage.local.set({ [QUEUE_KEY]: trimmed, [STATS_KEY]: stats });
  });
}

async function flush() {
  const settings = await getSettings();
  if (!settings.token) return;

  const batch = await serialise(async () => {
    const stored = await chrome.storage.local.get([QUEUE_KEY]);
    return (stored[QUEUE_KEY] || []).slice(0, settings.maxBatchSize);
  });
  if (batch.length === 0) return;

  // The fetch happens outside the lock: holding it across a network round trip
  // would stall every enqueue for the duration, losing activity during exactly
  // the pause a slow network creates.

  let response;
  try {
    response = await fetch(`${settings.apiBase}/api/v1/collect/events`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${settings.token}`,
      },
      body: JSON.stringify({ signals: batch }),
    });
  } catch (error) {
    // Keep the batch queued: an unreachable API must not lose activity.
    await setStats({ lastError: `network: ${error.message}` });
    return;
  }

  if (response.status === 423) {
    // Paused server-side. Honour it locally and discard everything queued:
    // replaying activity captured before a pause would defeat the pause.
    await setSettings({ paused: true });
    await serialise(async () => {
      await chrome.storage.local.set({ [QUEUE_KEY]: [] });
    });
    await setStats({ lastError: "paused from the Kriyā AI console", queued: 0 });
    return;
  }

  if (response.status === 401 || response.status === 403) {
    // The token is dead. Stop, rather than retrying forever against a revoked
    // source, and say so where the person will see it.
    await setSettings({ paused: true, token: "" });
    await serialise(async () => {
      await chrome.storage.local.set({ [QUEUE_KEY]: [] });
    });
    await setStats({
      lastError: "token rejected — this source was revoked. Re-onboard in the console.",
      queued: 0,
    });
    return;
  }

  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    await setStats({ lastError: `HTTP ${response.status} ${detail.slice(0, 120)}` });
    return;
  }

  const result = await response.json().catch(() => ({}));

  await serialise(async () => {
    // Remove exactly the number of items that were sent, from the front.
    // Replacing the queue with a stale remainder would discard anything
    // enqueued while the request was in flight.
    const stored = await chrome.storage.local.get([QUEUE_KEY]);
    const remaining = (stored[QUEUE_KEY] || []).slice(batch.length);
    const stats = await getStats();
    await chrome.storage.local.set({
      [QUEUE_KEY]: remaining,
      [STATS_KEY]: {
        ...stats,
        queued: remaining.length,
        sent: stats.sent + (result.accepted ?? batch.length),
        rejected: stats.rejected + (result.rejected ?? 0),
        transfers: stats.transfers + (result.transfers_linked ?? 0),
        lastFlushAt: new Date().toISOString(),
        lastError: "",
      },
    });
  });
}

/** Pull the denylist and pause state from the server, so the console governs. */
async function syncConfig() {
  const settings = await getSettings();
  if (!settings.token) return;
  try {
    const response = await fetch(`${settings.apiBase}/api/v1/collect/config`, {
      headers: { authorization: `Bearer ${settings.token}` },
    });
    if (!response.ok) return;
    const config = await response.json();
    await setSettings({
      paused: config.status === "paused" || config.status === "revoked",
      denylist: config.denylist || [],
      capturePageTitles: Boolean(config.capture_page_titles),
      batchIntervalSeconds: config.batch_interval_seconds || DEFAULTS.batchIntervalSeconds,
      maxBatchSize: config.max_batch_size || DEFAULTS.maxBatchSize,
    });
  } catch {
    // Offline. Keep the settings we have.
  }
}

chrome.runtime.onMessage.addListener((message, _sender, respond) => {
  if (message?.type === "loop:signal") {
    void enqueue(message.signal);
    return false;
  }
  if (message?.type === "loop:flush") {
    void (async () => {
      await flush();
      respond(await getStats());
    })();
    return true;
  }
  if (message?.type === "loop:status") {
    void (async () => {
      respond({ settings: await getSettings(), stats: await getStats() });
    })();
    return true;
  }
  if (message?.type === "loop:settings") {
    void (async () => {
      const next = await setSettings(message.patch || {});
      await syncConfig();
      respond(next);
    })();
    return true;
  }
  return false;
});

chrome.alarms.create(FLUSH_ALARM, { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== FLUSH_ALARM) return;
  void (async () => {
    await syncConfig();
    await flush();
  })();
});

chrome.runtime.onInstalled.addListener(() => {
  void chrome.runtime.openOptionsPage();
});
