"use client";

import Link from "next/link";
import { FlowDefinition } from "@/components/flow-definition";
import { Badge, ErrorNote, PageHeader, PageSkeleton, Panel } from "@/components/ui";
import { useAutomation, useN8nRuns } from "@/lib/api/queries";
import { hours, relativeTime } from "@/lib/format";
import { useParams } from "next/navigation";

/**
 * One automation: what it does, whether it is working, and what it saves.
 *
 * This page used to carry a promote button, a five-rung ladder, practice runs,
 * a replay backtest and a row of demo controls. All of it was machinery from
 * before n8n became the execution engine — a person looking at this screen
 * wants to know whether the thing is running and where to fix it if not, and
 * every extra control was another thing to explain first.
 *
 * The trust mechanism still exists in the backend and still demotes
 * automatically. It is simply not something anyone has to read a diagram to
 * understand any more.
 */
export default function AutomationDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { data: automation, isLoading, error } = useAutomation(id);

  if (isLoading) return <PageSkeleton rows={3} />;
  if (error) return <div className="p-8"><ErrorNote error={error} /></div>;
  if (!automation) return null;

  const approved = Boolean(automation.n8n_workflow_id);

  return (
    <div className="pb-16">
      <div className="px-8 pt-6">
        <Link className="link text-2xs" href="/automations">
          ← Automations
        </Link>
      </div>

      <PageHeader
        eyebrow="Automation"
        title={automation.name}
        subtitle={automation.description}
      />

      <div className="space-y-6 px-8 pt-6">
        <div className="flex flex-wrap items-center gap-3">
          <Badge tone={approved ? "good" : "warn"}>
            {approved ? "Built in n8n" : "Not approved yet"}
          </Badge>
          <span className="text-2xs text-mist-500">
            {automation.step_count} steps · found in {hours(automation.annual_hours)} hrs/yr of
            observed work
          </span>
          <Link
            className="link ml-auto text-2xs"
            href={`/clusters/${automation.cluster_id}`}
          >
            See what LOOP observed →
          </Link>
        </div>

        <N8nPanel id={id} workflowId={automation.n8n_workflow_id} />

        <Panel
          title="What it does"
          hint="Built from the steps LOOP watched people repeat, in the order they did them."
        >
          <FlowDefinition automation={automation} />
        </Panel>

        {automation.guards.requires_approval_if && (
          <Panel
            title="When it stops and asks"
            hint="Steps that cannot be undone are held for a person when this is true."
          >
            <div className="px-4 py-4">
              <p className="mono">{automation.guards.requires_approval_if}</p>
              <p className="mt-2 text-2xs leading-relaxed text-mist-500">
                Applies to {automation.guards.irreversible.length} step
                {automation.guards.irreversible.length === 1 ? "" : "s"} that reach outside
                this machine.
              </p>
            </div>
          </Panel>
        )}
      </div>
    </div>
  );
}


function N8nPanel({ id, workflowId }: { id: string; workflowId: string }) {
  const runs = useN8nRuns(id, Boolean(workflowId));

  if (!workflowId) {
    return (
      <Panel
        title="Running in n8n"
        hint="Approving a workflow builds it in n8n, which is what actually carries it out."
      >
        <div className="px-4 py-6 text-center">
          <p className="text-xs text-mist-400">Not approved yet.</p>
          <p className="mx-auto mt-1.5 max-w-sm text-2xs leading-relaxed text-mist-500">
            Approve it on the Approvals screen and it gets built in n8n, switched
            off, for you to wire up.
          </p>
        </div>
      </Panel>
    );
  }

  const data = runs.data;
  const failing = (data?.failed ?? 0) > 0;

  return (
    <Panel
      title="Running in n8n"
      hint="Read back from n8n itself, so a broken node shows up here rather than only there."
      actions={
        data?.configure_url ? (
          <a
            className="link text-2xs"
            href={data.configure_url}
            target="_blank"
            rel="noreferrer"
          >
            Open in n8n →
          </a>
        ) : undefined
      }
    >
      <div className="space-y-4 px-4 py-4">
        <div className="flex flex-wrap items-center gap-3">
          <Badge tone={data?.active ? "good" : "warn"}>
            {data?.active ? "Switched on" : "Switched off"}
          </Badge>
          {data && data.total > 0 && (
            <>
              <span className="tnum text-2xs text-good-400">{data.succeeded} passed</span>
              {failing && (
                <span className="tnum text-2xs text-bad-400">{data.failed} failed</span>
              )}
            </>
          )}
          {runs.isLoading && <span className="text-2xs text-mist-500">checking…</span>}
        </div>

        {data?.message && (
          <p className={`text-2xs leading-relaxed ${failing ? "text-warn-300" : "text-mist-400"}`}>
            {data.message}
          </p>
        )}

        {data && data.items.length > 0 && (
          <ul className="divide-y divide-ink-800">
            {data.items.slice(0, 8).map((run) => {
              const bad = ["error", "crashed", "failed"].includes(run.status);
              return (
                <li key={run.id} className="flex items-start gap-3 py-2">
                  <span
                    className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${
                      bad ? "bg-bad-400" : run.status === "success" ? "bg-good-400" : "bg-mist-600"
                    }`}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-baseline gap-x-3">
                      <span
                        className={`text-2xs font-medium ${bad ? "text-bad-400" : "text-mist-200"}`}
                      >
                        {run.status}
                      </span>
                      {run.failed_node && (
                        <span className="text-2xs text-mist-400">
                          stopped at <span className="text-mist-200">{run.failed_node}</span>
                        </span>
                      )}
                      {run.started_at && (
                        <span className="tnum text-2xs text-mist-600">
                          {relativeTime(run.started_at)}
                        </span>
                      )}
                    </div>
                    {run.error && (
                      <p className="mt-1 text-2xs leading-relaxed text-mist-500">{run.error}</p>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Panel>
  );
}
