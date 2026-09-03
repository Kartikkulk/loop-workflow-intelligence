"use client";

import Link from "next/link";
import { Badge, ErrorNote, PageHeader, PageSkeleton, Panel } from "@/components/ui";
import { useSystem } from "@/lib/api/queries";

/**
 * One place for the things you set up once.
 *
 * This replaces the old System screen, which read like a status board for
 * whoever built the thing rather than a settings page. What survives is only
 * what someone might act on: whether side effects are real, whether the model
 * is reachable, and what the detection thresholds are.
 */
export default function SettingsPage() {
  const { data, isLoading, error } = useSystem();

  if (isLoading) return <PageSkeleton rows={3} />;
  if (error) return <div className="p-8"><ErrorNote error={error} /></div>;
  if (!data) return null;

  return (
    <div className="pb-16">
      <PageHeader
        eyebrow="Settings"
        title="How Kriyā AI is set up"
        subtitle="Everything here is read from the running configuration, so it is what is actually in force rather than what was intended."
      />

      <div className="space-y-6 px-8 pt-6">
        <Panel
          title="Safety"
          hint="The two switches that decide whether anything can touch a real system."
        >
          <div className="divide-y divide-ink-800">
            <Row
              label="Side effects"
              value={data.mock_connectors ? "Pretend only" : "Real"}
              tone={data.mock_connectors ? "good" : "warn"}
              detail={
                data.mock_connectors
                  ? "Every connector is mocked. Nothing can reach a real account."
                  : "Live connectors are enabled. Approved automations can act for real."
              }
            />
            <Row
              label="Language model"
              value={data.llm_available ? data.llm_model : "Not reachable"}
              tone={data.llm_available ? "good" : "default"}
              detail={
                data.llm_available
                  ? "Used to name and explain workflows. It never executes anything."
                  : "Kriyā AI falls back to deterministic naming and scoring. Nothing breaks; the wording is plainer."
              }
            />
          </div>
        </Panel>

        <Panel title="What Kriyā AI has stored">
          <div className="grid gap-4 px-4 py-4 sm:grid-cols-3">
            <Metric label="Activity events" value={data.event_count.toLocaleString()} />
            <Metric label="Workflows found" value={String(data.cluster_count)} />
            <Metric label="Automations" value={String(data.automation_count)} />
          </div>
          <div className="border-t border-ink-800 px-4 py-3">
            <Link className="link text-2xs" href="/activity">
              See the events themselves →
            </Link>
          </div>
        </Panel>

        <Panel
          title="Detection thresholds"
          hint="Chosen by measurement and documented in apps/api/app/config.py, next to the reason for each value."
        >
          <div className="divide-y divide-ink-800">
            {Object.entries(data.settings).map(([key, value]) => (
              <div key={key} className="flex items-baseline justify-between gap-4 px-4 py-2">
                <span className="text-2xs text-mist-400">{key.replace(/_/g, " ")}</span>
                <span className="tnum text-2xs font-medium text-mist-200">{String(value)}</span>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="Connectors" hint="Each system has a real implementation and a safe pretend one.">
          <div className="divide-y divide-ink-800">
            {data.connectors.map((connector) => (
              <div
                key={connector.name}
                className="flex flex-wrap items-baseline justify-between gap-3 px-4 py-2.5"
              >
                <div className="min-w-0">
                  <span className="text-2xs font-medium text-mist-200">{connector.name}</span>
                  <p className="mt-0.5 text-2xs text-mist-500">{connector.api}</p>
                </div>
                <Badge tone={connector.active === "mock" ? "neutral" : "warn"}>
                  {connector.active === "mock" ? "pretend" : "live"}
                </Badge>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail: string;
  tone: "good" | "warn" | "default";
}) {
  const colour =
    tone === "good" ? "text-good-400" : tone === "warn" ? "text-warn-400" : "text-mist-300";
  return (
    <div className="flex flex-wrap items-start justify-between gap-4 px-4 py-3">
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium text-mist-100">{label}</p>
        <p className="mt-1 max-w-xl text-2xs leading-relaxed text-mist-500">{detail}</p>
      </div>
      <span className={`shrink-0 text-xs font-semibold ${colour}`}>{value}</span>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="eyebrow">{label}</p>
      <p className="metric mt-1.5 text-2xl text-mist-100">{value}</p>
    </div>
  );
}
