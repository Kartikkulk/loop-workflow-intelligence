"use client";

import { Empty } from "./ui";
import { formatFieldValue, percent, relativeTime } from "@/lib/format";
import type { ShadowRun } from "@/lib/api/types";

/**
 * Per-field agreement for every shadow run.
 *
 * Rows expand to show the actual predicted and observed values side by side.
 * A score alone is not evidence — being able to point at the field that
 * disagreed, and at what each party said, is what makes the ladder credible.
 */
export function ShadowRunTable({ runs }: { runs: ShadowRun[] }) {
  if (!runs.length) {
    return (
      <Empty
        title="No shadow runs yet"
        hint="Simulate a run to record what this automation would have done while a human did the task for real."
      />
    );
  }

  return (
    <div className="divide-y divide-ink-800">
      {runs.map((run) => {
        const fields = Object.entries(run.field_matches);
        const matched = fields.filter(([, ok]) => ok).length;
        return (
          <details key={run.id} className="group">
            <summary className="flex cursor-pointer list-none items-center gap-4 px-4 py-2.5 transition-colors hover:bg-ink-850/60">
              <span className="tnum w-8 shrink-0 text-2xs text-mist-500">#{run.sequence}</span>

              <span className="flex w-24 shrink-0 items-center gap-2">
                <span
                  className={`tnum text-xs font-semibold ${
                    run.critical_mismatch
                      ? "text-bad-400"
                      : run.score >= 0.9
                        ? "text-good-400"
                        : "text-warn-400"
                  }`}
                >
                  {percent(run.score, 0)}
                </span>
                {run.critical_mismatch && (
                  <span className="rounded border border-bad-500/40 bg-bad-500/10 px-1 py-0.5 text-[9px] font-semibold text-bad-400">
                    CRITICAL
                  </span>
                )}
              </span>

              <span className="flex w-28 shrink-0 items-center gap-0.5" aria-label="field agreement">
                {fields.length === 0 ? (
                  <span className="text-2xs text-mist-600">withheld</span>
                ) : (
                  fields.map(([field, ok]) => (
                    <span
                      key={field}
                      title={field}
                      className={`h-3 w-3 rounded-sm ${ok ? "bg-good-500/70" : "bg-bad-500/70"}`}
                    />
                  ))
                )}
              </span>

              <span className="min-w-0 flex-1 truncate text-2xs text-mist-400">{run.note}</span>

              <span className="shrink-0 text-2xs text-mist-600">
                {fields.length > 0 && `${matched}/${fields.length} · `}
                {relativeTime(run.created_at)}
              </span>
              <span
                className="shrink-0 text-mist-600 transition-transform group-open:rotate-90"
                aria-hidden
              >
                ›
              </span>
            </summary>

            <div className="bg-ink-950/60 px-4 py-3">
              {fields.length === 0 ? (
                <p className="text-2xs text-mist-500">
                  This run was withheld by a guard before producing any fields, so there is
                  nothing to compare. That counts as correct behaviour, not agreement.
                </p>
              ) : (
                <table className="w-full text-2xs">
                  <thead>
                    <tr className="text-left">
                      <th className="pb-1.5 font-medium text-mist-600">Field</th>
                      <th className="pb-1.5 font-medium text-mist-600">Automation predicted</th>
                      <th className="pb-1.5 font-medium text-mist-600">Human recorded</th>
                      <th className="pb-1.5 text-right font-medium text-mist-600">Match</th>
                    </tr>
                  </thead>
                  <tbody>
                    {fields.map(([field, ok]) => (
                      <tr key={field} className="border-t border-ink-800/70">
                        <td className="py-1.5 pr-3 font-medium text-mist-300">{field}</td>
                        <td className="mono py-1.5 pr-3">
                          {formatFieldValue(run.predicted[field])}
                        </td>
                        <td className="mono py-1.5 pr-3">
                          {formatFieldValue(run.observed[field])}
                        </td>
                        <td className="py-1.5 text-right">
                          <span className={ok ? "text-good-400" : "text-bad-400"}>
                            {ok ? "✓" : "✗"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </details>
        );
      })}
    </div>
  );
}
