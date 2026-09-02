"use client";

import Link from "next/link";
import { Badge, Empty, ErrorNote, PageHeader, PageSkeleton, Panel, Stat } from "@/components/ui";
import { useAutomations } from "@/lib/api/queries";
import { hours } from "@/lib/format";
import type { AutomationSummary } from "@/lib/api/types";

/**
 * Automations, in the two states that matter.
 *
 * Previously this page ranked automations along a five-rung trust ladder and
 * counted how many had reached each rung. That was the right model when LOOP
 * executed workflows itself and had to earn the right to act. n8n executes
 * them now, and the only questions left are whether a workflow has been built
 * and whether it is switched on — so those are the only two states shown.
 */
export default function AutomationsPage() {
  const { data, isLoading, error } = useAutomations();

  const all = data?.items ?? [];
  const built = all.filter((a) => a.n8n_workflow_id);
  const proposed = all.filter((a) => !a.n8n_workflow_id);

  return (
    <div className="pb-16">
      <PageHeader
        eyebrow="Automation"
        title="What LOOP has automated"
        subtitle="Each of these was discovered from observed work, approved by you, and built in n8n. Open one to see whether it is running and where it is failing."
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
            <div className="grid gap-3 sm:grid-cols-3">
              <Stat
                label="Built in n8n"
                value={String(built.length)}
                tone={built.length > 0 ? "good" : "default"}
                hint="Approved and handed to n8n to run"
              />
              <Stat
                label="Waiting for approval"
                value={String(proposed.length)}
                tone={proposed.length > 0 ? "warn" : "default"}
                hint="Discovered, not yet approved"
              />
              <Stat
                label="Work they cover"
                value={hours(built.reduce((sum, a) => sum + a.annual_hours, 0))}
                unit="hrs/yr"
                tone="accent"
                hint="Observed manual effort these replace"
              />
            </div>

            <Panel
              title="Built in n8n"
              hint="Open one to see its live run history, read back from n8n."
            >
              {built.length === 0 ? (
                <Empty
                  title="Nothing built yet"
                  hint="Approve a discovered workflow and it gets built in n8n."
                  action={
                    <Link className="btn-primary" href="/approvals">
                      Go to Approval
                    </Link>
                  }
                />
              ) : (
                <ul className="divide-y divide-ink-700">
                  {built.map((automation) => (
                    <Row key={automation.id} automation={automation} approved />
                  ))}
                </ul>
              )}
            </Panel>

            {proposed.length > 0 && (
              <Panel
                title="Waiting for your approval"
                hint="Nothing here has been built or can run."
              >
                <ul className="divide-y divide-ink-700">
                  {proposed.map((automation) => (
                    <Row key={automation.id} automation={automation} approved={false} />
                  ))}
                </ul>
              </Panel>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Row({
  automation,
  approved,
}: {
  automation: AutomationSummary;
  approved: boolean;
}) {
  return (
    <li className="row-interactive">
      <Link href={`/automations/${automation.id}`} className="block px-4 py-3.5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-medium text-mist-100">{automation.name}</h3>
              <Badge tone={approved ? "good" : "warn"}>
                {approved ? "In n8n" : "Needs approval"}
              </Badge>
            </div>
            <p className="mt-1.5 max-w-2xl text-2xs leading-relaxed text-mist-500">
              {automation.description}
            </p>
            <p className="tnum mt-2 text-2xs text-mist-600">
              {automation.step_count} steps
            </p>
          </div>
          <div className="shrink-0 text-right">
            <p className="eyebrow">Covers</p>
            <p className="metric mt-1 text-lg text-accent-400">
              {hours(automation.annual_hours)}
              <span className="ml-1 text-2xs font-normal tracking-normal text-mist-500">
                hrs/yr
              </span>
            </p>
          </div>
        </div>
      </Link>
    </li>
  );
}
