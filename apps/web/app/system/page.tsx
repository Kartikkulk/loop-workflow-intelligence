"use client";

import { useState } from "react";
import { Badge, ErrorNote, PageHeader, PageSkeleton, Panel, Stat } from "@/components/ui";
import { useResetDemo, useSystem } from "@/lib/api/queries";

export default function SystemPage() {
  const { data, isLoading, error } = useSystem();
  const reset = useResetDemo();
  const [notice, setNotice] = useState<string | null>(null);

  if (isLoading) return <PageSkeleton rows={4} />;
  if (error) return <div className="p-8"><ErrorNote error={error} /></div>;
  if (!data) return null;

  return (
    <div className="pb-16">
      <PageHeader
        eyebrow="System"
        title="Connectors and configuration"
        subtitle="What is wired to what, and every threshold the detection and trust policies use. All of it is environment-configurable."
        actions={
          <button
            className="btn-ghost"
            disabled={reset.isPending}
            onClick={() =>
              reset.mutate(undefined, { onSuccess: (r) => setNotice(r.message) })
            }
          >
            {reset.isPending ? "Resetting…" : "Reset demo state"}
          </button>
        }
      />

      <div className="space-y-6 px-8 pt-6">
        {notice && (
          <div className="panel border-good-500/30 bg-good-500/5 px-4 py-2.5">
            <p className="text-2xs leading-relaxed text-mist-300">{notice}</p>
          </div>
        )}
        {reset.error && <ErrorNote error={reset.error} />}

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Events" value={data.event_count.toLocaleString()} />
          <Stat label="Workflows" value={String(data.cluster_count)} />
          <Stat label="Automations" value={String(data.automation_count)} />
          <Stat
            label="Side effects"
            value={data.mock_connectors ? "Mocked" : "Live"}
            tone={data.mock_connectors ? "good" : "bad"}
            hint={
              data.mock_connectors
                ? "No connector can touch a real system"
                : "Live connectors are active"
            }
          />
        </div>

        <Panel
          title="Connectors"
          hint="One interface, two implementations per system. Replay and shadow force the mock regardless of configuration, so those modes can never produce a side effect."
        >
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-ink-700 text-left">
                  <th className="px-4 py-2 font-medium text-mist-500">Connector</th>
                  <th className="px-4 py-2 font-medium text-mist-500">Active</th>
                  <th className="px-4 py-2 font-medium text-mist-500">Live API</th>
                  <th className="px-4 py-2 font-medium text-mist-500">Credentials needed</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-800">
                {data.connectors.map((connector) => (
                  <tr key={connector.name}>
                    <td className="px-4 py-2.5 font-medium text-mist-200">{connector.name}</td>
                    <td className="px-4 py-2.5">
                      <Badge tone={connector.active === "mock" ? "good" : "warn"}>
                        {connector.active}
                      </Badge>
                    </td>
                    <td className="px-4 py-2.5 text-2xs text-mist-400">{connector.api}</td>
                    <td className="px-4 py-2.5">
                      {connector.required_credentials.length === 0 ? (
                        <span className="text-2xs text-mist-600">none</span>
                      ) : (
                        <div className="flex flex-wrap gap-1">
                          {connector.required_credentials.map((credential) => (
                            <span key={credential} className="mono">
                              {credential}
                            </span>
                          ))}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        <div className="grid gap-6 lg:grid-cols-2">
          <Panel title="Language model" hint="Used for structured generation via tool use.">
            <dl className="divide-y divide-ink-800">
              <Row label="Status" value={data.llm_available ? "connected" : "not configured"} />
              <Row label="Model" value={data.llm_model} />
              <Row label="Calls" value={String(data.llm_calls)} />
              <Row
                label="Deterministic fallbacks"
                value={String(data.llm_fallbacks)}
                hint="Every AI feature has a heuristic fallback, so the product runs with no API key"
              />
              <Row
                label="Estimated spend"
                value={`$${data.llm_estimated_cost_usd.toFixed(4)}`}
              />
            </dl>
          </Panel>

          <Panel title="Configuration" hint="Every value below is read from the environment.">
            <dl className="max-h-96 divide-y divide-ink-800 overflow-auto">
              {Object.entries(data.settings).map(([key, value]) => (
                <Row key={key} label={key.replace(/_/g, " ")} value={String(value)} />
              ))}
            </dl>
          </Panel>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex items-start justify-between gap-4 px-4 py-2.5">
      <div className="min-w-0">
        <dt className="text-2xs text-mist-400">{label}</dt>
        {hint && <dd className="mt-0.5 text-2xs leading-snug text-mist-600">{hint}</dd>}
      </div>
      <dd className="tnum shrink-0 font-mono text-2xs text-mist-200">{value}</dd>
    </div>
  );
}
