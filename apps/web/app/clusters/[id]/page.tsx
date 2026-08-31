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
  Panel,
  Stat,
} from "@/components/ui";
import { apiUrl } from "@/lib/api/client";
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

  if (isLoading) return <Loading label="Loading workflow" />;
  if (error) return <div className="p-8"><ErrorNote error={error} /></div>;
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
              Download SOP
            </a>
            <button className="btn-ghost" onClick={() => setShowSop((v) => !v)}>
              {showSop ? "Hide SOP" : "Preview SOP"}
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
              The SOP is still worth having: it documents the work for a human without
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
            label="Interruption tax"
            value={hours(cluster.interruption_tax_hours)}
            unit="hrs/yr"
            tone="warn"
            hint={`${cluster.context_switches_total} context switches observed across all instances`}
          />
          <Stat
            label="Instances"
            value={cluster.instance_count.toLocaleString()}
            hint={`${cluster.distinct_users} people across ${cluster.teams.length} team(s)`}
          />
          <Stat
            label="Build effort"
            value={`${cluster.build_effort}/5`}
            hint={`Priority score ${cluster.priority.toFixed(1)}`}
          />
        </div>

        <Panel
          title="Observed step sequence"
          hint="The canonical path, with the positions that varied between instances marked."
        >
          <WorkflowGraph steps={cluster.step_graph} />
        </Panel>

        <div className="grid gap-6 lg:grid-cols-3">
          <Panel
            className="lg:col-span-1"
            title="Automatability"
            hint="Inverse of measured variance. Structural signals dominate; judgement is weighted least."
          >
            <div className="space-y-4 px-4 py-4">
              <Gauge
                value={cluster.automatability}
                label={
                  cluster.do_not_automate
                    ? "Too variable to automate safely."
                    : "Consistent enough to automate."
                }
              />
              <dl className="space-y-2.5">
                <VarianceRow
                  label="Step-order entropy"
                  value={variance.step_order_entropy.toFixed(2)}
                  hint="0 = every instance identical, 1 = no dominant order"
                  bad={variance.step_order_entropy > 0.6}
                />
                <VarianceRow
                  label="Distinct step orders"
                  value={String(variance.variant_count)}
                  hint={`most common covers ${percent(variance.dominant_variant_share)}`}
                  bad={variance.dominant_variant_share < 0.4}
                />
                <VarianceRow
                  label="Branch points"
                  value={String(variance.branch_count)}
                  hint="positions where the step differed"
                  bad={variance.branch_count > 4}
                />
                <VarianceRow
                  label="Parameter spread"
                  value={variance.parameter_spread.toFixed(2)}
                  hint="how widely field values vary"
                  bad={variance.parameter_spread > 0.7}
                />
                <VarianceRow
                  label="Judgement content"
                  value={percent(variance.judgement_ratio)}
                  hint="share of the outcome depending on discretion"
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
            title="Observed variants"
            hint="Every distinct step order in this cluster. This is the evidence behind the entropy figure."
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
            {sopLoading && <Loading label="Writing SOP" />}
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
