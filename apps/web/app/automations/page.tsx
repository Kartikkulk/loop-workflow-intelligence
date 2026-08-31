"use client";

import Link from "next/link";
import { TrustBadge } from "@/components/trust-ladder";
import {
  Empty,
  ErrorNote,
  Meter,
  PageHeader,
  PageSkeleton,
  Panel,
  Stat,
} from "@/components/ui";
import { StateStripe } from "@/components/viz";
import { useAutomations } from "@/lib/api/queries";
import { hours, percent, relativeTime } from "@/lib/format";
import { TRUST_LADDER } from "@/lib/api/types";

export default function AutomationsPage() {
  const { data, isLoading, error } = useAutomations();

  const all = data?.items ?? [];
  // Only ASSIST and AUTONOMOUS actually act. Anything below is a proposal, and
  // showing it here would imply work is being automated when none is.
  const items = all.filter(
    (a) => a.trust_level === "ASSIST" || a.trust_level === "AUTONOMOUS",
  );
  const proposed = all.filter(
    (a) => a.trust_level !== "ASSIST" && a.trust_level !== "AUTONOMOUS",
  );
  const byLevel = TRUST_LADDER.map((level) => ({
    level,
    count: all.filter((a) => a.trust_level === level).length,
  }));

  return (
    <div className="pb-16">
      <PageHeader
        eyebrow="Step 4 of 4"
        title="Running for you now"
        subtitle="Work that has been approved and is actually being done. Each of these earned it by agreeing with a person often enough — and a single serious disagreement sends it straight back to Approvals."
        actions={
          proposed.length > 0 ? (
            <Link className="btn-ghost" href="/approvals">
              {proposed.length} waiting for approval
            </Link>
          ) : undefined
        }
      />

      <div className="space-y-6 px-8 pt-6">
        {error && <ErrorNote error={error} />}
        {isLoading && <PageSkeleton rows={3} />}

        {data && (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Stat
                label="Running now"
                value={String(items.length)}
                tone={items.length > 0 ? "good" : "default"}
                hint={
                  items.length > 0
                    ? "Approved and doing the work"
                    : "Nothing has been approved to run yet"
                }
              />
              <Stat
                label="Fully unattended"
                value={String(all.filter((a) => a.trust_level === "AUTONOMOUS").length)}
                hint="Runs without anyone confirming each step"
              />
              <Stat
                label="Hours being handled"
                value={hours(items.reduce((sum, a) => sum + a.annual_hours, 0))}
                unit="hrs/yr"
                tone="accent"
                hint="Work these automations are covering"
              />
              <Stat
                label="Awaiting approval"
                value={String(proposed.length)}
                tone={proposed.length > 0 ? "warn" : "default"}
                hint="Built, tested, not yet approved to act"
              />
            </div>

            <Panel
              title="How far each has earned"
              hint="Trust is granted a rung at a time, by measured agreement — never all at once."
            >
              <div className="flex items-stretch gap-1.5 px-4 py-4">
                {byLevel.map(({ level, count }) => (
                  <div key={level} className="min-w-0 flex-1">
                    <div
                      className={`h-0.5 rounded-full ${count > 0 ? "bg-accent-500" : "bg-ink-700"}`}
                    />
                    <p className="metric mt-2 text-lg text-mist-100">{count}</p>
                    <p className="mt-1 text-2xs font-medium tracking-wide text-mist-500">
                      {level}
                    </p>
                  </div>
                ))}
              </div>
            </Panel>

            <Panel
              title="Running automations"
              hint="Open one to see its trial runs, its backtest, and every field it agreed or disagreed on."
            >
              {items.length === 0 ? (
                <Empty
                  title="Nothing is running yet"
                  hint={
                    proposed.length > 0
                      ? `${proposed.length} workflow${proposed.length === 1 ? " is" : "s are"} built and waiting for you to approve. Nothing acts until you do.`
                      : "Workflows appear here once you approve them. Start by connecting the tools your team uses."
                  }
                  action={
                    proposed.length > 0 ? (
                      <Link className="btn-primary" href="/approvals">
                        Review {proposed.length} waiting
                      </Link>
                    ) : (
                      <Link className="btn-primary" href="/integrations">
                        Connect your tools
                      </Link>
                    )
                  }
                />
              ) : (
                <ul className="divide-y divide-ink-700">
                  {items.map((automation) => (
                    <li key={automation.id} className="row-interactive">
                      <Link
                        href={`/automations/${automation.id}`}
                        className="flex gap-3 px-4 py-4"
                      >
                        <StateStripe
                          state={
                            automation.critical_mismatch_count > 0
                              ? "bad"
                              : automation.trust_level === "AUTONOMOUS" ||
                                  automation.trust_level === "ASSIST"
                                ? "good"
                                : automation.shadow_run_count > 0
                                  ? "warn"
                                  : "idle"
                          }
                        />
                        <div className="flex min-w-0 flex-1 flex-wrap items-start justify-between gap-4">
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <h3 className="text-sm font-medium text-mist-100">
                                {automation.name}
                              </h3>
                              <TrustBadge level={automation.trust_level} />
                              {automation.critical_mismatch_count > 0 && (
                                <span className="tnum text-2xs text-bad-400">
                                  {automation.critical_mismatch_count} critical mismatch
                                  {automation.critical_mismatch_count === 1 ? "" : "es"}
                                </span>
                              )}
                            </div>
                            <p className="mt-1.5 max-w-2xl text-2xs leading-relaxed text-mist-500">
                              {automation.description}
                            </p>
                            <div className="tnum mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-mist-500">
                              <span>{automation.step_count} steps</span>
                              <span>{automation.shadow_run_count} shadow runs</span>
                              {automation.replay_accuracy !== null && (
                                <span>
                                  replay {percent(automation.replay_accuracy, 1)}
                                </span>
                              )}
                              <span className="mono">via {automation.generated_by}</span>
                              <span>{relativeTime(automation.created_at)}</span>
                            </div>
                          </div>

                          <div className="flex shrink-0 items-start gap-6">
                            <div className="w-32">
                              <p className="eyebrow">Confidence</p>
                              <p className="metric mt-1 text-lg text-mist-100">
                                {percent(automation.confidence, 1)}
                              </p>
                              <div className="mt-2">
                                <Meter
                                  value={automation.confidence}
                                  tone={
                                    automation.critical_mismatch_count > 0 ? "bad" : "accent"
                                  }
                                />
                              </div>
                            </div>
                            <div className="text-right">
                              <p className="eyebrow">Hours / yr</p>
                              <p className="metric mt-1 text-lg text-accent-400">
                                {hours(automation.annual_hours)}
                              </p>
                              <p className="tnum mt-1 text-2xs text-mist-500">
                                coverage {percent(automation.coverage)}
                              </p>
                            </div>
                          </div>
                        </div>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </>
        )}
      </div>
    </div>
  );
}
