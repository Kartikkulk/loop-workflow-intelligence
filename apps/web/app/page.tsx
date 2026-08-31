"use client";

import Link from "next/link";
import { TrustBadge } from "@/components/trust-ladder";
import { SignatureChips } from "@/components/workflow-graph";
import { Badge, ErrorNote, Meter, PageHeader, PageSkeleton, Panel, Stat } from "@/components/ui";
import { ProportionBar, StateStripe } from "@/components/viz";
import { useAutomations, useClusters, useRoi, useSystem } from "@/lib/api/queries";
import { hours, percent } from "@/lib/format";

/**
 * The landing screen: what is happening, right now.
 *
 * Everything here links somewhere else — this page answers "what is going on"
 * in about ten seconds and then gets out of the way. It deliberately shows the
 * pipeline as counts rather than as a diagram, because a number that is zero is
 * a more honest picture of the state than a box that is always drawn.
 */
export default function DashboardPage() {
  const clusters = useClusters();
  const automations = useAutomations();
  const roi = useRoi();
  const system = useSystem();

  if (clusters.isLoading || automations.isLoading) return <PageSkeleton rows={4} />;
  const error = clusters.error ?? automations.error;
  if (error) return <div className="p-8"><ErrorNote error={error} /></div>;

  const found = clusters.data;
  const all = automations.data?.items ?? [];
  const running = all.filter((a) => a.trust_level === "ASSIST" || a.trust_level === "AUTONOMOUS");
  const proposed = all.filter((a) => a.trust_level !== "ASSIST" && a.trust_level !== "AUTONOMOUS");

  const recommended = found?.recommended ?? [];
  const refused = found?.not_recommended ?? [];
  const topHours = Math.max(1, ...recommended.map((c) => c.annual_hours));

  const events = system.data?.event_count ?? 0;
  const reclaimable = recommended.reduce(
    (sum, c) => sum + (c.annual_hours + c.interruption_tax_hours) * c.automatability,
    0,
  );

  return (
    <div className="pb-16">
      <PageHeader
        eyebrow="Dashboard"
        title="What's happening"
        subtitle="LOOP watches how work actually gets done, finds the parts people repeat, and turns those into automations you approve before anything runs."
      />

      <div className="space-y-6 px-8 pt-6">
        {/* ── the pipeline, as counts ────────────────────────────────── */}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <PipelineStat
            step="1"
            label="Activity watched"
            value={events.toLocaleString()}
            unit="events"
            hint={`across ${system.data?.cluster_count ?? 0} teams' applications`}
            href="/sources"
            cta="Add a source"
          />
          <PipelineStat
            step="2"
            label="Repetitive work found"
            value={String(found?.total ?? 0)}
            unit="workflows"
            hint={`${refused.length} judged too variable to automate`}
            href="/discovery"
            cta="See what we found"
          />
          <PipelineStat
            step="3"
            label="Waiting on you"
            value={String(proposed.length)}
            unit={proposed.length === 1 ? "proposal" : "proposals"}
            hint={proposed.length ? "Nothing runs until you approve" : "Nothing pending"}
            tone={proposed.length ? "warn" : "default"}
            href="/approvals"
            cta="Review them"
          />
          <PipelineStat
            step="4"
            label="Running for you"
            value={String(running.length)}
            unit={running.length === 1 ? "automation" : "automations"}
            hint={running.length ? "Approved and doing the work" : "Nothing approved yet"}
            tone={running.length ? "good" : "default"}
            href="/automations"
            cta="See them"
          />
        </div>

        {/* ── the headline ───────────────────────────────────────────── */}
        <Panel
          title="Time this could give back"
          hint="Measured from real activity, then scaled by how automatable each workflow actually is — not the raw total."
        >
          <div className="grid gap-5 px-4 py-4 sm:grid-cols-3">
            <div>
              <p className="eyebrow">Spent on repetitive work</p>
              <p className="metric mt-1.5 text-3xl text-mist-100">
                {hours(found?.total_annual_hours ?? 0)}
                <span className="ml-1.5 text-xs font-normal tracking-normal text-mist-500">
                  hrs/yr
                </span>
              </p>
              <p className="mt-2 text-2xs leading-snug text-mist-500">
                Plus {hours(found?.total_interruption_tax_hours ?? 0)} hrs lost switching between
                applications
              </p>
            </div>

            <div>
              <p className="eyebrow">Could be handed over</p>
              <p className="metric mt-1.5 text-3xl text-good-400">
                {hours(reclaimable)}
                <span className="ml-1.5 text-xs font-normal tracking-normal text-mist-500">
                  hrs/yr
                </span>
              </p>
              <div className="mt-2.5">
                <Meter
                  value={reclaimable / Math.max(1, found?.total_annual_hours ?? 1)}
                  tone="good"
                />
              </div>
            </div>

            <div>
              <p className="eyebrow">Actually handed over</p>
              <p className="metric mt-1.5 text-3xl text-mist-100">
                {hours(roi.data?.realised_annual_hours ?? 0)}
                <span className="ml-1.5 text-xs font-normal tracking-normal text-mist-500">
                  hrs/yr
                </span>
              </p>
              <p className="mt-2 text-2xs leading-snug text-mist-500">
                {running.length === 0
                  ? "Nothing approved yet — approve a proposal to start"
                  : `From ${running.length} running automation${running.length === 1 ? "" : "s"}`}
              </p>
            </div>
          </div>
        </Panel>

        <div className="grid gap-6 lg:grid-cols-2">
          {/* ── recent discoveries ───────────────────────────────────── */}
          <Panel
            title="Repetitive work we found"
            hint="Ranked by what handing it over would give back."
            actions={
              <Link className="link text-2xs" href="/discovery">
                See all {found?.total ?? 0}
              </Link>
            }
          >
            <ul className="divide-y divide-ink-700">
              {recommended.slice(0, 4).map((cluster) => (
                <li key={cluster.id} className="row-interactive">
                  <Link href={`/clusters/${cluster.id}`} className="flex gap-3 px-4 py-3">
                    <StateStripe state={cluster.has_automation ? "good" : "warn"} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-3">
                        <span className="truncate text-xs font-medium text-mist-100">
                          {cluster.name}
                        </span>
                        <span className="metric shrink-0 text-sm text-accent-400">
                          {hours(cluster.annual_hours)}
                          <span className="ml-1 text-2xs font-normal text-mist-500">hrs/yr</span>
                        </span>
                      </div>
                      <div className="mt-1.5">
                        <SignatureChips signature={cluster.signature} max={4} />
                      </div>
                      <div className="mt-2">
                        <ProportionBar value={cluster.annual_hours} max={topHours} />
                      </div>
                      <p className="tnum mt-1.5 text-2xs text-mist-500">
                        {cluster.instance_count.toLocaleString()} times ·{" "}
                        {cluster.distinct_users} people ·{" "}
                        {percent(cluster.automatability)} automatable
                      </p>
                    </div>
                  </Link>
                </li>
              ))}

              {refused.slice(0, 1).map((cluster) => (
                <li key={cluster.id} className="px-4 py-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="truncate text-xs font-medium text-mist-300">
                      {cluster.name}
                    </span>
                    <Badge tone="bad">Kept human</Badge>
                  </div>
                  <p className="mt-1 text-2xs leading-relaxed text-mist-500">
                    Too variable to automate safely — {cluster.variance_breakdown.variant_count}{" "}
                    different ways of doing it across {cluster.instance_count} times.
                  </p>
                </li>
              ))}
            </ul>
          </Panel>

          {/* ── automation status ────────────────────────────────────── */}
          <Panel
            title="Automations"
            hint="Each one has to earn the right to act, a step at a time."
            actions={
              proposed.length > 0 ? (
                <Link className="link text-2xs" href="/approvals">
                  {proposed.length} to approve
                </Link>
              ) : undefined
            }
          >
            {all.length === 0 ? (
              <div className="px-4 py-10 text-center">
                <p className="text-xs font-medium text-mist-300">Nothing built yet</p>
                <p className="mx-auto mt-1.5 max-w-xs text-2xs leading-relaxed text-mist-500">
                  Open a workflow from Discovery and turn it into an automation.
                </p>
              </div>
            ) : (
              <ul className="divide-y divide-ink-700">
                {all.slice(0, 5).map((automation) => {
                  const isRunning =
                    automation.trust_level === "ASSIST" ||
                    automation.trust_level === "AUTONOMOUS";
                  return (
                    <li key={automation.id} className="row-interactive">
                      <Link
                        href={`/automations/${automation.id}`}
                        className="flex gap-3 px-4 py-3"
                      >
                        <StateStripe state={isRunning ? "good" : "warn"} />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center justify-between gap-3">
                            <span className="truncate text-xs font-medium text-mist-100">
                              {automation.name}
                            </span>
                            <TrustBadge level={automation.trust_level} />
                          </div>
                          <div className="mt-2 flex items-center gap-2">
                            <Meter
                              value={automation.confidence}
                              tone={isRunning ? "good" : "accent"}
                            />
                            <span className="tnum w-9 shrink-0 text-right text-2xs text-mist-400">
                              {percent(automation.confidence)}
                            </span>
                          </div>
                          <p className="tnum mt-1.5 text-2xs text-mist-500">
                            {isRunning
                              ? `running · covering ${hours(automation.annual_hours)} hrs/yr`
                              : `proposed · ${automation.shadow_run_count} trial run${automation.shadow_run_count === 1 ? "" : "s"} so far`}
                          </p>
                        </div>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}

function PipelineStat({
  step,
  label,
  value,
  unit,
  hint,
  tone = "default",
  href,
  cta,
}: {
  step: string;
  label: string;
  value: string;
  unit: string;
  hint: string;
  tone?: "default" | "good" | "warn";
  href: string;
  cta: string;
}) {
  const toneClass = { default: "text-mist-100", good: "text-good-400", warn: "text-warn-400" }[
    tone
  ];
  return (
    <Link
      href={href}
      className="panel group flex flex-col px-4 py-3.5 shadow-lift transition-colors hover:border-ink-600"
    >
      <div className="flex items-center gap-2">
        <span className="flex h-4 w-4 items-center justify-center rounded-full border border-ink-600 text-[9px] font-semibold text-mist-500">
          {step}
        </span>
        <p className="eyebrow">{label}</p>
      </div>
      <p className={`metric mt-2 text-2xl ${toneClass}`}>
        {value}
        <span className="ml-1 text-xs font-normal tracking-normal text-mist-500">{unit}</span>
      </p>
      <p className="mt-2 text-2xs leading-snug text-mist-500">{hint}</p>
      <span className="mt-2.5 text-2xs font-medium text-accent-400 opacity-0 transition-opacity group-hover:opacity-100">
        {cta} →
      </span>
    </Link>
  );
}
