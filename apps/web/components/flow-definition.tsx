"use client";

import { Badge, Panel } from "./ui";
import type { AutomationDetail } from "@/lib/api/types";

/**
 * The generated flow, rendered as configuration rather than as JSON.
 *
 * `depends_on` is given its own column deliberately: it is what self-healing
 * watches, so a step with no declared dependencies is unmaintainable and should
 * be visibly so.
 */
export function FlowDefinition({ automation }: { automation: AutomationDetail }) {
  const irreversible = new Set(automation.guards.irreversible);

  return (
    <Panel
      title="Flow definition"
      hint="Generated from the observed workflow. Every step declares the fields it reads, which is how drift is detected."
      actions={<Badge tone="neutral">via {automation.generated_by}</Badge>}
    >
      <div className="border-b border-ink-800 px-4 py-3">
        <p className="eyebrow mb-1.5">Trigger</p>
        <p className="text-xs text-mist-200">
          <span className="mono">{automation.trigger.type ?? "manual"}</span>
          {automation.trigger.filter && Object.keys(automation.trigger.filter).length > 0 && (
            <span className="ml-2 text-mist-500">
              where{" "}
              {Object.entries(automation.trigger.filter)
                .map(([key, value]) => `${key} = ${String(value)}`)
                .join(", ")}
            </span>
          )}
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-2xs">
          <thead>
            <tr className="border-b border-ink-800 text-left">
              <th className="px-4 py-2 font-medium text-mist-600">Step</th>
              <th className="px-4 py-2 font-medium text-mist-600">Action</th>
              <th className="px-4 py-2 font-medium text-mist-600">Reads (depends_on)</th>
              <th className="px-4 py-2 font-medium text-mist-600">Produces</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-800">
            {automation.steps.map((step, index) => (
              <tr key={`${step.id}-${index}`}>
                <td className="px-4 py-2 align-top">
                  <span className="mono">{step.id}</span>
                  {irreversible.has(step.id) && (
                    <span className="ml-1.5 rounded border border-warn-500/40 bg-warn-500/10 px-1 py-0.5 text-[9px] font-semibold text-warn-400">
                      IRREVERSIBLE
                    </span>
                  )}
                </td>
                <td className="px-4 py-2 align-top">
                  <span className="text-mist-200">
                    {step.type} <span className="text-mist-500">via</span> {step.connector}
                  </span>
                  {step.description && (
                    <p className="mt-0.5 text-mist-600">{step.description}</p>
                  )}
                </td>
                <td className="px-4 py-2 align-top">
                  {step.depends_on.length === 0 ? (
                    <span className="text-mist-600">— trigger data</span>
                  ) : (
                    <div className="flex flex-wrap gap-1">
                      {step.depends_on.map((field) => (
                        <span
                          key={field}
                          className="rounded border border-accent-500/30 bg-accent-500/10 px-1.5 py-0.5 font-mono text-accent-300"
                        >
                          {field}
                        </span>
                      ))}
                    </div>
                  )}
                </td>
                <td className="px-4 py-2 align-top">
                  <div className="flex flex-wrap gap-1">
                    {step.outputs.map((field) => (
                      <span
                        key={field}
                        className="rounded border border-ink-600 bg-ink-800 px-1.5 py-0.5 font-mono text-mist-400"
                      >
                        {field}
                      </span>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {automation.guards.requires_approval_if && (
        <div className="border-t border-ink-800 px-4 py-3">
          <p className="eyebrow mb-1.5">Guard</p>
          <p className="text-2xs leading-relaxed text-mist-400">
            When <span className="mono">{automation.guards.requires_approval_if}</span>, any
            irreversible step is held for a human. Guards are evaluated by a restricted
            comparator, never by <span className="mono">eval</span> — a flow definition is partly
            model-generated, so it is untrusted input.
          </p>
        </div>
      )}
    </Panel>
  );
}
