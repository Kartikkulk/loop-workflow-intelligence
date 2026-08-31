/**
 * Content script: observes interactions on the page and forwards them.
 *
 * Two rules govern everything here:
 *
 *   1. Never read a field's value. Field *names* are collected; what was typed
 *      into them is not. Detection works on the shape of activity, so this
 *      costs nothing in capability and is the difference between a tool people
 *      accept and a tool they uninstall.
 *
 *   2. Clipboard text is hashed in this file and the hash leaves; the text does
 *      not. Matching a hash seen in app A against the same hash in app B proves
 *      data moved between systems without ever transmitting the data.
 */

(() => {
  // Never observe the LOOP console itself: it would record the act of reading
  // the report as work, which is both noise and faintly absurd.
  const SELF_HOSTS = ["localhost:3000", "127.0.0.1:3000"];
  if (SELF_HOSTS.some((h) => location.host === h)) return;

  const MIN_INTERVAL_MS = 400; // coalesce bursts of identical interactions
  let lastKey = "";
  let lastAt = 0;
  let pageEnteredAt = Date.now();

  // A page title routinely carries the subject of an email or a customer's
  // name, so it is withheld unless the console has explicitly scoped this
  // source to capture values. Read here rather than filtered downstream: the
  // guarantee should hold in the file that does the reading.
  let capturePageTitles = false;
  try {
    chrome.storage?.local?.get?.(["loop_config"], (stored) => {
      capturePageTitles = Boolean(stored?.loop_config?.capturePageTitles);
    });
    chrome.storage?.onChanged?.addListener?.((changes) => {
      if (changes.loop_config) {
        capturePageTitles = Boolean(changes.loop_config.newValue?.capturePageTitles);
      }
    });
  } catch {
    // No storage access: stay with the safe default.
  }

  /**
   * Strip values out of a URL, keeping only its structure.
   *
   * This is not a nicety. A GET form puts every field straight into the query
   * string, so `?vendor=Kaveri+Logistics&secret=hunter2` is a routine URL — and
   * transmitting it would leak exactly the field values this collector promises
   * never to read. Parameter *names* are kept because they describe the schema;
   * their values are dropped.
   */
  function sanitiseUrl(href) {
    let parsed;
    try {
      parsed = new URL(href);
    } catch {
      return "";
    }

    // Keep path structure, but drop any segment that looks like free text or an
    // address rather than an identifier.
    const segments = parsed.pathname
      .split("/")
      .map((segment) => {
        const decoded = (() => {
          try {
            return decodeURIComponent(segment);
          } catch {
            return segment;
          }
        })();
        if (decoded.length > 40 || /[\s@]/.test(decoded)) return "_";
        return segment;
      })
      .join("/");

    // Query and fragment: keep the keys, discard the values.
    const keys = [...parsed.searchParams.keys()];
    const query = keys.length ? `?${keys.map((k) => `${k}=`).join("&")}` : "";

    let fragment = "";
    if (parsed.hash) {
      const raw = parsed.hash.slice(1);
      if (raw.includes("=")) {
        const fragmentKeys = [...new URLSearchParams(raw).keys()];
        fragment = fragmentKeys.length ? `#${fragmentKeys.map((k) => `${k}=`).join("&")}` : "";
      } else {
        // A value-free fragment is a route — Gmail's `#inbox/FMfcgz` — and it
        // is how the object being worked on is identified in many web apps.
        fragment = raw.length > 120 ? "" : `#${raw}`;
      }
    }

    return `${parsed.origin}${segments}${query}${fragment}`;
  }

  function send(signal) {
    const key = `${signal.interaction}|${signal.label || ""}|${signal.field_name || ""}`;
    const now = Date.now();
    if (key === lastKey && now - lastAt < MIN_INTERVAL_MS) return;
    lastKey = key;
    lastAt = now;

    try {
      chrome.runtime.sendMessage({
        type: "loop:signal",
        signal: {
          url: sanitiseUrl(location.href),
          title: capturePageTitles ? document.title || "" : "",
          occurred_at: new Date().toISOString(),
          ...signal,
        },
      });
    } catch {
      // The extension was reloaded or the context is gone. Losing a signal is
      // strictly better than throwing inside someone's application.
    }
  }

  /** SHA-256, first 16 hex chars. Must match the server's digest exactly. */
  async function digest(text) {
    const data = new TextEncoder().encode(text);
    if (crypto?.subtle?.digest) {
      const buf = await crypto.subtle.digest("SHA-256", data);
      return [...new Uint8Array(buf)]
        .map((b) => b.toString(16).padStart(2, "0"))
        .join("")
        .slice(0, 16);
    }
    // Insecure context (plain http). Fall back to a non-cryptographic hash: it
    // is only ever used to correlate a copy with a paste, never as a secret.
    let h1 = 0x811c9dc5;
    let h2 = 0x01000193;
    for (const byte of data) {
      h1 = (h1 ^ byte) * 0x01000193 >>> 0;
      h2 = (h2 + byte) * 0x85ebca6b >>> 0;
    }
    return (h1.toString(16).padStart(8, "0") + h2.toString(16).padStart(8, "0")).slice(0, 16);
  }

  /** A human-readable label for a control, without reading user input. */
  function labelFor(element) {
    if (!element) return "";
    const candidates = [
      element.getAttribute?.("aria-label"),
      element.getAttribute?.("title"),
      element.dataset?.testid,
      // innerText of a button is its caption, not user data.
      element.tagName === "BUTTON" || element.getAttribute?.("role") === "button"
        ? element.innerText
        : "",
      element.tagName === "A" ? element.innerText : "",
      element.value && element.type === "submit" ? element.value : "",
    ];
    const label = candidates.find((c) => c && String(c).trim());
    return label ? String(label).trim().replace(/\s+/g, " ").slice(0, 80) : "";
  }

  /** The *name* of a field. Never its contents. */
  function fieldNameFor(element) {
    if (!element) return "";
    const name =
      element.getAttribute?.("name") ||
      element.getAttribute?.("aria-label") ||
      element.getAttribute?.("placeholder") ||
      element.id ||
      "";
    return String(name).trim().replace(/\s+/g, "_").slice(0, 64);
  }

  function roleFor(element) {
    if (!element) return "";
    const explicit = element.getAttribute?.("role");
    if (explicit) return String(explicit).slice(0, 64);
    if (element.type === "search") return "searchbox";
    return (element.tagName || "").toLowerCase().slice(0, 64);
  }

  function isEditable(element) {
    if (!element) return false;
    const tag = (element.tagName || "").toUpperCase();
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || element.isContentEditable;
  }

  // ── page view and dwell time ─────────────────────────────────────────────

  function reportPageView() {
    pageEnteredAt = Date.now();
    send({ interaction: "pageview", duration_ms: 0 });
  }

  function reportDwell() {
    const dwell = Date.now() - pageEnteredAt;
    // Under two seconds is a bounce, not work.
    if (dwell < 2000) return;
    send({ interaction: "pageview", duration_ms: Math.min(dwell, 3_600_000) });
  }

  reportPageView();
  addEventListener("beforeunload", reportDwell, { capture: true });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") reportDwell();
    else pageEnteredAt = Date.now();
  });

  // Single-page applications change route without a navigation, so patch the
  // history API. Without this, everything after the first load is invisible in
  // exactly the apps most enterprise work happens in.
  for (const method of ["pushState", "replaceState"]) {
    const original = history[method];
    history[method] = function (...args) {
      const result = original.apply(this, args);
      reportDwell();
      setTimeout(() => send({ interaction: "route_change" }), 60);
      pageEnteredAt = Date.now();
      return result;
    };
  }
  addEventListener("popstate", () => send({ interaction: "route_change" }));

  // ── interactions ─────────────────────────────────────────────────────────

  document.addEventListener(
    "click",
    (event) => {
      const target = event.target?.closest?.(
        'button, a, [role="button"], [role="menuitem"], [role="tab"], input[type="submit"]'
      );
      if (!target) return;
      send({ interaction: "click", label: labelFor(target), role: roleFor(target) });
    },
    { capture: true, passive: true }
  );

  document.addEventListener(
    "submit",
    (event) => {
      const form = event.target;
      send({
        interaction: "submit",
        label: labelFor(form?.querySelector?.('[type="submit"], button')) || "submit",
        role: "form",
      });
    },
    { capture: true, passive: true }
  );

  // Field edits are reported on blur, once, with the field's name only.
  document.addEventListener(
    "focusout",
    (event) => {
      const target = event.target;
      if (!isEditable(target)) return;
      const name = fieldNameFor(target);
      if (!name) return;
      const isSearch =
        target.type === "search" ||
        roleFor(target) === "searchbox" ||
        /search|query|filter|^q$/i.test(name);
      send({
        interaction: isSearch ? "search" : "field_edit",
        field_name: name,
        role: roleFor(target),
      });
    },
    { capture: true, passive: true }
  );

  document.addEventListener(
    "copy",
    async () => {
      const text = String(getSelection?.() ?? "").trim();
      if (text.length < 3) return;
      send({ interaction: "copy", payload_digest: await digest(text) });
    },
    { capture: true, passive: true }
  );

  document.addEventListener(
    "paste",
    async (event) => {
      const text = String(event.clipboardData?.getData?.("text") ?? "").trim();
      if (text.length < 3) return;
      send({
        interaction: "paste",
        payload_digest: await digest(text),
        field_name: fieldNameFor(event.target),
      });
    },
    { capture: true, passive: true }
  );
})();
