const el = (id) => document.getElementById(id);

function say(message, ok = true) {
  const status = el("status");
  status.textContent = message;
  status.className = ok ? "ok" : "bad";
}

async function load() {
  const { settings, stats } = await chrome.runtime.sendMessage({ type: "loop:status" });
  el("apiBase").value = settings.apiBase || "";
  el("token").value = settings.token || "";
  el("denylist").value = (settings.denylist || []).join("\n");
  el("pause").textContent = settings.paused ? "Resume capture" : "Pause capture";
  if (settings.token) {
    const parts = [`${stats.sent} events sent`, `${stats.queued} queued`];
    if (stats.transfers) parts.push(`${stats.transfers} transfers detected`);
    say(parts.join(" · "), true);
  } else {
    say("Not connected — paste a source token to begin.", false);
  }
  if (stats.lastError) say(stats.lastError, false);
}

el("save").addEventListener("click", async () => {
  const token = el("token").value.trim();
  const apiBase = el("apiBase").value.trim().replace(/\/$/, "") || "http://localhost:8000";
  const denylist = el("denylist").value.split("\n").map((s) => s.trim()).filter(Boolean);

  if (!token.startsWith("loop_src_")) {
    say("That does not look like a source token — it should start with loop_src_.", false);
    return;
  }

  // Verify against the server before claiming success: a typo'd token that
  // silently queues forever is worse than an error message now.
  try {
    const response = await fetch(`${apiBase}/api/v1/collect/config`, {
      headers: { authorization: `Bearer ${token}` },
    });
    if (!response.ok) {
      say(`Server rejected that token (HTTP ${response.status}).`, false);
      return;
    }
    const config = await response.json();
    await chrome.runtime.sendMessage({
      type: "loop:settings",
      patch: { token, apiBase, denylist, paused: config.status !== "connected" },
    });
    say(`Connected as source ${config.source_id} (${config.capture_scope}).`, true);
  } catch (error) {
    say(`Cannot reach ${apiBase} — ${error.message}`, false);
  }
});

el("pause").addEventListener("click", async () => {
  const { settings } = await chrome.runtime.sendMessage({ type: "loop:status" });
  await chrome.runtime.sendMessage({
    type: "loop:settings",
    patch: { paused: !settings.paused },
  });
  await load();
});

el("flush").addEventListener("click", async () => {
  const stats = await chrome.runtime.sendMessage({ type: "loop:flush" });
  say(stats.lastError || `${stats.sent} events sent · ${stats.queued} queued`, !stats.lastError);
});

load();
