"use client";

import { TRUST_LADDER, type TrustLevel, type TrustState } from "@/lib/api/types";
import { percent } from "@/lib/format";

const DESCRIPTIONS: Record<TrustLevel, string> = {
  OBSERVE: "Just watching how people do it.",
  SUGGEST: "Says it could do this. Nothing runs.",
  SHADOW: "Practises alongside the person. Nothing is sent.",
  ASSIST: "Does the work, but asks before anything it cannot undo.",
  AUTONOMOUS: "Runs on its own, inside the limits you set.",
};

/** What each rung is allowed to touch. Shown so the stakes of a rung are legible. */
const EFFECT: Record<TrustLevel, string> = {
  OBSERVE: "changes nothing",
  SUGGEST: "changes nothing",
  SHADOW: "changes nothing",
  ASSIST: "acts, with your yes",
  AUTONOMOUS: "acts on its own",
};

/**
 * The five rungs.
 *
 * Three states have to be distinguishable at a glance, not two: rungs already
 * earned, the rung currently held, and rungs not yet reached. That matters
 * because an automation can arrive at its current rung by having been
 * *demoted*, and a design that only shows "progress" would hide that entirely.
 */
export function TrustLadder({ state, live }: { state: TrustState; live?: boolean }) {
  const currentIndex = TRUST_LADDER.indexOf(state.level);
  const demoted = state.critical_mismatches > 0;

  return (
    <div className="px-4 py-5">
      {/* ── the rungs ─────────────────────────────────────────────────── */}
      <ol className="flex items-stretch gap-2">
        {TRUST_LADDER.map((level, index) => {
          const earned = index < currentIndex;
          const current = index === currentIndex;
          const reached = earned || current;
          const hasEffect = level === "ASSIST" || level === "AUTONOMOUS";

          return (
            <li key={level} className="group relative min-w-0 flex-1">
              {/* track segment */}
              <div className="relative h-1 overflow-hidden rounded-full bg-ink-700">
                <div
                  className="bar-fill absolute inset-y-0 left-0 rounded-full"
                  style={{
                    width: reached ? "100%" : "0%",
                    backgroundColor: current
                      ? demoted
                        ? "#f59e0b"
                        : "#3b82f6"
                      : "rgba(37,99,235,0.45)",
                  }}
                />
              </div>

              {/* node — the current rung gets a ring so it reads as "you are here" */}
              <div className="mt-2 flex items-center gap-1.5">
                <span
                  className={`relative flex h-2 w-2 shrink-0 items-center justify-center rounded-full transition-colors duration-300 ${
                    current
                      ? demoted
                        ? "bg-warn-400"
                        : "bg-accent-400"
                      : earned
                        ? "bg-accent-600/70"
                        : "bg-ink-600"
                  }`}
                >
                  {current && (
                    <span
                      className={`absolute inset-[-5px] animate-pulse-ring rounded-full border ${
                        demoted ? "border-warn-400/60" : "border-accent-400/60"
                      }`}
                      aria-hidden
                    />
                  )}
                </span>
                <span
                  className={`truncate text-2xs font-semibold tracking-wide transition-colors ${
                    current
                      ? demoted
                        ? "text-warn-300"
                        : "text-accent-300"
                      : earned
                        ? "text-mist-400"
                        : "text-mist-600"
                  }`}
                >
                  {level}
                </span>
              </div>

              <p
                className={`mt-1.5 text-2xs leading-snug ${
                  current ? "text-mist-300" : "text-mist-600"
                }`}
              >
                {DESCRIPTIONS[level]}
              </p>

              <p
                className={`mt-1.5 text-[9px] font-medium uppercase tracking-[0.1em] ${
                  hasEffect
                    ? reached
                      ? "text-warn-400"
                      : "text-mist-600"
                    : "text-mist-600"
                }`}
              >
                {EFFECT[level]}
              </p>
            </li>
          );
        })}
      </ol>

      {/* ── confidence ────────────────────────────────────────────────── */}
      <div className="mt-6 space-y-2.5">
        <div className="flex items-baseline justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="eyebrow">Confidence</span>
            {live && (
              <span className="flex items-center gap-1 text-2xs font-medium text-good-400">
                <span className="relative flex h-1.5 w-1.5">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-good-400 opacity-60" />
                  <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-good-400" />
                </span>
                live
              </span>
            )}
          </div>
          <span
            className={`metric text-lg ${
              demoted
                ? "text-warn-400"
                : state.confidence >= state.threshold
                  ? "text-good-400"
                  : "text-mist-100"
            }`}
          >
            {percent(state.confidence, 1)}
          </span>
        </div>

        {/* The bar carries the threshold marker, so it reads as progress
            towards a specific bar rather than as a vague score. */}
        <div className="relative pt-1">
          <div className="h-2 w-full overflow-hidden rounded-full bg-ink-800">
            <div
              className="bar-fill h-full rounded-full"
              style={{
                width: `${Math.max(0, Math.min(1, state.confidence)) * 100}%`,
                backgroundColor: demoted
                  ? "#f59e0b"
                  : state.confidence >= state.threshold
                    ? "#10b981"
                    : "#3b82f6",
              }}
            />
          </div>

          <div
            className="pointer-events-none absolute top-0 flex flex-col items-center"
            style={{ left: `${state.threshold * 100}%`, transform: "translateX(-50%)" }}
          >
            <span className="h-4 w-px bg-mist-400" />
          </div>
          <span
            className="pointer-events-none absolute -bottom-4 whitespace-nowrap text-[9px] font-medium text-mist-500"
            style={{ left: `${state.threshold * 100}%`, transform: "translateX(-50%)" }}
          >
            needs {percent(state.threshold)} to move up
          </span>
        </div>

        {/* ── run window: each shadow run as its own cell ─────────────── */}
        <div className="flex items-center gap-3 pt-5">
          <span className="eyebrow shrink-0">Recent runs</span>
          <div className="flex flex-1 items-center gap-1">
            {Array.from({ length: state.runs_required }).map((_, index) => {
              const filled = index < state.runs_in_window;
              return (
                <span
                  key={index}
                  className={`h-1.5 flex-1 rounded-full transition-colors duration-300 ${
                    filled ? (demoted ? "bg-warn-500" : "bg-accent-500") : "bg-ink-700"
                  }`}
                  title={filled ? `run ${index + 1} recorded` : "not run yet"}
                />
              );
            })}
          </div>
          <span className="tnum shrink-0 text-2xs font-medium text-mist-300">
            {state.runs_in_window}/{state.runs_required}
          </span>
        </div>

        <div className="tnum flex flex-wrap items-center gap-x-4 gap-y-1 pt-1 text-2xs text-mist-500">
          <span>
            average so far{" "}
            <span className="font-medium text-mist-300">{percent(state.average_score, 1)}</span>
          </span>
          {state.critical_mismatches > 0 && (
            <span className="font-medium text-bad-400">
              got {state.critical_mismatches} important thing
              {state.critical_mismatches === 1 ? "" : "s"} wrong recently
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

export function TrustBadge({ level }: { level: TrustLevel }) {
  const tone: Record<TrustLevel, string> = {
    OBSERVE: "border-ink-600 bg-ink-800 text-mist-400",
    SUGGEST: "border-ink-600 bg-ink-800 text-mist-300",
    SHADOW: "border-accent-500/40 bg-accent-500/10 text-accent-300",
    ASSIST: "border-warn-500/40 bg-warn-500/10 text-warn-400",
    AUTONOMOUS: "border-good-500/40 bg-good-500/10 text-good-400",
  };
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-2xs font-semibold tracking-wide ${tone[level]}`}
    >
      {/* A dot per rung reached: the badge alone does not say how far up it is. */}
      <span className="flex gap-0.5" aria-hidden>
        {TRUST_LADDER.map((candidate, index) => (
          <span
            key={candidate}
            className={`h-1 w-1 rounded-full ${
              index <= TRUST_LADDER.indexOf(level) ? "bg-current" : "bg-current opacity-25"
            }`}
          />
        ))}
      </span>
      {level}
    </span>
  );
}
