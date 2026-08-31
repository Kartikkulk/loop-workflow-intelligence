"use client";

import Link from "next/link";
import { useState } from "react";
import { SignatureChips } from "@/components/workflow-graph";
import {
  AvatarRow,
  Badge,
  Empty,
  ErrorNote,
  Loading,
  PageHeader,
  Panel,
  Stat,
} from "@/components/ui";
import { IngestPanel } from "@/components/ingest-panel";
import { useClusters } from "@/lib/api/queries";
import { duration, hours, percent, teamLabel } from "@/lib/format";
import type { ClusterSummary } from "@/lib/api/types";

export default function DiscoveryPage() {
  const { data, isLoading, error } = useClusters();
  const [showIngest, setShowIngest] = useState(false);
  const [showNotRecommended, setShowNotRecommended] = useState(false);

  return (
    <div className="pb-16">
      <PageHeader
        eyebrow="Discovery"
        title="Detected workflows"
        subtitle="Repetitive work mined from the activity log, ranked by what automating it would return. Every number below is measured from observed events — nothing here is configured by hand."
        actions={
          <button className="btn-ghost" onClick={() => setShowIngest((v) => !v)}>
            {showIngest ? "Hide" : "Add activity data"}
          </button>
        }
      />

      <div className="space-y-6 px-8 pt-6">
        {showIngest && <IngestPanel onDone={() => setShowIngest(false)} />}

        {error && <ErrorNote error={error} />}
        {isLoading && <Loading label="Mining workflows" />}

        {data && (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Stat
                label="Workflows detected"
                value={String(data.total)}
                hint={`${data.recommended.length} automatable, ${data.not_recommended.length} not recommended`}
              />
              <Stat
                label="Annual hours at stake"
                value={hours(data.total_annual_hours)}
                unit="hrs/yr"
                tone="accent"
                hint="Median duration × observed frequency × 48 weeks × people"
              />
              <Stat
                label="Interruption tax"
                value={hours(data.total_interruption_tax_hours)}
                unit="hrs/yr"
                tone="warn"
                hint="Cost of context switching, invisible in a time-and-motion study"
              />
              <Stat
                label="Organisation-wide"
                value={String(data.recommended.filter((c) => c.is_organisational).length)}
                hint="Performed by more than 3 people — a team problem, not a personal one"
              />
            </div>

            <Panel
              title="Recommended for automation"
              hint="Sorted by priority: (time + interruption tax) × automatability ÷ build effort"
            >
              {data.recommended.length === 0 ? (
                <Empty
                  title="No automatable workflows yet"
                  hint="Upload an activity log or describe a recurring task to get started."
                />
              ) : (
                <ul className="divide-y divide-ink-700">
                  {data.recommended.map((cluster) => (
                    <ClusterRow key={cluster.id} cluster={cluster} />
                  ))}
                </ul>
              )}
            </Panel>

            {data.not_recommended.length > 0 && (
              <Panel
                title="Not recommended for automation"
                hint="Knowing a task should stay human is a result, not a gap. These are surfaced deliberately."
                actions={
                  <button
                    className="btn-ghost"
                    onClick={() => setShowNotRecommended((v) => !v)}
                  >
                    {showNotRecommended ? "Collapse" : `Show ${data.not_recommended.length}`}
                  </button>
                }
              >
                {showNotRecommended && (
                  <ul className="divide-y divide-ink-700">
                    {data.not_recommended.map((cluster) => (
                      <NotRecommendedRow key={cluster.id} cluster={cluster} />
                    ))}
                  </ul>
                )}
              </Panel>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function ClusterRow({ cluster }: { cluster: ClusterSummary }) {
  return (
    <li className="group transition-colors hover:bg-ink-850/60">
      <Link href={`/clusters/${cluster.id}`} className="block px-4 py-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-medium text-mist-100">{cluster.name}</h3>
              {cluster.is_organisational && <Badge tone="accent">Organisational</Badge>}
              {cluster.has_automation && <Badge tone="good">Automation built</Badge>}
            </div>

            <div className="mt-2.5">
              <SignatureChips signature={cluster.signature} />
            </div>

            <div className="tnum mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-mist-500">
              <span>{cluster.instance_count.toLocaleString()} instances</span>
              <span>{duration(cluster.median_duration_ms)} median</span>
              <span>{cluster.instances_per_user_per_week.toFixed(1)}×/person/week</span>
              <span>
                {cluster.teams.map(teamLabel).join(", ")}
              </span>
            </div>
          </div>

          <div className="flex shrink-0 items-start gap-6">
            <div className="text-right">
              <p className="eyebrow">Hours / yr</p>
              <p className="tnum mt-1 text-lg font-semibold leading-none text-mist-100">
                {hours(cluster.annual_hours)}
              </p>
              <p className="tnum mt-1 text-2xs text-warn-400">
                +{hours(cluster.interruption_tax_hours)} tax
              </p>
            </div>
            <div className="text-right">
              <p className="eyebrow">Automatable</p>
              <p
                className={`tnum mt-1 text-lg font-semibold leading-none ${
                  cluster.automatability >= 0.6 ? "text-good-400" : "text-warn-400"
                }`}
              >
                {percent(cluster.automatability)}
              </p>
              <p className="tnum mt-1 text-2xs text-mist-500">effort {cluster.build_effort}/5</p>
            </div>
            <div className="w-24 text-right">
              <p className="eyebrow">People</p>
              <div className="mt-1.5 flex justify-end">
                <AvatarRow userIds={cluster.user_ids} max={5} />
              </div>
            </div>
          </div>
        </div>
      </Link>
    </li>
  );
}

function NotRecommendedRow({ cluster }: { cluster: ClusterSummary }) {
  return (
    <li className="px-4 py-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href={`/clusters/${cluster.id}`}
              className="text-sm font-medium text-mist-200 hover:text-mist-100"
            >
              {cluster.name}
            </Link>
            <Badge tone="bad">Do not automate</Badge>
          </div>
          <p className="mt-2 max-w-3xl text-2xs leading-relaxed text-mist-400">
            {cluster.reasoning}
          </p>
          <div className="tnum mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-mist-500">
            <span>{cluster.instance_count} instances</span>
            <span>{cluster.variance_breakdown.variant_count} distinct step orders</span>
            <span>entropy {cluster.variance_breakdown.step_order_entropy.toFixed(2)}</span>
            <span>judgement {percent(cluster.variance_breakdown.judgement_ratio)}</span>
          </div>
        </div>
        <div className="text-right">
          <p className="eyebrow">Automatable</p>
          <p className="tnum mt-1 text-lg font-semibold leading-none text-bad-400">
            {percent(cluster.automatability)}
          </p>
          <p className="mt-1 text-2xs text-mist-500">still worth an SOP</p>
        </div>
      </div>
    </li>
  );
}
