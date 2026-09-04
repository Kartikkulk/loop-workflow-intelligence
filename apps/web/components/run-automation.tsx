"use client";

import { ErrorNote, Panel } from "@/components/ui";
import { useRunAutomation } from "@/lib/api/queries";
import type { Step } from "@/lib/api/types";

/** Connectors whose live implementation is local and needs no account. */
const RUNNABLE = new Set(["files", "pdf", "git"]);

/**
 * Executes the automation for real, over whatever is waiting in the inbox.
 *
 * Offered only when every step is local work. A step on a SaaS system needs an
 * account configured before it could do anything, and a button that cannot
 * work is worse than no button — so for those the panel explains what is
 * missing instead of failing when pressed.
 */
export function RunAutomation({ id, steps }: { id: string; steps: Step[] }) {
  const run = useRunAutomation(id);
  const connectors = [...new Set(steps.map((s) => s.connector))];
  const blocked = connectors.filter((c) => !RUNNABLE.has(c));

  return (
    <Panel
      title="Run it"
      hint="Executes for real, over everything waiting in the inbox."
    >
      <div className="space-y-4 px-4 py-4">
        {blocked.length > 0 ? (
          <p className="text-2xs leading-relaxed text-mist-500">
            This automation touches{" "}
            <span className="mono text-mist-300">{blocked.join(", ")}</span>, which needs an
            account connected before it can act. Export it to n8n and pick the account there.
          </p>
        ) : (
          <>
            <p className="text-2xs leading-relaxed text-mist-500">
              Every step here is local file work, so it runs with nothing to configure. The
              guard still holds anything the observation said a person should look at.
            </p>
            <button
              className="btn-primary px-4 py-2 text-xs"
              disabled={run.isPending}
              onClick={() => run.mutate()}
              type="button"
            >
              {run.isPending ? "Running…" : "Run automation"}
            </button>
          </>
        )}

        {run.error && <ErrorNote error={run.error} />}

        {run.data && (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-3">
              <span
                className={`text-2xs font-medium ${
                  run.data.dry_run
                    ? "text-warn-400"
                    : run.data.ok
                      ? "text-good-400"
                      : "text-bad-400"
                }`}
              >
                {run.data.message}
              </span>
            </div>

            {run.data.side_effects.length > 0 && (
              <div>
                <p className="eyebrow mb-1 text-mist-600">What changed</p>
                <ul className="space-y-0.5">
                  {run.data.side_effects.slice(0, 8).map((effect, i) => (
                    <li key={`${effect}-${i}`} className="mono text-2xs text-mist-400">
                      {effect}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="max-h-56 overflow-auto">
              {run.data.items.map((item) => (
                <p key={item.item} className="mono text-2xs text-mist-400">
                  <span
                    className={
                      item.status === "done"
                        ? "text-good-400"
                        : item.status === "held"
                          ? "text-warn-400"
                          : "text-bad-400"
                    }
                  >
                    {item.status === "done" ? "✓" : item.status === "held" ? "⚠" : "✕"}
                  </span>{" "}
                  {item.item}
                  {item.status !== "done" && (
                    <span className="text-mist-600"> — {item.detail}</span>
                  )}
                </p>
              ))}
            </div>
          </div>
        )}
      </div>
    </Panel>
  );
}
