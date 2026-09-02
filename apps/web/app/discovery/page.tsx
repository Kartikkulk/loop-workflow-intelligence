"use client";

import { useState } from "react";
import { IngestPanel } from "@/components/ingest-panel";
import { SignatureChips } from "@/components/workflow-graph";
import {
  Badge,
  Empty,
  ErrorNote,
  Meter,
  PageHeader,
  PageSkeleton,
  Panel,
  Stat,
} from "@/components/ui";
import {
  useCandidates,
  useCreateCandidateAutomation,
  useInvestigateCandidate,
  usePromote,
  useReplay,
  useValidateCandidate,
} from "@/lib/api/queries";
import { percent } from "@/lib/format";
import type { CandidateStatus, CandidateWorkflow } from "@/lib/api/types";

export default function DiscoveryPage() {
  const candidates = useCandidates();
  const [showIngest, setShowIngest] = useState(false);
  const items = candidates.data?.items ?? [];
  const apps = new Set(items.flatMap((candidate) => candidate.apps));

  return (
    <div className="pb-16">
      <PageHeader
        eyebrow="Step 2 of 4"
        title="Workflows observed in your browser"
        subtitle="Live candidates built only from browser-extension events through the existing sessioniser and workflow clustering pipeline. Seed workflows are not shown here."
        actions={
          <button className="btn-ghost" onClick={() => setShowIngest((value) => !value)}>
            {showIngest ? "Hide" : "Add activity data"}
          </button>
        }
      />

      <div className="space-y-6 px-5 pt-6 sm:px-8">
        {showIngest && <IngestPanel onDone={() => setShowIngest(false)} />}
        {candidates.error && <ErrorNote error={candidates.error} />}
        {candidates.isLoading && <PageSkeleton rows={4} />}

        {candidates.data && (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Stat
                label="Live workflows"
                value={String(candidates.data.total)}
                hint="Browser-extension activity only"
              />
              <Stat
                label="Observed sessions"
                value={String(items.reduce((total, item) => total + item.session_count, 0))}
                hint="Sessionised by the existing F2 pipeline"
              />
              <Stat
                label="Applications"
                value={String(apps.size)}
                hint={Array.from(apps).join(", ") || "No browser activity yet"}
              />
              <Stat
                label="Validated"
                value={String(items.filter((item) => item.status === "validated").length)}
                hint="Grounded against Activity Atlas evidence"
                tone="accent"
              />
            </div>

            <Panel
              title="Live workflow candidates"
              hint="Observed ≥1 session · Candidate ≥2 occurrences · lifecycle actions require grounded evidence"
            >
              {items.length === 0 ? (
                <Empty
                  title="No browser workflows observed yet"
                  hint="Capture a multi-step browser task, then refresh this page. Synthetic seed clusters are intentionally excluded."
                />
              ) : (
                <ul className="divide-y divide-ink-700">
                  {items.map((candidate) => (
                    <CandidateCard key={candidate.workflow_id} candidate={candidate} />
                  ))}
                </ul>
              )}
            </Panel>
          </>
        )}
      </div>
    </div>
  );
}

