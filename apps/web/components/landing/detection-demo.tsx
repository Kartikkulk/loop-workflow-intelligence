"use client";

import { useEffect, useState } from "react";

/**
 * The product, animated, in the space above the fold.
 *
 * A landing page for something this abstract has one hard job: make "it finds
 * repetitive work by itself" concrete before anyone scrolls. Describing that in
 * a paragraph asks the reader to imagine it. Showing five recorded runs collapse
 * into one detected pattern, and that pattern become an automation held behind a
 * guard, does not.
 *
 * Every value on screen is from the demo fixture the test suite runs against, so
 * this is a re-enactment of a real detection rather than an invented mock-up.
 */

const RUNS = [
  { customer: "ABC", issue: "Login failure", ticket: "1001" },
  { customer: "XYZ", issue: "Payment failure", ticket: "1002" },
  { customer: "PQR", issue: "API failure", ticket: "1003" },
  { customer: "Acme", issue: "Account locked", ticket: "1004" },
  { customer: "DemoCorp", issue: "Sync failure", ticket: "1005" },
];

const STEPS = [
  { app: "browser", action: "open", target: "Support Portal" },
  { app: "browser", action: "search", target: "Ticket" },
  { app: "browser", action: "read", target: "Customer" },
  { app: "browser", action: "read", target: "Issue" },
  { app: "browser", action: "read", target: "Priority" },
  { app: "jira", action: "open", target: "Create Issue" },
  { app: "jira", action: "fill", target: "Summary" },
  { app: "jira", action: "set", target: "Priority" },
  { app: "jira", action: "create", target: "Issue" },
];

const PHASES = [
  { key: "observe", label: "Observe", note: "Recording what was actually done" },
  { key: "discover", label: "Discover", note: "Five runs, one pattern" },
  { key: "build", label: "Build", note: "Choosing the runtime" },
  { key: "approve", label: "Approve", note: "Nothing runs until a person says so" },
] as const;

const PHASE_MS = [5200, 4200, 4200, 4600];

