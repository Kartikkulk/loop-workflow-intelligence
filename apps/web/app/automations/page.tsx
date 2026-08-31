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

  const items = data?.items ?? [];
  const byLevel = TRUST_LADDER.map((level) => ({
    level,
    count: items.filter((a) => a.trust_level === level).length,
  }));
  const trusted = items.filter(
    (a) => a.trust_level === "ASSIST" || a.trust_level === "AUTONOMOUS",
  ).length;

  return (
    <div className="pb-16">
      <PageHeader
        eyebrow="Automations"
        title="Built automations"
        subtitle="Each automation climbs the trust ladder by agreeing with a human often enough to earn the next rung. Nothing starts trusted, and a single critical mismatch sends it back down."
      />

      <div className="space-y-6 px-8 pt-6">
        {error && <ErrorNote error={error} />}
        {isLoading && <PageSkeleton rows={3} />}

        {data && (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Stat label="Automations" value={String(items.length)} />
              <Stat
                label="Earned trust"
                value={String(trusted)}
                tone={trusted > 0 ? "good" : "default"}
                hint="At ASSIST or above — running with or without a human in the loop"
              />
              <Stat
                label="Hours addressed"
                value={hours(items.reduce((sum, a) => sum + a.annual_hours, 0))}
                unit="hrs/yr"
                tone="accent"
              />
              <Stat
                label="Shadow runs"
                value={String(items.reduce((sum, a) => sum + a.shadow_run_count, 0))}
                hint="Predictions compared against real human work"
              />
            </div>

            <Panel title="Distribution across the ladder">
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

            <Panel title="All automations">
              {items.length === 0 ? (
                <Empty
                  title="No automations yet"
                  hint="An automation is generated from a detected workflow. Pick the highest-priority one and press Generate."
                  action={
                    <Link className="btn-primary" href="/">
                      Go to Discovery
                    </Link>
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
