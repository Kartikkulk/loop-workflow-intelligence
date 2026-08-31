const el = (id) => document.getElementById(id);

async function render() {
  const { settings, stats } = await chrome.runtime.sendMessage({ type: "loop:status" });
  el("sent").textContent = stats.sent ?? 0;
  el("queued").textContent = stats.queued ?? 0;
  el("transfers").textContent = stats.transfers ?? 0;
  el("err").textContent = stats.lastError || "";

  const state = el("state");
  if (!settings.token) {
    state.textContent = "Not connected";
    state.className = "state bad";
    el("toggle").textContent = "Open settings";
  } else if (settings.paused) {
    state.textContent = "Paused — nothing is being recorded";
    state.className = "state off";
    el("toggle").textContent = "Resume";
  } else {
    state.textContent = "Observing — metadata only";
    state.className = "state on";
    el("toggle").textContent = "Pause";
  }
}

el("toggle").addEventListener("click", async () => {
  const { settings } = await chrome.runtime.sendMessage({ type: "loop:status" });
  if (!settings.token) {
    await chrome.runtime.openOptionsPage();
    return;
  }
  await chrome.runtime.sendMessage({
    type: "loop:settings",
    patch: { paused: !settings.paused },
  });
  await render();
});

el("flush").addEventListener("click", async () => {
  await chrome.runtime.sendMessage({ type: "loop:flush" });
  await render();
});

el("options").addEventListener("click", () => chrome.runtime.openOptionsPage());

render();
