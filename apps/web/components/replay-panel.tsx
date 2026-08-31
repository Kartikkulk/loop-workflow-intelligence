"use client";

import { useState } from "react";
import { Empty, Meter, Panel } from "./ui";
import { formatFieldValue, percent } from "@/lib/format";
import { useReplay } from "@/lib/api/queries";

/**
 * The backtest. Failures are expanded by default and never rounded away —
 * naming your own failure modes before a reviewer finds them is the point.
 */
export function ReplayPanel({ automationId }: { automationId: string }) {
  const [days, setDays] = useState(30);
  const replay = useReplay();
  const report = replay.data;

  return (
    <Panel
      title="Replay dry-run"
      hint="Executes against historical events with side effects mocked, then diffs the result against what the human actually did."
      actions={
        <div className="flex items-center gap-2">
          <select
            value={days}
            onChange={(event) => setDays(Number(event.target.value))}
            className="rounded-md border border-ink-600 bg-ink-850 px-2 py-1 text-2xs text-mist-300 focus:border-accent-500 focus:outline-none"
          >
            {[7, 30, 60, 90].map((value) => (
              <option key={value} value={value}>
                {value} days
              </option>
            ))}
          </select>
          <button
            className="btn-ghost"
            disabled={replay.isPending}
            onClick={() => replay.mutate({ id: automationId, days })}
          >
            {replay.isPending ? "Replaying…" : "Run backtest"}
          </button>
        </div>
      }
    >
      {!report && !replay.isPending && (
        <Empty
          title="No backtest yet"
          hint="Run one to see how this automation would have performed against the last 30 days of real activity."
        />
      )}

      {report && (
        <div className="space-y-4 px-4 py-4">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div>
              <p className="eyebrow">Accuracy</p>
              <p
                className={`tnum mt-1 text-2xl font-semibold leading-none ${
                  report.accuracy >= 0.9 ? "text-good-400" : "text-warn-400"
                }`}
              >
                {percent(report.accuracy, 2)}
              </p>
              <div className="mt-2">
                <Meter
                  value={report.accuracy}
                  tone={report.accuracy >= 0.9 ? "good" : "warn"}
                />
              </div>
            </div>
            <Figure label="Correct" value={`${report.correct} / ${report.total}`} />
            <Figure
              label="Withheld by guard"
              value={String(report.needs_approval)}
              hint="Correctly stopped for a human"
            />
            <Figure
              label="Failed"
              value={String(report.total - report.correct)}
              hint={report.errored ? `${report.errored} step errors` : undefined}
            />
          </div>

          {Object.keys(report.failure_modes).length > 0 && (
            <div className="border-t border-ink-800 pt-3.5">
              <p className="eyebrow mb-2">Failure modes, named</p>
              <ul className="space-y-1.5">
                {Object.entries(report.failure_modes).map(([reason, count]) => (
                  <li key={reason} className="flex items-start gap-2.5">
                    <span className="tnum mt-px shrink-0 rounded border border-ink-600 bg-ink-800 px-1.5 py-0.5 text-2xs font-semibold text-mist-300">
                      {count}×
                    </span>
                    <span className="text-2xs leading-relaxed text-mist-400">{reason}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {report.failures.length > 0 && (
            <details open className="border-t border-ink-800 pt-3.5">
              <summary className="eyebrow cursor-pointer">
                Individual failures ({report.failures.length} shown)
              </summary>
              <div className="mt-2.5 max-h-72 space-y-2 overflow-auto">
                {report.failures.map((failure) => (
                  <div
                    key={failure.event_id}
                    className="rounded-md border border-ink-700 bg-ink-850 px-3 py-2.5"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <p className="text-2xs leading-relaxed text-mist-300">{failure.reason}</p>
                      {failure.critical && (
                        <span className="shrink-0 rounded border border-bad-500/40 bg-bad-500/10 px-1.5 py-0.5 text-[9px] font-semibold text-bad-400">
                          CRITICAL
                        </span>
                      )}
                    </div>
                    {failure.diff_fields.length > 0 && (
                      <table className="mt-2 w-full text-2xs">
                        <tbody>
                          {failure.diff_fields.map((field) => (
                            <tr key={field}>
                              <td className="w-28 py-0.5 font-medium text-mist-400">{field}</td>
                              <td className="mono py-0.5">
                                predicted {formatFieldValue(failure.predicted[field])}
                              </td>
                              <td className="mono py-0.5">
                                actual {formatFieldValue(failure.expected[field])}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                    <p className="mono mt-1.5">{failure.event_id}</p>
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
      )}
    </Panel>
  );
}

function Figure({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <p className="eyebrow">{label}</p>
      <p className="tnum mt-1 text-2xl font-semibold leading-none text-mist-100">{value}</p>
      {hint && <p className="mt-2 text-2xs leading-snug text-mist-500">{hint}</p>}
    </div>
  );
}
