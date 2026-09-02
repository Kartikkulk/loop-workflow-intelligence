"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, Empty, ErrorNote, Meter, PageHeader, PageSkeleton, Panel, Stat } from "@/components/ui";
import { StateStripe } from "@/components/viz";
import {
  useApplyPatch,
  useApproveToN8n,
  useAutomations,
  useExceptions,
  usePatches,
  useRejectPatch,
  useResolveException,
} from "@/lib/api/queries";
import { formatFieldValue, hours, percent, relativeTime } from "@/lib/format";
import { isAwaitingApproval } from "@/lib/api/types";
import type { AutomationSummary, ExceptionCase, Patch } from "@/lib/api/types";

const DECISIONS = ["route_to_manager", "approve", "reject", "hold_for_clarification"];

/**
 * Everything waiting on a person, in one place.
 *
 * Three different things need a human decision — a workflow proposed as an
 * automation, a change to a running automation, and a single case the
 * automation was not confident about — and splitting them across screens meant
 * nobody could answer "what is waiting on me?" without visiting three.
 */
export default function ApprovalsPage() {
  const automations = useAutomations();
  const exceptions = useExceptions();
  const patches = usePatches();
  const [notice, setNotice] = useState<string | null>(null);

  if (automations.isLoading || exceptions.isLoading || patches.isLoading) {
    return <PageSkeleton rows={3} />;
  }

  const error = automations.error ?? exceptions.error ?? patches.error;
  if (error) return <div className="p-8"><ErrorNote error={error} /></div>;

  // Proposed means: not yet approved. Once a workflow has been exported to n8n
  // the decision has been made, so it belongs on Automations rather than
  // sitting here implying it still needs a yes. isAwaitingApproval is the one
  // definition of that, shared with the nav badge and the automations page.
  const proposed = (automations.data?.items ?? []).filter(isAwaitingApproval);
  const openExceptions = (exceptions.data?.items ?? []).filter((e) => e.status === "open");
  const openPatches = (patches.data?.items ?? []).filter((p) => p.status === "proposed");

  const total = proposed.length + openExceptions.length + openPatches.length;
  const potentialHours = proposed.reduce((sum, a) => sum + a.annual_hours, 0);

  return (
    <div className="pb-16">
      <PageHeader
        eyebrow="Step 3 of 4"
        title="Waiting on your decision"
        subtitle="Nothing here is running. LOOP has built these from the work it observed, and each one needs a person to say yes before it can act — that is the whole safety model, not a formality."
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

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            label="Awaiting you"
            value={String(total)}
            tone={total > 0 ? "warn" : "good"}
            hint={total > 0 ? "Nothing acts until you decide" : "Everything is decided"}
          />
          <Stat
            label="Workflows proposed"
            value={String(proposed.length)}
            hint="Built from observed work, not yet approved to run"
          />
          <Stat
            label="Hours they would cover"
            value={hours(potentialHours)}
            unit="hrs/yr"
            tone="accent"
            hint="If every proposal here were approved"
          />
          <Stat
            label="Changes and cases"
            value={String(openPatches.length + openExceptions.length)}
            hint="Fixes to running automations, and cases they escalated"
          />
        </div>

        {/* ── 1. workflows proposed ─────────────────────────────────── */}
        <Panel
          title="Workflows proposed for automation"
          hint="LOOP built each of these from a repetitive pattern it observed. Approving builds it in n8n — switched off, with no accounts attached — and hands you the link to finish wiring it up."
        >
          {proposed.length === 0 ? (
            <Empty
              title="No workflows waiting"
              hint="Everything LOOP proposed has been decided. New proposals appear here as it observes more work."
              action={
                <Link className="btn-ghost" href="/">
                  See what was discovered
                </Link>
              }
            />
          ) : (
            <ul className="divide-y divide-ink-700">
              {proposed.map((automation) => (
                <ProposedRow key={automation.id} automation={automation} />
              ))}
            </ul>
          )}
        </Panel>

        {/* ── 2. changes to running automations ─────────────────────── */}
        <Panel
          title="Changes to approve"
          hint="A source system changed, or LOOP learned a rule from how you resolved past cases. Both edit a flow definition, so both need signing off."
        >
          {openPatches.length === 0 ? (
            <Empty
              title="No changes proposed"
              hint="LOOP proposes a change when a field stops resolving, or when three similar cases were resolved the same way."
            />
          ) : (
            <ul className="divide-y divide-ink-700">
              {openPatches.map((patch) => (
                <PatchRow key={patch.id} patch={patch} onNotice={setNotice} />
              ))}
            </ul>
          )}
        </Panel>

        {/* ── 3. individual cases ───────────────────────────────────── */}
        <Panel
          title="Cases the automation escalated"
          hint="Each decision you make here is training data. Three matching decisions on the same kind of input and LOOP proposes the rule that would have handled them."
        >
          {openExceptions.length === 0 ? (
            <Empty
              title="Nothing escalated"
              hint="An automation escalates when a guard holds it, or when it is not confident enough to proceed."
            />
          ) : (
            <ul className="divide-y divide-ink-700">
              {openExceptions.map((item) => (
                <ExceptionRow key={item.id} item={item} onNotice={setNotice} />
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}

function ProposedRow({ automation }: { automation: AutomationSummary }) {
  const approve = useApproveToN8n();
  const result = approve.data;

  return (
    <li>
      <Link href={`/automations/${automation.id}`} className="row-interactive flex gap-3 px-4 py-4">
        <StateStripe state="warn" />

        <div className="flex min-w-0 flex-1 flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-medium text-mist-100">{automation.name}</h3>
            </div>
            <p className="mt-1.5 max-w-2xl text-2xs leading-relaxed text-mist-500">
              {automation.description}
            </p>
            <div className="tnum mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-mist-500">
              <span>{automation.step_count} steps</span>
              {automation.replay_accuracy !== null && (
                <span>got it right {percent(automation.replay_accuracy, 1)} of the time on past work</span>
              )}
              {automation.critical_mismatch_count > 0 && (
                <span className="text-bad-400">
                  {automation.critical_mismatch_count} serious disagreement
                  {automation.critical_mismatch_count === 1 ? "" : "s"}
                </span>
              )}
            </div>
          </div>

          <div className="flex shrink-0 items-start gap-6">
            <div className="w-28">
              <p className="eyebrow">Confidence</p>
              <p className="metric mt-1 text-lg text-mist-100">
                {percent(automation.confidence, 0)}
              </p>
              <div className="mt-2">
                <Meter
                  value={automation.confidence}
                  tone={automation.critical_mismatch_count > 0 ? "bad" : "accent"}
                />
              </div>
            </div>
            <div className="w-24 text-right">
              <p className="eyebrow whitespace-nowrap">Covers</p>
              <p className="metric mt-1 text-lg text-accent-400">
                {hours(automation.annual_hours)}
                <span className="ml-1 text-2xs font-normal tracking-normal text-mist-500">
                  hrs/yr
                </span>
              </p>
            </div>
          </div>
        </div>
      </Link>

      {/* ── the decision ───────────────────────────────────────────────
          Approving creates the workflow in n8n, switched off and with no
          accounts attached. That split is the point: LOOP decides the work is
          worth automating, and a person decides what it may connect to. */}
      <div className="flex flex-wrap items-center gap-3 border-t border-ink-800 px-4 py-3">
        <button
          className="btn-primary"
          disabled={approve.isPending || Boolean(result?.ok)}
          onClick={() => approve.mutate({ id: automation.id, schedule: "hourly" })}
        >
          {approve.isPending
            ? "Creating in n8n…"
            : result?.ok
              ? "Approved"
              : "Approve — build it in n8n"}
        </button>

        {result?.ok && result.configure_url && (
          <>
            <a
              className="btn-ghost"
              href={result.configure_url}
              target="_blank"
              rel="noreferrer"
            >
              Configure the accounts in n8n →
            </a>
            <Link className="link text-2xs" href={`/automations/${automation.id}`}>
              Watch how it gets on
            </Link>
          </>
        )}

        {!result && (
          <span className="text-2xs text-mist-500">
            It arrives switched off. You choose which accounts it may use.
          </span>
        )}

        {result && !result.ok && (
          <span className="text-2xs leading-relaxed text-warn-400">{result.message}</span>
        )}

        {result?.ok && (
          <span className="text-2xs leading-relaxed text-mist-400">{result.message}</span>
        )}
      </div>

      {approve.error && (
        <div className="px-4 pb-3">
          <ErrorNote error={approve.error} />
        </div>
      )}
    </li>
  );
}

function PatchRow({ patch, onNotice }: { patch: Patch; onNotice: (m: string) => void }) {
  const apply = useApplyPatch();
  const reject = useRejectPatch();

  return (
    <li className="px-4 py-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={patch.kind === "rule" ? "accent" : "warn"}>
              {patch.kind === "rule" ? "Learned rule" : "Source changed"}
            </Badge>
            <span className="text-2xs text-mist-500">{patch.automation_name}</span>
          </div>

          <div className="mt-2.5 rounded-md border border-ink-700 bg-ink-950/60 px-3 py-2.5">
            {patch.kind === "rule" ? (
              <p className="mono text-good-400">
                + IF {patch.rule?.condition} THEN {patch.rule?.action}
              </p>
            ) : (
              <>
                <p className="mono text-bad-400">− reads &quot;{patch.from_value}&quot;</p>
                <p className="mono text-good-400">+ reads &quot;{patch.to_value}&quot;</p>
              </>
            )}
          </div>

          <p className="mt-2 max-w-3xl text-2xs leading-relaxed text-mist-400">{patch.rationale}</p>
          <div className="tnum mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-mist-500">
            <span>
              confidence{" "}
              <span
                className={`font-medium ${
                  patch.confidence >= 0.9 ? "text-good-400" : "text-warn-400"
                }`}
              >
                {percent(patch.confidence)}
              </span>
            </span>
            {patch.evidence_count > 0 && <span>{patch.evidence_count} supporting cases</span>}
            <span>{relativeTime(patch.created_at)}</span>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <button
            className="btn-primary"
            disabled={apply.isPending}
            onClick={() =>
              apply.mutate({ id: patch.id }, { onSuccess: (r) => onNotice(r.message) })
            }
          >
            {apply.isPending ? "Applying…" : "Approve"}
          </button>
          <button
            className="btn-ghost"
            disabled={reject.isPending}
            onClick={() =>
              reject.mutate({ id: patch.id }, { onSuccess: (r) => onNotice(r.message) })
            }
          >
            Dismiss
          </button>
        </div>
      </div>
    </li>
  );
}

function ExceptionRow({
  item,
  onNotice,
}: {
  item: ExceptionCase;
  onNotice: (m: string) => void;
}) {
  const resolve = useResolveException();
  const [decision, setDecision] = useState(DECISIONS[0]);
  const [note, setNote] = useState("");

  return (
    <li className="px-4 py-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="warn">Needs a decision</Badge>
            <span className="text-2xs text-mist-500">{item.automation_name}</span>
            <span className="text-2xs text-mist-600">{relativeTime(item.created_at)}</span>
          </div>
          <p className="mt-2 max-w-3xl text-xs leading-relaxed text-mist-300">{item.reason}</p>

          {Object.keys(item.input_features).length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {Object.entries(item.input_features).map(([key, value]) => (
                <span key={key} className="chip">
                  <span className="text-mist-500">{key}</span>
                  <span className="font-mono">{formatFieldValue(value)}</span>
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="flex shrink-0 flex-col gap-2 sm:w-64">
          <select
            value={decision}
            onChange={(event) => setDecision(event.target.value)}
            className="rounded-md border border-ink-600 bg-ink-850 px-2 py-1.5 text-2xs text-mist-300 focus:border-accent-500 focus:outline-none"
          >
            {DECISIONS.map((value) => (
              <option key={value} value={value}>
                {value.replace(/_/g, " ")}
              </option>
            ))}
          </select>
          <input
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Why? (optional)"
            className="rounded-md border border-ink-600 bg-ink-850 px-2 py-1.5 text-2xs text-mist-300 placeholder:text-mist-600 focus:border-accent-500 focus:outline-none"
          />
          <button
            className="btn-primary"
            disabled={resolve.isPending}
            onClick={() =>
              resolve.mutate(
                { id: item.id, decision, note: note || undefined },
                {
                  onSuccess: (result) => {
                    onNotice(
                      result.rules_proposed > 0
                        ? `${result.message} — a new rule is now waiting above.`
                        : result.message,
                    );
                    setNote("");
                  },
                },
              )
            }
          >
            {resolve.isPending ? "Recording…" : "Record decision"}
          </button>
        </div>
      </div>
    </li>
  );
}
