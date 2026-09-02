"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { WorkflowGraph } from "@/components/workflow-graph";
import {
  AvatarRow,
  Badge,
  ErrorNote,
  Gauge,
  Loading,
  PageHeader,
  PageSkeleton,
  Panel,
  Stat,
} from "@/components/ui";
import { ApiError, apiUrl } from "@/lib/api/client";
import { useCluster, useGenerateAutomation, useSop } from "@/lib/api/queries";
import { displayName, duration, hours, percent, teamLabel } from "@/lib/format";

export default function ClusterDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = params.id;
  const { data: cluster, isLoading, error } = useCluster(id);
  const [showSop, setShowSop] = useState(false);
  const { data: sop, isLoading: sopLoading } = useSop(id, showSop);
  const generate = useGenerateAutomation();

  if (isLoading) return <PageSkeleton rows={2} />;
  if (error) {
    // A 404 here means the automation pointed at a workflow that no longer
    // exists (stale link from an older detection run). Explain it plainly and
    // offer the way back, rather than dumping a raw error.
    const notFound =
      (error instanceof ApiError && error.status === 404) ||
      /not found/i.test(String((error as Error)?.message ?? ""));
    return (
      <div className="pb-16">
        <PageHeader back={{ href: "/", label: "Discovery" }} eyebrow="Workflow" title="Workflow unavailable" />
        <div className="px-8 pt-6">
          {notFound ? (
            <div className="panel border-warn-500/30 bg-warn-500/5 px-4 py-4">
              <p className="text-sm font-medium text-mist-100">This workflow isn&apos;t available</p>
              <p className="mt-1.5 max-w-2xl text-xs leading-relaxed text-mist-400">
                The link points to a detected workflow that no longer exists — usually because
                detection was re-run since this automation was created. Re-seeding the demo
                (or the next detection pass) re-links it automatically.
              </p>
              <div className="mt-3 flex gap-2">
                <Link className="btn-primary" href="/">
                  Back to Discovery
                </Link>
                <Link className="btn-ghost" href="/automations">
                  View automations
                </Link>
              </div>
            </div>
          ) : (
            <ErrorNote error={error} />
          )}
        </div>
      </div>
    );
  }
  if (!cluster) return null;

  const variance = cluster.variance_breakdown;

  return (
    <div className="pb-16">
      <PageHeader
        back={{ href: "/", label: "Discovery" }}
        eyebrow={cluster.is_organisational ? "Organisational workflow" : "Workflow"}
        title={cluster.name}
        subtitle={cluster.description}
        actions={
          <>
            <a className="btn-ghost" href={apiUrl(`/api/v1/clusters/${id}/sop.md`)} download>
              Download the guide
            </a>
            <button className="btn-ghost" onClick={() => setShowSop((v) => !v)}>
              {showSop ? "Hide the guide" : "Preview the guide"}
            </button>
            {cluster.has_automation && cluster.automation_id ? (
              <Link className="btn-primary" href={`/automations/${cluster.automation_id}`}>
                Open automation
              </Link>
            ) : (
              <button
                className="btn-primary"
                disabled={generate.isPending}
                onClick={() =>
                  generate.mutate(
                    { clusterId: id, override: cluster.do_not_automate },
                    { onSuccess: (data) => router.push(`/automations/${data.id}`) },
                  )
                }
              >
                {generate.isPending
                  ? "Generating…"
                  : cluster.do_not_automate
                    ? "Generate anyway"
                    : "Generate automation"}
              </button>
            )}
          </>
        }
      />

      <div className="space-y-6 px-8 pt-6">
        {generate.error && <ErrorNote error={generate.error} />}

        {cluster.do_not_automate && (
          <div className="panel border-bad-500/30 bg-bad-500/5 px-4 py-3.5">
            <div className="flex items-center gap-2">
              <Badge tone="bad">Do not automate</Badge>
              <span className="tnum text-2xs text-mist-500">
                automatability {percent(cluster.automatability)} — below the{" "}
                {percent(0.4)} threshold
              </span>
            </div>
            <p className="mt-2 max-w-3xl text-xs leading-relaxed text-mist-300">
              {cluster.reasoning}
            </p>
            <p className="mt-2 text-2xs leading-relaxed text-mist-500">
              A written guide is still worth having: it records the work for a person without
              pretending a machine can take it over.
            </p>
          </div>
        )}

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            label="Annual hours"
            value={hours(cluster.annual_hours)}
            unit="hrs/yr"
            tone="accent"
            hint={`${duration(cluster.median_duration_ms)} × ${cluster.instances_per_user_per_week.toFixed(1)}/wk × 48 × ${cluster.distinct_users}`}
          />
          <Stat
            label="Time lost switching apps"
            value={hours(cluster.interruption_tax_hours)}
            unit="hrs/yr"
            tone="warn"
            hint={`People jumped between apps ${cluster.context_switches_total.toLocaleString()} times doing this`}
          />
          <Stat
            label="Times people did this"
            value={cluster.instance_count.toLocaleString()}
            hint={`${cluster.distinct_users} people across ${cluster.teams.length} team(s)`}
          />
          <Stat
            label="Effort to automate"
            value={`${cluster.build_effort}/5`}
            hint={cluster.build_effort <= 2 ? "Straightforward to build" : "Needs some rules written"}
          />
        </div>

        <Panel
          title="What people actually do"
          hint="The usual path, start to finish. Marked steps are the ones that changed between runs."
        >
          <WorkflowGraph steps={cluster.step_graph} />
        </Panel>

        <div className="grid gap-6 lg:grid-cols-3">
          <Panel
            className="lg:col-span-1"
            title="Can this be automated?"
            hint="Scored from how consistently people repeat it. Work that is done the same way every time scores high."
          >
            <div className="space-y-4 px-4 py-4">
              <Gauge
                value={cluster.automatability}
                label={
                  cluster.do_not_automate
                    ? "Too unpredictable — a person should keep doing this."
                    : "Done the same way often enough to hand over."
                }
              />
              <dl className="space-y-2.5">
                <VarianceRow
                  label="How much the order varies"
                  value={variance.step_order_entropy.toFixed(2)}
                  hint="0 means everyone does it the same way; 1 means no two runs match"
                  bad={variance.step_order_entropy > 0.6}
                />
                <VarianceRow
                  label="Different ways people did it"
                  value={String(variance.variant_count)}
                  hint={`the most common way covers ${percent(variance.dominant_variant_share)} of runs`}
                  bad={variance.dominant_variant_share < 0.4}
                />
                <VarianceRow
                  label="Steps that changed between runs"
                  value={String(variance.branch_count)}
                  hint="each one needs its own rule before this can run unattended"
                  bad={variance.branch_count > 4}
                />
                <VarianceRow
                  label="How much the details vary"
                  value={variance.parameter_spread.toFixed(2)}
                  hint="whether the values typed in change a lot from run to run"
                  bad={variance.parameter_spread > 0.7}
                />
                <VarianceRow
                  label="How much needs a human decision"
                  value={percent(variance.judgement_ratio)}
                  hint="the share of this work that depends on someone thinking, not just typing"
                  bad={variance.judgement_ratio > 0.4}
                />
              </dl>
            </div>
          </Panel>

          <Panel
            className="lg:col-span-2"
            title="Who performs this"
            hint={
              cluster.is_organisational
                ? "More than three people do this — it is a team problem, not a personal habit."
                : undefined
            }
            actions={<AvatarRow userIds={cluster.user_ids} max={8} />}
          >
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-ink-700 text-left">
                  <th className="px-4 py-2 font-medium text-mist-500">Person</th>
                  <th className="px-4 py-2 font-medium text-mist-500">Team</th>
                  <th className="px-4 py-2 text-right font-medium text-mist-500">Instances</th>
                  <th className="px-4 py-2 text-right font-medium text-mist-500">Median</th>
                  <th className="px-4 py-2 text-right font-medium text-mist-500">Hrs/yr</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-800">
                {cluster.users.map((user) => (
                  <tr key={user.user_id}>
                    <td className="px-4 py-2 text-mist-200">{displayName(user.user_id)}</td>
                    <td className="px-4 py-2 text-mist-400">{teamLabel(user.team)}</td>
                    <td className="tnum px-4 py-2 text-right text-mist-300">
                      {user.instance_count}
                    </td>
                    <td className="tnum px-4 py-2 text-right text-mist-400">
                      {duration(user.median_duration_ms)}
                    </td>
                    <td className="tnum px-4 py-2 text-right text-mist-200">
                      {user.annual_hours.toFixed(1)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </div>

        <div className="grid gap-6">
          <Panel
            title="Every way people did this"
            hint="Each distinct order we saw, most common first. This is the evidence behind the score above."
          >
            <ul className="divide-y divide-ink-800">
              {cluster.variants.map((variant, index) => (
                <li key={index} className="px-4 py-2.5">
                  <div className="flex items-center justify-between gap-3">
                    <p className="mono min-w-0 flex-1 truncate">
                      {variant.signature
                        .map((token) => token.split(":").slice(0, 2).join(":"))
                        .join(" › ")}
                    </p>
                    <span className="tnum shrink-0 text-2xs text-mist-400">
                      {variant.count} · {percent(variant.share)}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          </Panel>
        </div>

        {showSop && (
          <Panel
            title="Standard operating procedure"
            hint={sop ? `Generated by ${sop.generated_by}` : undefined}
          >
            {sopLoading && <Loading label="Writing the guide" />}
            {sop && (
              <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap px-4 py-4 text-xs leading-relaxed text-mist-300">
                {sop.markdown}
              </pre>
            )}
          </Panel>
        )}
      </div>
    </div>
  );
}

function VarianceRow({
  label,
  value,
  hint,
  bad,
}: {
  label: string;
  value: string;
  hint: string;
  bad: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <dt className="text-2xs font-medium text-mist-300">{label}</dt>
        <dd className="mt-0.5 text-2xs leading-snug text-mist-600">{hint}</dd>
      </div>
      <span
        className={`tnum shrink-0 text-xs font-semibold ${bad ? "text-warn-400" : "text-mist-200"}`}
      >
        {value}
      </span>
    </div>
  );
}
