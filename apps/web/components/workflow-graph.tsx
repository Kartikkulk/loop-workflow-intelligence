"use client";

import { duration, stepLabel } from "@/lib/format";
import type { StepNode } from "@/lib/api/types";

const APP_TONE: Record<string, string> = {
  gmail: "border-red-500/30 bg-red-500/10 text-red-300",
  outlook: "border-blue-500/30 bg-blue-500/10 text-blue-300",
  sheets: "border-good-500/30 bg-good-500/10 text-good-400",
  erp: "border-violet-500/30 bg-violet-500/10 text-violet-300",
  drive: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  slack: "border-fuchsia-500/30 bg-fuchsia-500/10 text-fuchsia-300",
  pdf: "border-orange-500/30 bg-orange-500/10 text-orange-300",
  browser: "border-ink-500 bg-ink-800 text-mist-300",
};

function tone(app: string): string {
  return APP_TONE[app] ?? "border-ink-500 bg-ink-800 text-mist-300";
}

/**
 * The observed step sequence. Steps that varied between instances are marked,
 * because a branch point is exactly where an automation needs a rule — showing
 * only the happy path would hide the hard part.
 */
export function WorkflowGraph({ steps }: { steps: StepNode[] }) {
  if (!steps.length) {
    return <p className="px-4 py-6 text-2xs text-mist-500">No steps recorded.</p>;
  }

  return (
    <div className="overflow-x-auto px-4 py-5">
      <ol className="flex min-w-max items-stretch gap-0">
        {steps.map((step, index) => (
          <li key={step.index} className="flex items-stretch">
            <div className="flex w-40 flex-col">
              <div className={`rounded-md border px-2.5 py-2 ${tone(step.app)}`}>
                <p className="text-2xs font-semibold uppercase tracking-wide opacity-70">
                  {step.app}
                </p>
                <p className="mt-1 text-xs font-medium capitalize leading-snug text-mist-100">
                  {step.action} {step.label}
                </p>
              </div>
              <p className="tnum mt-1.5 px-0.5 text-2xs text-mist-500">
                ~{duration(step.median_duration_ms)}
              </p>
              {step.alternatives.length > 0 && (
                <div className="mt-1 px-0.5">
                  <p className="text-2xs font-medium text-warn-400">
                    varies ({step.alternatives.length})
                  </p>
                  <ul className="mt-0.5 space-y-0.5">
                    {step.alternatives.slice(0, 2).map((alt) => {
                      const parsed = stepLabel(alt);
                      return (
                        <li key={alt} className="mono truncate">
                          {parsed.app}:{parsed.action}
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}
            </div>
            {index < steps.length - 1 && (
              <div className="flex w-7 shrink-0 items-start justify-center pt-6">
                <svg width="18" height="8" viewBox="0 0 18 8" aria-hidden>
                  <path d="M0 4h13" stroke="#2a3140" strokeWidth="1.25" />
                  <path d="M12 1l4 3-4 3" fill="none" stroke="#2a3140" strokeWidth="1.25" />
                </svg>
              </div>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}

/** Compact inline rendering of a signature, for cards and tables. */
export function SignatureChips({ signature, max = 6 }: { signature: string[]; max?: number }) {
  const shown = signature.slice(0, max);
  return (
    <div className="flex flex-wrap items-center gap-1">
      {shown.map((token, index) => {
        const { app, action } = stepLabel(token);
        return (
          <span key={`${token}-${index}`} className="flex items-center gap-1">
            <span className={`rounded border px-1.5 py-0.5 text-2xs font-medium ${tone(app)}`}>
              {app}
              <span className="ml-1 opacity-60">{action}</span>
            </span>
            {index < shown.length - 1 && <span className="text-mist-600" aria-hidden>›</span>}
          </span>
        );
      })}
      {signature.length > max && (
        <span className="text-2xs text-mist-500">+{signature.length - max}</span>
      )}
    </div>
  );
}
