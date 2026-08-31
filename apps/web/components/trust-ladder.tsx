"use client";

import { TRUST_LADDER, type TrustLevel, type TrustState } from "@/lib/api/types";
import { percent } from "@/lib/format";
import { Meter } from "./ui";

const DESCRIPTIONS: Record<TrustLevel, string> = {
  OBSERVE: "Watching only. No predictions recorded.",
  SUGGEST: "Recommends the automation. Nothing runs.",
  SHADOW: "Predicts what it would do while the human works. Nothing is sent.",
  ASSIST: "Runs with a human confirming each irreversible step.",
  AUTONOMOUS: "Runs unattended within its guards.",
};

/**
 * The five rungs. The current level is highlighted; levels already earned are
 * marked distinctly from levels not yet reached, so the direction of travel is
 * legible at a glance — which matters because this automation may have arrived
 * at its current rung by being demoted.
 */
export function TrustLadder({ state, live }: { state: TrustState; live?: boolean }) {
  const currentIndex = TRUST_LADDER.indexOf(state.level);

  return (
    <div className="px-4 py-5">
      <ol className="flex items-stretch gap-1.5">
        {TRUST_LADDER.map((level, index) => {
          const earned = index < currentIndex;
          const current = index === currentIndex;
          return (
            <li key={level} className="min-w-0 flex-1">
              <div
                className={`h-0.5 rounded-full transition-colors duration-500 ${
                  current ? "bg-accent-500" : earned ? "bg-accent-600/50" : "bg-ink-700"
                }`}
              />
              <div className="mt-2.5">
                <p
                  className={`text-2xs font-semibold tracking-wide transition-colors ${
                    current
                      ? "text-accent-300"
                      : earned
                        ? "text-mist-400"
                        : "text-mist-600"
                  }`}
                >
                  {level}
                </p>
                <p
                  className={`mt-1 text-2xs leading-snug ${
                    current ? "text-mist-300" : "text-mist-600"
                  }`}
                >
                  {DESCRIPTIONS[level]}
                </p>
              </div>
            </li>
          );
        })}
      </ol>

      <div className="mt-6 space-y-2.5">
        <div className="flex items-baseline justify-between">
          <div className="flex items-center gap-2">
            <span className="eyebrow">Confidence</span>
            {live && (
              <span className="flex items-center gap-1 text-2xs text-good-400">
                <span className="h-1 w-1 animate-pulse rounded-full bg-good-400" />
                live
              </span>
            )}
          </div>
          <span className="tnum text-sm font-semibold text-mist-100">
            {percent(state.confidence, 1)}
          </span>
        </div>

        <div className="relative">
          <Meter
            value={state.confidence}
            tone={
              state.critical_mismatches > 0
                ? "bad"
                : state.confidence >= state.threshold
                  ? "good"
                  : "accent"
            }
            height="h-2"
          />
          {/* The promotion threshold, marked so the bar is readable as progress
              towards a specific bar rather than as a vague score. */}
          <div
            className="absolute -top-1 h-4 w-px bg-mist-400"
            style={{ left: `${state.threshold * 100}%` }}
            title={`promotion threshold ${percent(state.threshold)}`}
          />
        </div>

        <div className="tnum flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-mist-500">
          <span>
            rolling average{" "}
            <span className="font-medium text-mist-300">{percent(state.average_score, 1)}</span>
          </span>
          <span>
            runs{" "}
            <span className="font-medium text-mist-300">
              {state.runs_in_window}/{state.runs_required}
            </span>
          </span>
          <span>
            threshold{" "}
            <span className="font-medium text-mist-300">{percent(state.threshold)}</span>
          </span>
          {state.critical_mismatches > 0 && (
            <span className="font-medium text-bad-400">
              {state.critical_mismatches} critical mismatch
              {state.critical_mismatches === 1 ? "" : "es"}
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
      className={`inline-flex items-center rounded-md border px-2 py-0.5 text-2xs font-semibold tracking-wide ${tone[level]}`}
    >
      {level}
    </span>
  );
}