function CandidateCard({ candidate }: { candidate: CandidateWorkflow }) {
  const investigate = useInvestigateCandidate();
  const validate = useValidateCandidate();
  const createAutomation = useCreateCandidateAutomation();
  const approve = usePromote();
  const replay = useReplay();

  const investigation = candidate.investigation;
  const conclusion = investigation?.conclusions[0];
  const canValidate =
    investigation?.status === "ok" &&
    investigation.final_decision === "safe_to_continue";
  const grounded = candidate.validation?.validated[0];
  const canCreate = Boolean(grounded && !candidate.automation_id);
  const approved =
    Boolean(candidate.automation_id) &&
    candidate.automation_trust_level !== null &&
    candidate.automation_trust_level !== "SUGGEST";
  const error =
    investigate.error ??
    validate.error ??
    createAutomation.error ??
    approve.error ??
    replay.error;

  return (
    <li className="p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-mist-100">{candidate.name}</h3>
            <StatusBadge status={candidate.status} />
            {candidate.automation_trust_level && (
              <Badge tone={approved ? "good" : "warn"}>
                {candidate.automation_trust_level}
              </Badge>
            )}
          </div>
          <p className="mt-1 font-mono text-[10px] text-mist-600">
            {candidate.workflow_id}
          </p>
          <div className="mt-3">
            <SignatureChips signature={candidate.signature_tokens} max={12} />
          </div>
        </div>

        <div className="w-full sm:w-44">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="eyebrow">Evidence confidence</span>
            <span className="tnum text-xs text-mist-300">
              {percent(candidate.confidence)}
            </span>
          </div>
          <Meter value={candidate.confidence} tone="accent" />
        </div>
      </div>

      <div className="tnum mt-4 flex flex-wrap gap-x-5 gap-y-1 text-2xs text-mist-500">
        <span>{candidate.session_count} sessions</span>
        <span>{candidate.occurrence_count} occurrences</span>
        <span>{candidate.distinct_users} users</span>
        <span>{candidate.apps.join(" → ")}</span>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {!candidate.automation_id && (
          <button
            className="btn-primary"
            disabled={investigate.isPending}
            onClick={() => investigate.mutate(candidate.workflow_id)}
          >
            {investigate.isPending ? "Investigating…" : "Investigate Workflow"}
          </button>
        )}
        {investigation && !candidate.automation_id && (
          <button
            className="btn-ghost"
            disabled={!canValidate || validate.isPending}
            onClick={() => validate.mutate(candidate.workflow_id)}
            title={
              canValidate
                ? "Validate against Activity Atlas evidence"
                : "Investigation must be safe to continue"
            }
          >
            {validate.isPending ? "Validating…" : "Validate Workflow"}
          </button>
        )}
        {candidate.validation && !candidate.automation_id && (
          <button
            className="btn-ghost"
            disabled={!canCreate || createAutomation.isPending}
            onClick={() => createAutomation.mutate(candidate.workflow_id)}
          >
            {createAutomation.isPending ? "Creating…" : "Create Automation"}
          </button>
        )}
        {candidate.automation_id && candidate.automation_trust_level === "SUGGEST" && (
          <button
            className="btn-primary"
            disabled={approve.isPending}
            onClick={() => approve.mutate({ id: candidate.automation_id!, force: true })}
          >
            {approve.isPending ? "Approving…" : "Approve"}
          </button>
        )}
        {candidate.automation_id && approved && (
          <button
            className="btn-primary"
            disabled={replay.isPending}
            onClick={() => replay.mutate({ id: candidate.automation_id!, days: 30 })}
          >
            {replay.isPending ? "Running replay…" : "Run Replay"}
          </button>
        )}
      </div>

      {error && (
        <div className="mt-3">
          <ErrorNote error={error} />
        </div>
      )}

      {investigation && (
        <div className="mt-4 rounded-md border border-ink-700 bg-ink-850 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="eyebrow">Investigation result</p>
            <Badge
              tone={
                investigation.final_decision === "safe_to_continue" ? "accent" : "warn"
              }
            >
              {conclusion?.relationship ?? "INSUFFICIENT EVIDENCE"}
            </Badge>
          </div>
          <p className="mt-2 text-xs text-mist-300">
            Confidence {percent(conclusion?.confidence ?? 0)} ·{" "}
            {investigation.final_decision.replaceAll("_", " ")}
          </p>
          <p className="mt-1 text-2xs text-mist-500">
            Evidence:{" "}
            {investigation.evidence
              .slice(0, 12)
              .map((item) => item.evidence_id)
              .join(", ") || "none cited"}
            {investigation.evidence.length > 12
              ? ` +${investigation.evidence.length - 12} more`
              : ""}
          </p>
          <p className="mt-1 text-2xs text-mist-500">
            Gaps: {investigation.evidence_gaps.join("; ") || "none"}
          </p>
        </div>
      )}

      {candidate.validation && (
        <div className="mt-3 rounded-md border border-good-500/25 bg-good-500/5 p-3">
          <p className="eyebrow text-good-400">Grounded validation</p>
          {grounded ? (
            <p className="mt-2 text-xs text-mist-300">
              Validated · score {percent(grounded.validation_score)} ·{" "}
              {grounded.issues.length ? grounded.issues.join("; ") : "no grounding issues"}
            </p>
          ) : (
            <p className="mt-2 text-xs text-warn-400">
              Rejected ·{" "}
              {candidate.validation.rejected[0]?.issues.join("; ") ||
                "insufficient grounded evidence"}
            </p>
          )}
        </div>
      )}

      {candidate.automation_id && (
        <div className="mt-3 rounded-md border border-accent-500/25 bg-accent-500/5 p-3">
          <p className="eyebrow">Persisted automation</p>
          <p className="mt-1 font-mono text-xs text-accent-300">
            {candidate.automation_id}
          </p>
          <p className="mt-1 text-2xs text-mist-500">
            Human approval moves SUGGEST to SHADOW before replay is enabled.
          </p>
        </div>
      )}

      {replay.data && (
        <div className="mt-3 rounded-md border border-good-500/25 bg-good-500/5 p-3">
          <p className="text-xs font-semibold text-good-400">REPLAY COMPLETE</p>
          <p className="tnum mt-1 text-2xs text-mist-300">
            {replay.data.correct}/{replay.data.total - replay.data.not_comparable} scored
            correctly · {percent(replay.data.accuracy)} accuracy · {replay.data.errored} step
            errors
          </p>
          {replay.data.not_comparable > 0 && (
            <p className="mt-1 text-2xs text-mist-500">
              {replay.data.not_comparable} of {replay.data.total} matching historical rows lacked
              comparable output fields.
            </p>
          )}
        </div>
      )}
    </li>
  );
}

function StatusBadge({ status }: { status: CandidateStatus }) {
  const tone =
    status === "validated"
      ? "good"
      : status === "investigated"
        ? "accent"
        : status === "candidate"
          ? "warn"
          : "neutral";
  return <Badge tone={tone}>{status.toUpperCase()}</Badge>;
}
