"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { TrustLadder, TrustBadge } from "@/components/trust-ladder";
import { ShadowRunTable } from "@/components/shadow-run-table";
import { ReplayPanel } from "@/components/replay-panel";
import { FlowDefinition } from "@/components/flow-definition";
import {
  Badge,
  ErrorNote,
  Meter,
  PageHeader,
  PageSkeleton,
  Panel,
  Stat,
} from "@/components/ui";
import {
  useAutomation,
  useBreakSchema,
  useCluster,
  useDemote,
  usePromote,
  useSeedExceptions,
  useShadowRuns,
  useSimulateShadow,
} from "@/lib/api/queries";
import { useTrustStream } from "@/lib/use-trust-stream";
import { hours, percent } from "@/lib/format";

export default function AutomationDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;

  const { data: automation, isLoading, error } = useAutomation(id);
  const { data: shadowRuns } = useShadowRuns(id);
  const { payload, connected } = useTrustStream(id);
  // Resolve the linked workflow so "View workflow" is only offered when it
  // actually leads somewhere. A missing cluster returns 404, which we treat as
  // "no linked workflow" rather than surfacing a broken link.
  const clusterId = automation?.cluster_id ?? "";
  const { data: linkedCluster } = useCluster(clusterId);

  const simulate = useSimulateShadow();
  const promote = usePromote();
  const demote = useDemote();
  const breakSchema = useBreakSchema();
  const seedExceptions = useSeedExceptions();
  const [notice, setNotice] = useState<string | null>(null);

  if (isLoading) return <PageSkeleton rows={2} />;
  if (error) return <div className="p-8"><ErrorNote error={error} /></div>;
  if (!automation) return null;

  // The stream is authoritative when connected: it reflects demotions the
  // moment they happen, without waiting for a refetch.
  const trust = payload?.trust ?? automation.trust;
  const coverage = payload?.coverage ?? automation.coverage;
  const shadowCount = payload?.shadow_run_count ?? automation.shadow_run_count;

  const promoteTitle = trust.can_promote
    ? `Promote to ${trust.next_level}`
    : trust.blockers.join("; ");

  return (
    <div className="pb-16">
      <PageHeader
        back={{ href: "/automations", label: "Automations" }}
        eyebrow="Automation"
        title={automation.name}
        subtitle={automation.description}
        actions={
          <>
            {linkedCluster && (
              <Link className="btn-ghost" href={`/clusters/${automation.cluster_id}`}>
                View workflow
              </Link>
            )}
            <button
              className="btn-ghost"
              disabled={simulate.isPending}
              onClick={() =>
                simulate.mutate(
                  { id, count: 1 },
                  { onSuccess: (r) => setNotice(r.runs[0]?.note ?? null) },
                )
              }
            >
              {simulate.isPending ? "Running…" : "Simulate shadow run"}
            </button>
            <button
              className="btn-ghost"
              disabled={simulate.isPending}
              onClick={() =>
                simulate.mutate(
                  { id, count: 5 },
                  { onSuccess: () => setNotice("5 shadow runs recorded.") },
                )
              }
            >
              ×5
            </button>
            <button
              className="btn-primary"
              disabled={!trust.can_promote || promote.isPending}
              title={promoteTitle}
              onClick={() =>
                promote.mutate({ id }, { onSuccess: (r) => setNotice(r.message) })
              }
            >
              {trust.next_level ? `Promote to ${trust.next_level}` : "At top of ladder"}
            </button>
          </>
        }
      />

      <div className="space-y-6 px-8 pt-6">
        {notice && (
          <div className="panel border-accent-500/30 bg-accent-500/5 px-4 py-2.5">
            <div className="flex items-start justify-between gap-3">
              <p className="text-2xs leading-relaxed text-mist-300">{notice}</p>
              <button className="link shrink-0 text-2xs" onClick={() => setNotice(null)}>
                dismiss
              </button>
            </div>
          </div>
        )}
        {promote.error && <ErrorNote error={promote.error} />}
        {simulate.error && <ErrorNote error={simulate.error} />}

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            label="Trust level"
            value={trust.level}
            tone={
              trust.level === "AUTONOMOUS" ? "good" : trust.level === "ASSIST" ? "warn" : "default"
            }
            hint={trust.next_level ? `Next rung: ${trust.next_level}` : "Top of the ladder"}
          />
          <Stat
            label="Confidence"
            value={percent(trust.confidence, 1)}
            tone={trust.confidence >= trust.threshold ? "good" : "accent"}
            hint={
              trust.runs_in_window < trust.runs_required
                ? `${percent(trust.average_score, 0)} agreement, scaled by a window that is ` +
                  `${trust.runs_in_window}/${trust.runs_required} full — one good run is not confidence`
                : `Rolling agreement over the last ${trust.runs_required} runs`
            }
          />
          <Stat
            label="Replay accuracy"
            value={
              automation.replay_accuracy === null
                ? "—"
                : percent(automation.replay_accuracy, 2)
            }
            hint="Backtested against what the human actually did"
          />
          <Stat
            label="Coverage"
            value={percent(coverage)}
            hint="Share of triggers handled without a human"
          />
        </div>

        <Panel
          title="Trust ladder"
          hint="Promotion is earned by measured agreement, never asserted. Demotion is automatic."
          actions={
            <div className="flex items-center gap-2">
              {connected && (
                <span className="flex items-center gap-1.5 text-2xs text-good-400">
                  <span className="h-1 w-1 animate-pulse rounded-full bg-good-400" />
                  streaming
                </span>
              )}
              <TrustBadge level={trust.level} />
            </div>
          }
        >
          <TrustLadder state={trust} live={connected} />

          <div className="border-t border-ink-700 px-4 py-3">
            {trust.can_promote ? (
              <p className="text-2xs text-good-400">
                Policy satisfied — this automation has earned {trust.next_level}.
              </p>
            ) : (
              <div>
                <p className="eyebrow mb-1.5">Still required before promotion</p>
                <ul className="space-y-1">
                  {trust.blockers.map((blocker) => (
                    <li key={blocker} className="flex items-start gap-2 text-2xs text-mist-400">
                      <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-warn-500" />
                      {blocker}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </Panel>

        <div className="grid gap-6 lg:grid-cols-3">
          <div className="space-y-6 lg:col-span-2">
            <ReplayPanel
              automationId={id}
              storedAccuracy={automation.replay_accuracy}
              storedTotal={automation.replay_total}
            />
            <Panel
              title="Shadow run history"
              hint="Each run pairs what the automation predicted with what the human actually did, field by field."
              actions={
                <span className="tnum text-2xs text-mist-500">{shadowCount} total</span>
              }
            >
              <ShadowRunTable runs={shadowRuns?.items ?? []} />
            </Panel>
            <FlowDefinition automation={automation} />
          </div>

          <div className="space-y-6">
            <Panel title="Demo controls" hint="Every control drives the real code path.">
              <div className="space-y-2.5 px-4 py-4">
                <ControlButton
                  label="Force a critical mismatch"
                  hint="Picks a run the automation genuinely gets wrong. Demotes on the spot."
                  disabled={simulate.isPending}
                  danger
                  onClick={() =>
                    simulate.mutate(
                      { id, count: 1, forceMismatch: true },
                      { onSuccess: (r) => setNotice(r.runs[0]?.note ?? "Critical mismatch recorded.") },
                    )
                  }
                />
                <ControlButton
                  label="Break the source schema"
                  hint="Renames a column across the stored events. Drift detection rediscovers it."
                  disabled={breakSchema.isPending}
                  onClick={() =>
                    breakSchema.mutate(undefined, {
                      onSuccess: (r) => setNotice(r.message),
                    })
                  }
                />
                <ControlButton
                  label="Queue exceptions"
                  hint="Runs the automation until its guard holds, then queues those for review."
                  disabled={seedExceptions.isPending}
                  onClick={() =>
                    seedExceptions.mutate(
                      { id, count: 4 },
                      { onSuccess: (r) => setNotice(r.message) },
                    )
                  }
                />
                <ControlButton
                  label="Demote one rung"
                  hint="Manual override, recorded in the audit trail."
                  disabled={demote.isPending}
                  onClick={() =>
                    demote.mutate({ id }, { onSuccess: (r) => setNotice(r.message) })
                  }
                />
              </div>
            </Panel>

            <Panel title="Review queue">
              <div className="space-y-3 px-4 py-4">
                <QueueRow
                  label="Open exceptions"
                  value={automation.open_exception_count}
                  href="/approvals"
                />
                <QueueRow
                  label="Pending patches"
                  value={automation.pending_patch_count}
                  href="/approvals"
                />
                {automation.rules.length > 0 && (
                  <div className="border-t border-ink-800 pt-3">
                    <p className="eyebrow mb-2">Learned rules</p>
                    <ul className="space-y-2">
                      {automation.rules.map((rule) => (
                        <li key={rule.condition} className="rounded border border-ink-700 bg-ink-850 px-2.5 py-2">
                          <p className="mono text-mist-300">
                            IF {rule.condition} THEN {rule.action}
                          </p>
                          <p className="mt-1 text-2xs text-mist-500">
                            learned from {rule.evidence_count} human decisions
                          </p>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </Panel>

            <Panel title="Audit trail" hint="Every rung change, and why.">
              <ol className="divide-y divide-ink-800">
                {[...automation.trust_history].reverse().map((entry, index) => (
                  <li key={index} className="px-4 py-2.5">
                    <div className="flex items-center gap-2">
                      <TrustBadge level={entry.level as never} />
                    </div>
                    <p className="mt-1.5 text-2xs leading-relaxed text-mist-500">
                      {entry.reason}
                    </p>
                  </li>
                ))}
              </ol>
            </Panel>

            <Panel title="Value">
              <div className="space-y-3 px-4 py-4">
                <div>
                  <div className="flex items-baseline justify-between">
                    <span className="eyebrow">Hours addressed</span>
                    <span className="tnum text-sm font-semibold text-accent-400">
                      {hours(automation.annual_hours)}
                    </span>
                  </div>
                </div>
                <div>
                  <div className="mb-1.5 flex items-baseline justify-between">
                    <span className="eyebrow">Coverage</span>
                    <span className="tnum text-xs font-medium text-mist-200">
                      {percent(coverage)}
                    </span>
                  </div>
                  <Meter value={coverage} tone="good" />
                </div>
                {automation.guards.requires_approval_if && (
                  <div className="border-t border-ink-800 pt-3">
                    <p className="eyebrow mb-1.5">Active guard</p>
                    <p className="mono">{automation.guards.requires_approval_if}</p>
                    <p className="mt-1.5 text-2xs leading-snug text-mist-500">
                      Applies to {automation.guards.irreversible.length} irreversible step(s).
                    </p>
                  </div>
                )}
              </div>
            </Panel>
          </div>
        </div>
      </div>
    </div>
  );
}

function ControlButton({
  label,
  hint,
  onClick,
  disabled,
  danger,
}: {
  label: string;
  hint: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`w-full rounded-md border px-3 py-2.5 text-left transition-colors disabled:opacity-50 ${
        danger
          ? "border-bad-500/30 bg-bad-500/5 hover:bg-bad-500/10"
          : "border-ink-600 bg-ink-850 hover:border-ink-500 hover:bg-ink-800"
      }`}
    >
      <p className={`text-xs font-medium ${danger ? "text-bad-400" : "text-mist-200"}`}>
        {label}
      </p>
      <p className="mt-0.5 text-2xs leading-snug text-mist-500">{hint}</p>
    </button>
  );
}

function QueueRow({ label, value, href }: { label: string; value: number; href: string }) {
  return (
    <Link href={href} className="flex items-center justify-between text-xs">
      <span className="text-mist-400">{label}</span>
      <span className="flex items-center gap-2">
        <span className="tnum font-semibold text-mist-100">{value}</span>
        {value > 0 && <Badge tone="warn">review</Badge>}
      </span>
    </Link>
  );
}
