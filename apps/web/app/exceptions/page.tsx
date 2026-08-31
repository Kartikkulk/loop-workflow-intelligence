"use client";

import Link from "next/link";
import { useState } from "react";
import {
  Badge,
  Empty,
  ErrorNote,
  PageHeader,
  PageSkeleton,
  Panel,
  Stat,
} from "@/components/ui";
import {
  useApplyPatch,
  useExceptions,
  usePatches,
  useRejectPatch,
  useResolveException,
} from "@/lib/api/queries";
import { formatFieldValue, percent, relativeTime } from "@/lib/format";
import type { ExceptionCase, Patch } from "@/lib/api/types";

const DECISIONS = ["route_to_manager", "approve", "reject", "hold_for_clarification"];

export default function ExceptionsPage() {
  const exceptions = useExceptions();
  const patches = usePatches();
  const [notice, setNotice] = useState<string | null>(null);

  const open = exceptions.data?.items.filter((e) => e.status === "open") ?? [];
  const resolved = exceptions.data?.items.filter((e) => e.status === "resolved") ?? [];
  const proposed = patches.data?.items.filter((p) => p.status === "proposed") ?? [];
  const settled = patches.data?.items.filter((p) => p.status !== "proposed") ?? [];

  return (
    <div className="pb-16">
      <PageHeader
        eyebrow="Review queue"
        title="Exceptions and proposed changes"
        subtitle="Where the automation stops and asks. Every resolution here is training data: enough matching decisions on the same input shape and LOOP proposes the branch that would have handled them."
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
        {exceptions.error && <ErrorNote error={exceptions.error} />}
        {patches.error && <ErrorNote error={patches.error} />}
        {(exceptions.isLoading || patches.isLoading) && <PageSkeleton rows={3} />}

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Open exceptions" value={String(open.length)} tone={open.length ? "warn" : "good"} />
          <Stat label="Resolved" value={String(resolved.length)} hint="Each one is a training example" />
          <Stat
            label="Proposed changes"
            value={String(proposed.length)}
            tone={proposed.length ? "accent" : "default"}
          />
          <Stat label="Applied" value={String(settled.filter((p) => p.status === "applied").length)} />
        </div>

        <Panel
          title="Proposed changes"
          hint="Drift remappings and learned branch rules. High-confidence remappings on non-destructive steps apply themselves; everything else waits here."
        >
          {proposed.length === 0 && settled.length === 0 ? (
            <Empty
              title="Nothing proposed"
              hint="Use the demo controls on an automation to break a source schema, or resolve three similar exceptions to trigger a rule proposal."
            />
          ) : (
            <ul className="divide-y divide-ink-700">
              {[...proposed, ...settled].map((patch) => (
                <PatchRow key={patch.id} patch={patch} onNotice={setNotice} />
              ))}
            </ul>
          )}
        </Panel>

        <Panel
          title="Exception queue"
          hint="Low-confidence or guard-held executions, with the reason stated."
        >
          {open.length === 0 && resolved.length === 0 ? (
            <Empty
              title="Queue is empty"
              hint="Nothing needs a human right now."
            />
          ) : (
            <ul className="divide-y divide-ink-700">
              {[...open, ...resolved].map((item) => (
                <ExceptionRow key={item.id} item={item} onNotice={setNotice} />
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}

function PatchRow({
  patch,
  onNotice,
}: {
  patch: Patch;
  onNotice: (message: string) => void;
}) {
  const apply = useApplyPatch();
  const reject = useRejectPatch();
  const pending = patch.status === "proposed";

  return (
    <li className="px-4 py-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={patch.kind === "rule" ? "accent" : "warn"}>
              {patch.kind === "rule" ? "Learned rule" : "Schema drift"}
            </Badge>
            {patch.status === "applied" && <Badge tone="good">Applied</Badge>}
            {patch.status === "rejected" && <Badge tone="neutral">Dismissed</Badge>}
            {patch.auto_applicable && patch.status === "applied" && (
              <span className="text-2xs text-good-400">applied automatically</span>
            )}
            <Link
              href={`/automations/${patch.automation_id}`}
              className="text-2xs text-mist-500 hover:text-mist-300"
            >
              {patch.automation_name}
            </Link>
          </div>

          {/* The change rendered as a diff, which is how a reviewer reads it. */}
          <div className="mt-2.5 rounded-md border border-ink-700 bg-ink-950/60 px-3 py-2.5">
            {patch.kind === "rule" ? (
              <p className="mono text-good-400">
                + IF {patch.rule?.condition} THEN {patch.rule?.action}
              </p>
            ) : (
              <>
                <p className="mono text-bad-400">
                  − {patch.step_id}.depends_on: &quot;{patch.from_value}&quot;
                </p>
                <p className="mono text-good-400">
                  + {patch.step_id}.depends_on: &quot;{patch.to_value}&quot;
                </p>
              </>
            )}
          </div>

          <p className="mt-2 max-w-3xl text-2xs leading-relaxed text-mist-400">
            {patch.rationale}
          </p>
          <div className="tnum mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-mist-500">
            <span>
              confidence{" "}
              <span
                className={`font-medium ${
                  patch.confidence >= 0.9 ? "text-good-400" : "text-warn-400"
                }`}
              >
                {percent(patch.confidence, 0)}
              </span>
            </span>
            {patch.evidence_count > 0 && <span>{patch.evidence_count} supporting cases</span>}
            <span className="mono">proposed by {patch.proposed_by}</span>
            <span>{relativeTime(patch.created_at)}</span>
          </div>
        </div>

        {pending && (
          <div className="flex shrink-0 items-center gap-2">
            <button
              className="btn-primary"
              disabled={apply.isPending}
              onClick={() =>
                apply.mutate({ id: patch.id }, { onSuccess: (r) => onNotice(r.message) })
              }
            >
              {apply.isPending ? "Applying…" : "Accept"}
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
        )}
      </div>
      {(apply.error || reject.error) && (
        <p className="mt-2 text-2xs text-bad-400">
          {(apply.error ?? reject.error) instanceof Error
            ? (apply.error ?? reject.error)!.message
            : "Failed"}
        </p>
      )}
    </li>
  );
}

function ExceptionRow({
  item,
  onNotice,
}: {
  item: ExceptionCase;
  onNotice: (message: string) => void;
}) {
  const resolve = useResolveException();
  const [decision, setDecision] = useState(DECISIONS[0]);
  const [note, setNote] = useState("");
  const isOpen = item.status === "open";

  return (
    <li className="px-4 py-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={isOpen ? "warn" : "good"}>{isOpen ? "Needs review" : "Resolved"}</Badge>
            <span className="mono">{item.signature_key}</span>
            <Link
              href={`/automations/${item.automation_id}`}
              className="text-2xs text-mist-500 hover:text-mist-300"
            >
              {item.automation_name}
            </Link>
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

          {!isOpen && item.human_decision && (
            <p className="mt-2 text-2xs text-mist-400">
              Decided:{" "}
              <span className="font-medium text-good-400">{item.human_decision}</span>
              {item.human_note && <span className="text-mist-500"> — {item.human_note}</span>}
            </p>
          )}
        </div>

        {isOpen && (
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
                          ? `${result.message} — check Proposed changes.`
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
        )}
      </div>
    </li>
  );
}