export function DetectionDemo() {
  const [phase, setPhase] = useState(0);
  const [tick, setTick] = useState(0);

  // Advance through the phases, then start over. `tick` changes the React key
  // on the animated subtree so every loop replays the entry animations rather
  // than showing a finished state.
  useEffect(() => {
    const timer = setTimeout(() => {
      setPhase((current) => {
        const next = (current + 1) % PHASES.length;
        if (next === 0) setTick((t) => t + 1);
        return next;
      });
    }, PHASE_MS[phase]);
    return () => clearTimeout(timer);
  }, [phase]);

  return (
    <div className="relative w-full">
      <div className="panel-raised relative overflow-hidden rounded-xl border border-ink-600/80 shadow-lift">
        {/* window chrome */}
        <div className="flex items-center gap-2 border-b border-ink-700 bg-ink-900/80 px-4 py-2.5">
          <span className="h-2 w-2 rounded-full bg-ink-500" />
          <span className="h-2 w-2 rounded-full bg-ink-500" />
          <span className="h-2 w-2 rounded-full bg-ink-500" />
          <span className="mono ml-2 text-2xs text-mist-600">loop — live detection</span>
          <span className="ml-auto flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 animate-pulse-ring rounded-full bg-good-500" />
            <span className="mono text-2xs text-mist-600">watching</span>
          </span>
        </div>

        <div key={`${phase}-${tick}`} className="relative h-[19rem] px-5 py-4 sm:h-[17.5rem]">
          {phase === 0 && <ObservePhase />}
          {phase === 1 && <DiscoverPhase />}
          {phase === 2 && <BuildPhase />}
          {phase === 3 && <ApprovePhase />}
        </div>

        {/* phase stepper */}
        <div className="grid grid-cols-4 gap-px border-t border-ink-700 bg-ink-700">
          {PHASES.map((item, index) => (
            <div
              key={item.key}
              className={`relative overflow-hidden bg-ink-900 px-3 py-2.5 transition-colors duration-500 ${
                index === phase ? "bg-ink-850" : ""
              }`}
            >
              <p
                className={`text-2xs font-medium transition-colors duration-500 ${
                  index === phase ? "text-accent-400" : "text-mist-600"
                }`}
              >
                {item.label}
              </p>
              <p className="mt-0.5 hidden truncate text-2xs text-mist-600 sm:block">
                {item.note}
              </p>
              {index === phase && (
                <span
                  key={`bar-${phase}-${tick}`}
                  className="absolute inset-x-0 bottom-0 h-px origin-left bg-accent-500"
                  style={{
                    animation: `grow-x ${PHASE_MS[phase]}ms linear both`,
                  }}
                />
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── phase 1: raw activity arriving ──────────────────────────────────── */

function ObservePhase() {
  const rows = RUNS.flatMap((run, runIndex) =>
    STEPS.slice(0, 3).map((step, stepIndex) => ({
      key: `${runIndex}-${stepIndex}`,
      time: `09:${String(15 + runIndex * 2 + stepIndex).padStart(2, "0")}`,
      app: step.app,
      action: step.action,
      target: step.target,
      value: stepIndex === 2 ? run.customer : stepIndex === 1 ? `Ticket ${run.ticket}` : "",
      delay: (runIndex * 3 + stepIndex) * 190,
    })),
  );

  return (
    <div className="relative h-full overflow-hidden">
      <p className="eyebrow mb-2.5 text-mist-600">Raw activity · 50 events</p>
      <div className="space-y-[3px]">
        {rows.map((row) => (
          <div
            key={row.key}
            className="mono flex items-center gap-2.5 text-2xs text-mist-500 opacity-0"
            style={{ animation: `fade-up 380ms ease-out ${row.delay}ms both` }}
          >
            <span className="text-mist-700">{row.time}</span>
            <span
              className={`w-14 shrink-0 ${
                row.app === "jira" ? "text-cyan-400" : "text-accent-400"
              }`}
            >
              {row.app}
            </span>
            <span className="w-12 shrink-0 text-mist-400">{row.action}</span>
            <span className="truncate text-mist-500">{row.target}</span>
            {row.value && <span className="truncate text-mist-300">{row.value}</span>}
          </div>
        ))}
      </div>
      {/* a scanning beam, so "watching" reads as continuous rather than static */}
      <span
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-16 animate-scan bg-gradient-to-b from-transparent via-accent-500/[0.07] to-transparent"
      />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-14 bg-gradient-to-t from-ink-850 to-transparent" />
    </div>
  );
}

/* ── phase 2: five runs collapse into one pattern ────────────────────── */

function DiscoverPhase() {
  return (
    <div className="h-full">
      <p className="eyebrow mb-3 text-mist-600">Repetitive work found</p>

      <div className="mb-3.5 flex items-end gap-1.5">
        {RUNS.map((run, index) => (
          <div
            key={run.customer}
            className="flex-1 opacity-0"
            style={{ animation: `fade-up 400ms ease-out ${index * 110}ms both` }}
          >
            <div className="h-8 rounded-sm border border-accent-500/30 bg-accent-500/10" />
            <p className="mono mt-1 truncate text-center text-2xs text-mist-600">
              {run.customer}
            </p>
          </div>
        ))}
        <div
          className="ml-1.5 shrink-0 opacity-0"
          style={{ animation: `scale-in 500ms ease-out 700ms both` }}
        >
          <p className="text-lg font-semibold leading-none text-mist-100">5</p>
          <p className="text-2xs text-mist-600">runs</p>
        </div>
      </div>

      <div
        className="rounded-lg border border-accent-500/30 bg-accent-500/[0.06] p-3.5 opacity-0"
        style={{ animation: `scale-in 520ms ease-out 900ms both` }}
      >
        <p className="text-xs font-semibold tracking-tight text-mist-100">
          High-priority support ticket escalation
        </p>
        <div className="mt-2.5 grid grid-cols-3 gap-3">
          {[
            { label: "occurrences", value: "5" },
            { label: "similarity", value: "91%" },
            { label: "hrs / year", value: "126" },
          ].map((metric, index) => (
            <div
              key={metric.label}
              className="opacity-0"
              style={{ animation: `fade-up 400ms ease-out ${1150 + index * 130}ms both` }}
            >
              <p className="text-sm font-semibold leading-none text-accent-300">
                {metric.value}
              </p>
              <p className="mt-1 text-2xs text-mist-600">{metric.label}</p>
            </div>
          ))}
        </div>
        <div
          className="mono mt-3 flex flex-wrap gap-1.5 text-2xs opacity-0"
          style={{ animation: `fade-in 500ms ease-out 1600ms both` }}
        >
          <span className="text-mist-600">variables detected</span>
          {["{{customer}}", "{{issue}}", "{{ticket}}"].map((token) => (
            <span
              key={token}
              className="rounded border border-ink-600 bg-ink-900 px-1.5 py-0.5 text-mist-300"
            >
              {token}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── phase 3: the runtime is chosen, with reasons ────────────────────── */

function BuildPhase() {
  const options = [
    { name: "n8n", note: "APIs and SaaS", chosen: false },
    { name: "Browser", note: "no API available", chosen: false },
    { name: "Python", note: "files and documents", chosen: false },
    { name: "Hybrid", note: "browser reads, API writes", chosen: true },
  ];

  return (
    <div className="h-full">
      <p className="eyebrow mb-3 text-mist-600">Choosing how to run it</p>
      <div className="space-y-1.5">
        {options.map((option, index) => (
          <div
            key={option.name}
            className={`flex items-center gap-3 rounded-md border px-3 py-2 opacity-0 transition-colors ${
              option.chosen
                ? "border-accent-500/50 bg-accent-500/[0.08]"
                : "border-ink-700 bg-ink-900"
            }`}
            style={{ animation: `slide-in-left 380ms ease-out ${index * 130}ms both` }}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                option.chosen ? "bg-accent-400" : "bg-ink-500"
              }`}
            />
            <span
              className={`text-2xs font-medium ${
                option.chosen ? "text-mist-100" : "text-mist-500"
              }`}
            >
              {option.name}
            </span>
            <span className="text-2xs text-mist-600">{option.note}</span>
            {option.chosen && (
              <span
                className="ml-auto rounded bg-accent-500/20 px-1.5 py-0.5 text-2xs font-medium text-accent-300 opacity-0"
                style={{ animation: `fade-in 400ms ease-out 750ms both` }}
              >
                selected
              </span>
            )}
          </div>
        ))}
      </div>

      <div
        className="mt-3 border-l-2 border-accent-500/40 pl-3 opacity-0"
        style={{ animation: `fade-up 460ms ease-out 950ms both` }}
      >
        {[
          "The support portal has no usable API — a browser is the only way in.",
          "Jira has one, and an API call survives a redesign that breaks a click.",
        ].map((reason) => (
          <p key={reason} className="text-2xs leading-relaxed text-mist-500">
            {reason}
          </p>
        ))}
        <p className="mono mt-1.5 text-2xs text-mist-600">confidence 0.87</p>
      </div>
    </div>
  );
}

/* ── phase 4: validated, dry-run, and waiting for a human ────────────── */

function ApprovePhase() {
  const checks = [
    "Connectors all observed in the activity log",
    "Guard preserved: priority != High",
    "Dry run: 10/10 steps, 0 side effects",
  ];

  return (
    <div className="flex h-full flex-col">
      <p className="eyebrow mb-3 text-mist-600">Ready for review</p>
      <div className="space-y-1.5">
        {checks.map((check, index) => (
          <div
            key={check}
            className="flex items-start gap-2 opacity-0"
            style={{ animation: `slide-in-left 360ms ease-out ${index * 220}ms both` }}
          >
            <span className="mt-[3px] text-2xs text-good-400">✓</span>
            <span className="text-2xs leading-relaxed text-mist-400">{check}</span>
          </div>
        ))}
      </div>

      <div
        className="mt-3.5 rounded-lg border border-warn-500/30 bg-warn-500/[0.06] p-3 opacity-0"
        style={{ animation: `fade-up 460ms ease-out 800ms both` }}
      >
        <p className="text-2xs font-medium text-warn-300">If approved, it will</p>
        <p className="mt-1 text-2xs leading-relaxed text-mist-400">
          read the ticket, then create a Jira escalation — and stop and ask a person whenever{" "}
          <span className="mono text-mist-300">priority != High</span>.
        </p>
      </div>

      <div
        className="mt-auto flex items-center gap-2 pt-3 opacity-0"
        style={{ animation: `fade-up 420ms ease-out 1150ms both` }}
      >
        <span className="relative overflow-hidden rounded-md bg-accent-600 px-3 py-1.5 text-2xs font-medium text-white">
          Approve &amp; enable
          <span
            aria-hidden
            className="absolute inset-y-0 -left-full w-1/2 animate-sheen bg-gradient-to-r from-transparent via-white/25 to-transparent"
          />
        </span>
        <span className="rounded-md border border-ink-600 px-3 py-1.5 text-2xs text-mist-400">
          Cancel
        </span>
        <span className="ml-auto text-2xs text-mist-600">nothing has run yet</span>
      </div>
    </div>
  );
}
