"use client";

import { useState } from "react";
import { Badge, ErrorNote, Panel } from "@/components/ui";
import { useDryRun, useGeneratedCode, useValidateAutomation } from "@/lib/api/queries";
import type { ExecutionPlan } from "@/lib/api/types";

/**
 * Build → validate → dry run → approve, as four visibly separate steps.
 *
 * They are separate because they are separate decisions. Reviewing what LOOP
 * intends to do is not the same act as permitting it to happen, and collapsing
 * them into one button would mean the only moment a person is asked to think is
 * the moment they are also asked to consent. The approve control stays disabled
 * until validation has passed and a dry run has been seen, so "approved" always
 * means somebody watched it not touch anything first.
 */

const DESCRIPTIONS: Record<string, string> = {
  n8n: "n8n runs it. It already holds the connectors and the credentials, so approving means importing the workflow and picking accounts.",
  python:
    "A standalone Python script runs it. Standard library only — nothing to install, and no credentials for the local steps.",
  playwright:
    "A real browser drives it. The only option when a system has no usable API, and the slowest and most fragile of the three.",
  hybrid:
    "Two executors. A browser reads from the system that has no API; an API call does the writing. Browser automation stays confined to the half that needs it.",
};

export function ExecutionPlanPanel({
  id,
  plan,
  guard,
}: {
  id: string;
  plan: ExecutionPlan | null;
  guard?: string | null;
}) {
  const [showCode, setShowCode] = useState(false);
  const hasSource = ["python", "playwright", "hybrid"].includes(plan?.method ?? "");
  const code = useGeneratedCode(id, showCode && hasSource);
  const validation = useValidateAutomation(id);
  const dryRun = useDryRun(id);

  if (!plan || !plan.method) return null;

  const validated = validation.data?.ok === true;
  const dryRunSeen = Boolean(dryRun.data);
  const readyToApprove = validated && dryRunSeen;

  return (
    <Panel
      title="How it will run"
      hint="Chosen from the systems its steps touch, not from configuration."
    >
      <div className="space-y-5 px-4 py-4">
        {/* ── the recommendation, and why ─────────────────────────────── */}
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <Badge tone="accent">{plan.method}</Badge>
            <span className="text-2xs text-mist-500">
              chosen by {plan.decided_by === "llm" ? "the local model" : "connector rules"} ·
              confidence {plan.confidence.toFixed(2)}
            </span>
            {hasSource && (
              <button
                className="link ml-auto text-2xs"
                onClick={() => setShowCode((open) => !open)}
                type="button"
              >
                {showCode ? "Hide the code" : "View code"}
              </button>
            )}
          </div>
          <p className="mt-2 text-2xs leading-relaxed text-mist-400">
            {DESCRIPTIONS[plan.method] ?? ""}
          </p>
          <p className="mt-1 text-2xs leading-relaxed text-mist-500">{plan.rationale}</p>

          {plan.factors.length > 0 && (
            <ul className="mt-3 space-y-1 border-l border-ink-600 pl-3">
              {plan.factors.map((factor) => (
                <li key={factor} className="text-2xs leading-relaxed text-mist-500">
                  {factor}
                </li>
              ))}
            </ul>
          )}

          {plan.alternative_method && (
            <div className="mt-3 border-l-2 border-warn-500/40 pl-3">
              <p className="text-2xs font-medium text-warn-400">
                The connector rules would have chosen {plan.alternative_method}
              </p>
              <p className="mt-1 text-2xs leading-relaxed text-mist-500">
                {plan.alternative_rationale} Both are workable, so this is shown rather than
                settled silently.
              </p>
            </div>
          )}
        </div>

        {showCode && code.isLoading && <p className="text-2xs text-mist-500">Generating…</p>}
        {showCode && code.error && <ErrorNote error={code.error} />}
        {showCode && code.data && (
          <div className="space-y-2">
            <div className="flex flex-wrap items-baseline gap-3">
              <span className="mono text-2xs text-mist-300">{code.data.filename}</span>
              <span className="text-2xs text-mist-500">{code.data.line_count} lines</span>
            </div>
            {code.data.caveats.length > 0 && (
              <ul className="space-y-1">
                {code.data.caveats.map((line) => (
                  <li key={line} className="text-2xs leading-relaxed text-warn-400">
                    · {line}
                  </li>
                ))}
              </ul>
            )}
            <pre className="mono max-h-[26rem] overflow-auto rounded border border-mist-800 bg-black/30 p-3 text-2xs leading-relaxed text-mist-300">
              {code.data.source}
            </pre>
          </div>
        )}

        {/* ── validate ────────────────────────────────────────────────── */}
        <div className="border-t border-ink-700 pt-4">
          <div className="flex items-center gap-3">
            <span className="text-2xs font-medium text-mist-300">1 · Validate</span>
            <button
              className="btn-ghost ml-auto"
              disabled={validation.isPending}
              onClick={() => validation.mutate()}
              type="button"
            >
              {validation.isPending ? "Checking…" : "Run checks"}
            </button>
          </div>
          <p className="mt-1 text-2xs leading-relaxed text-mist-500">
            Every step, connector and guard is checked against the activity that was actually
            observed. A step naming a system nobody used is a fabrication, however reasonable
            it looks.
          </p>
          {validation.error && <ErrorNote error={validation.error} />}
          {validation.data && (
            <div className="mt-3 space-y-1">
              {validation.data.passed.map((check) => (
                <p key={check} className="text-2xs text-good-400">
                  ✓ {check}
                </p>
              ))}
              {validation.data.findings.map((finding) => (
                <p
                  key={finding.check + finding.detail}
                  className={finding.blocking ? "text-2xs text-bad-400" : "text-2xs text-warn-400"}
                >
                  {finding.blocking ? "✕" : "!"} {finding.detail}
                </p>
              ))}
              {!validation.data.ok && (
                <p className="mt-2 text-2xs font-medium text-bad-400">
                  Automation needs repair — {validation.data.blocking_count} blocking issue
                  {validation.data.blocking_count === 1 ? "" : "s"}. It cannot be approved
                  until these are fixed.
                </p>
              )}
            </div>
          )}
        </div>

        {/* ── dry run ─────────────────────────────────────────────────── */}
        <div className="border-t border-ink-700 pt-4">
          <div className="flex items-center gap-3">
            <span className="text-2xs font-medium text-mist-300">2 · Dry run</span>
            <button
              className="btn-ghost ml-auto"
              disabled={dryRun.isPending || !validated}
              onClick={() => dryRun.mutate()}
              type="button"
            >
              {dryRun.isPending ? "Running…" : "Run without side effects"}
            </button>
          </div>
          <p className="mt-1 text-2xs leading-relaxed text-mist-500">
            The same engine a live run uses, with every connector forced to its mock by the
            engine itself. Nothing outside this machine is touched.
          </p>
          {dryRun.error && <ErrorNote error={dryRun.error} />}
          {dryRun.data && (
            <div className="mt-3 space-y-1">
              {dryRun.data.steps.map((step) => (
                <p key={step.step_id} className="mono text-2xs text-mist-400">
                  <span className={step.status === "ok" ? "text-good-400" : "text-bad-400"}>
                    {step.status === "ok" ? "✓" : "✕"}
                  </span>{" "}
                  {step.connector}:{step.action}
                  {Object.keys(step.outputs).length > 0 && (
                    <span className="text-mist-600">
                      {"  "}
                      {Object.entries(step.outputs)
                        .slice(0, 2)
                        .map(([k, v]) => `${k}=${String(v)}`)
                        .join(", ")}
                    </span>
                  )}
                  {step.error && <span className="text-bad-400"> — {step.error}</span>}
                </p>
              ))}
              {dryRun.data.held_by_guard && (
                <p className="mt-2 text-2xs text-warn-400">
                  Held by the guard: {dryRun.data.guard_reason}
                </p>
              )}
              <p className="mt-2 text-2xs text-good-400">
                ⚠ Nothing was created. Side effects performed:{" "}
                {dryRun.data.side_effects_performed}.
              </p>
            </div>
          )}
        </div>

        {/* ── approve ─────────────────────────────────────────────────── */}
        <div className="border-t border-ink-700 pt-4">
          <p className="text-2xs font-medium text-mist-300">3 · Approve</p>
          <p className="mt-1 text-2xs leading-relaxed text-mist-500">
            Approval is permission to act, not agreement that the plan looks right — that was
            step 1. Until it is given, this automation has never touched a real system.
          </p>
          {guard && (
            <p className="mt-2 text-2xs leading-relaxed text-mist-400">
              If approved, it will still stop and ask a person whenever{" "}
              <span className="mono">{guard}</span>.
            </p>
          )}
          <p className="mt-3 text-2xs text-mist-500">
            {readyToApprove
              ? "Checks passed and a dry run has been seen. Approve from the Approvals screen."
              : "Run the checks and a dry run first — the approve control stays closed until both have been seen."}
          </p>
        </div>
      </div>
    </Panel>
  );
}
