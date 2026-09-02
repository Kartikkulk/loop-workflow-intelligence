"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";
import { Badge, ErrorNote, Meter, PageSkeleton, Panel } from "@/components/ui";
import { SignatureChips } from "@/components/workflow-graph";
import {
  useAutomation,
  useAutomations,
  useClusters,
  useInvestigateCluster,
  useReplay,
  useSystem,
} from "@/lib/api/queries";
import type { ClusterInvestigationResponse, InvestigationEvidence } from "@/lib/api/types";
import { percent } from "@/lib/format";

const STAGES = [
  { name: "Observe", detail: "Activity captured" },
  { name: "Discover", detail: "Patterns found" },
  { name: "Investigate", detail: "Meaning tested" },
  { name: "Validate", detail: "Evidence checked" },
  { name: "Automate", detail: "Flow generated" },
  { name: "Execute", detail: "Replay safely" },
] as const;

export default function DemoPage() {
  const clusters = useClusters();
  const automations = useAutomations();
  const system = useSystem();

  const featuredCluster =
    clusters.data?.recommended.find((cluster) => cluster.has_automation) ??
    clusters.data?.recommended[0];
  const featuredAutomationSummary =
    automations.data?.items.find((item) => item.id === featuredCluster?.automation_id) ??
    automations.data?.items[0];
  const automation = useAutomation(featuredAutomationSummary?.id ?? "");
  const investigate = useInvestigateCluster();
  const replay = useReplay();
  const runInvestigation = investigate.mutate;
  const investigatedClusterId = useRef<string | null>(null);

  useEffect(() => {
    if (featuredCluster?.id && investigatedClusterId.current !== featuredCluster.id) {
      investigatedClusterId.current = featuredCluster.id;
      runInvestigation(featuredCluster.id);
    }
  }, [featuredCluster?.id, runInvestigation]);

  const error = clusters.error ?? automations.error;
  if (clusters.isLoading || automations.isLoading) {
    return <DemoLoading />;
  }
  if (error) {
    return (
      <DemoState
        title="Unable to load workflow data."
        detail="The LOOP console could not reach the backend. Start the API and refresh this page."
        action={<ErrorNote error={error} />}
      />
    );
  }
  if (!featuredCluster) {
    return (
      <DemoState
        title="No repetitive workflow detected yet."
        detail="Connect an observation source or add activity data, then run detection."
        action={
          <Link className="btn-primary" href="/sources">
            Add activity
          </Link>
        }
      />
    );
  }

  const detail = automation.data;
  const report = replay.data;
  const executionOk = Boolean(report && report.errored === 0 && report.total > 0);

  return (
    <div className="pb-16">
      <header className="border-b border-ink-700 bg-ink-950/80 px-5 py-6 backdrop-blur sm:px-8">
        <div className="mx-auto max-w-[1500px]">
          <div className="flex flex-wrap items-end justify-between gap-5">
            <div>
              <p className="eyebrow text-accent-400">LOOP · workflow intelligence</p>
              <h1 className="mt-2 max-w-4xl text-2xl font-semibold tracking-tight text-mist-100 sm:text-3xl">
                Discover repetitive work → Understand it → Validate it → Automate it
              </h1>
              <p className="mt-2 max-w-3xl text-xs leading-relaxed text-mist-400">
                Evidence first. Every workflow is observed, investigated, grounded, and replayed
                with mock side effects before it earns the right to act.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Badge tone={system.data?.mock_connectors ? "good" : "warn"}>
                {system.data?.mock_connectors ? "Replay / mock only" : "Live connectors enabled"}
              </Badge>
              <Badge tone="neutral">{system.data?.llm_model ?? "LLM optional"}</Badge>
            </div>
          </div>

          <Pipeline activeStage={report ? "Execute" : "Automate"} />
        </div>
      </header>

      <main className="mx-auto max-w-[1500px] space-y-5 px-5 pt-5 sm:px-8">
        <section className="grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
          <DiscoveredWorkflow cluster={featuredCluster} />
          <Investigation
            data={investigate.data}
            isPending={investigate.isPending}
            error={investigate.error}
          />
        </section>

        <section className="grid gap-5 xl:grid-cols-[0.78fr_1.22fr]">
          <Validation
            data={investigate.data}
            isPending={investigate.isPending}
            error={investigate.error}
          />
          <AutomationFlow
            automation={detail}
            isLoading={automation.isLoading}
            error={automation.error}
          />
        </section>

        <Execution
          automationId={featuredAutomationSummary?.id}
          automationName={featuredAutomationSummary?.name}
          steps={detail?.steps ?? []}
          report={report}
          isPending={replay.isPending}
          error={replay.error}
          success={executionOk}
          onRun={(id) => replay.mutate({ id, days: 30 })}
        />
      </main>
    </div>
  );
}

function Pipeline({
  activeStage,
}: {
  activeStage: (typeof STAGES)[number]["name"];
}) {
  const activeIndex = STAGES.findIndex((stage) => stage.name === activeStage);
  return (
    <ol
      className="mt-6 grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6"
      aria-label="LOOP workflow pipeline"
    >
      {STAGES.map((stage, index) => {
        const done = index <= activeIndex;
        return (
          <li
            key={stage.name}
            className={`relative rounded-md border px-3 py-2.5 ${
              done
                ? "border-accent-500/35 bg-accent-500/10"
                : "border-ink-700 bg-ink-900"
            }`}
          >
            <div className="flex items-center gap-2">
              <span
                className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold ${
                  done ? "bg-accent-500 text-white" : "bg-ink-700 text-mist-500"
                }`}
              >
                {index + 1}
              </span>
              <div className="min-w-0">
                <p className="text-2xs font-semibold uppercase tracking-[0.1em] text-mist-200">
                  {stage.name}
                </p>
                <p className="truncate text-[10px] text-mist-500">{stage.detail}</p>
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function DiscoveredWorkflow({
  cluster,
}: {
  cluster: NonNullable<ReturnType<typeof useClusters>["data"]>["recommended"][number];
}) {
  return (
    <Panel
      title="Discovered workflow"
      hint="Live backend data · F2 discovery and F3 scoring"
      actions={<Badge tone="good">DISCOVERED</Badge>}
    >
      <div className="space-y-4 p-4">
        <div>
          <Link
            href={`/clusters/${cluster.id}`}
            className="text-base font-semibold text-mist-100 hover:text-accent-300"
          >
            {cluster.name}
          </Link>
          <p className="mt-1 text-2xs leading-relaxed text-mist-400">
            {cluster.description}
          </p>
        </div>

        <SignatureChips signature={cluster.signature} max={8} />

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Fact value={cluster.instance_count.toLocaleString()} label="executions" />
          <Fact value={String(cluster.distinct_users)} label="people" />
          <Fact value={String(cluster.apps.length)} label="applications" />
          <Fact value={percent(cluster.automatability)} label="automatable" />
        </div>

        <div className="rounded-md border border-ink-700 bg-ink-850 p-3">
          <p className="eyebrow">Repetition evidence</p>
          <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-2xs text-mist-400">
            <span>✓ {cluster.instance_count.toLocaleString()} observed instances</span>
            <span>✓ {cluster.distinct_users} distinct users</span>
            <span>
              ✓ {percent(cluster.variance_breakdown.dominant_variant_share)} dominant path
            </span>
          </div>
        </div>
      </div>
    </Panel>
  );
}

function Investigation({
  data,
  isPending,
  error,
}: {
  data?: ClusterInvestigationResponse;
  isPending: boolean;
  error: Error | null;
}) {
  if (isPending) {
    return (
      <Panel title="AI investigation" hint="Bounded Activity Atlas evidence">
        <div className="p-4">
          <p className="text-sm font-medium text-mist-200">Investigating workflow...</p>
          <p className="mt-1 text-2xs text-mist-500">
            Testing semantic claims against deterministic evidence.
          </p>
        </div>
      </Panel>
    );
  }

  if (error || !data) {
    return (
      <Panel
        title="AI investigation"
        hint="Bounded Activity Atlas evidence"
        actions={<Badge tone="warn">UNAVAILABLE</Badge>}
      >
        <div className="p-4">
          {error ? (
            <ErrorNote error={error} />
          ) : (
            <p className="text-xs text-mist-400">Investigation is not available.</p>
          )}
        </div>
      </Panel>
    );
  }

  const result = data.investigation;
  const conclusion = result.conclusions[0];
  const relationship = conclusion?.relationship ?? "insufficient_evidence";
  const confidence = conclusion?.confidence ?? 0;
  const variant = result.variant_statistics[0];
  const candidateEvidence = result.evidence.find(
    (item) => item.evidence_type === "candidate_summary",
  );
  const coreTokens = stringArray(candidateEvidence?.facts.core_tokens);
  const evidenceIds = Array.from(
    new Set([
      ...result.evidence.map((item) => item.evidence_id),
      ...(conclusion?.evidence_ids ?? []),
      ...result.semantic_relationships.flatMap((item) => item.evidence_ids),
    ]),
  ).filter(Boolean);
  const gaps = Array.from(
    new Set([
      ...result.evidence_gaps,
      ...(conclusion?.evidence_gaps ?? []),
      ...result.semantic_relationships.flatMap((item) => item.evidence_gaps),
    ]),
  );
  const isSafe = result.final_decision === "safe_to_continue";

  return (
    <Panel
      title="AI investigation"
      hint={`${result.generated_by} · ${result.model_name || "deterministic fallback"}`}
      actions={
        <Badge tone={isSafe ? "accent" : "warn"}>
          {result.status === "insufficient_evidence"
            ? "INSUFFICIENT EVIDENCE"
            : result.status.toUpperCase()}
        </Badge>
      }
    >
      <div className="space-y-4 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="eyebrow">Candidate workflow</p>
            <p className="mt-1 text-sm font-semibold text-mist-100">
              {result.candidate_workflow_id}
            </p>
          </div>
          <div className="text-right">
            <p className="eyebrow">Classification</p>
            <p className={`mt-1 font-mono text-xs font-semibold ${isSafe ? "text-accent-300" : "text-warn-400"}`}>
              {relationship}
            </p>
          </div>
        </div>

        <div>
          <div className="mb-2 flex items-center justify-between">
            <span className="eyebrow">Grounded confidence</span>
            <span className="tnum text-xs font-semibold text-mist-200">
              {percent(confidence)}
            </span>
          </div>
          <Meter value={confidence} tone={isSafe ? "accent" : "warn"} />
        </div>

        {coreTokens.length > 0 && (
          <ol className="flex flex-wrap items-center gap-1.5">
            {coreTokens.map((step, index) => (
              <li key={step} className="flex items-center gap-1.5">
                <StepToken token={step} />
                {index < coreTokens.length - 1 && <span className="text-mist-600">→</span>}
              </li>
            ))}
            {variant?.variant_token && (
              <li className="flex items-center gap-1.5">
                <span className="text-mist-600">→</span>
                <StepToken token={variant.variant_token} variant />
              </li>
            )}
          </ol>
        )}

        <div className="grid gap-2 sm:grid-cols-2">
          {result.evidence.slice(0, 4).map((item) => (
            <EvidenceLine key={item.evidence_id} text={evidenceSignal(item)} />
          ))}
        </div>

        <div>
          <p className="eyebrow">Evidence IDs</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {evidenceIds.map((id) => (
              <code
                key={id}
                className="rounded border border-ink-600 bg-ink-800 px-1.5 py-1 text-[10px] text-mist-300"
              >
                {id}
              </code>
            ))}
            {evidenceIds.length === 0 && (
              <span className="text-2xs text-mist-500">No grounded evidence cited.</span>
            )}
          </div>
          <p className="mt-2 text-2xs text-mist-500">
            Evidence gaps: {gaps.length ? gaps.join("; ") : "none"}
          </p>
        </div>
      </div>
    </Panel>
  );
}

function Validation({
  data,
  isPending,
  error,
}: {
  data?: ClusterInvestigationResponse;
  isPending: boolean;
  error: Error | null;
}) {
  const valid = data?.automation_eligible === true;
  const validated = data?.validation.validated ?? [];
  const rejected = data?.validation.rejected ?? [];

  return (
    <Panel
      title="Validation"
      hint="Grounding and automation-readiness gate"
      actions={
        <Badge tone={valid ? "good" : "warn"}>
          {isPending ? "CHECKING" : valid ? "VALIDATED" : "BLOCKED"}
        </Badge>
      }
    >
      <div className="space-y-3 p-4">
        {error ? (
          <ErrorNote error={error} />
        ) : isPending ? (
          <p className="text-xs text-mist-400">Validating grounded evidence...</p>
        ) : valid ? (
          <>
            <ValidationLine label="Evidence citations are grounded" />
            <ValidationLine label="Repetition is confirmed" />
            <ValidationLine label="Investigation is safe to continue" />
            <ValidationLine label={`${validated.length} proposal validated`} />
          </>
        ) : (
          <div className="rounded-md border border-warn-500/30 bg-warn-500/5 p-3">
            <p className="text-xs font-medium text-warn-400">
              {data?.investigation.final_decision === "insufficient_evidence"
                ? "Investigation blocked automation readiness"
                : "Additional evidence required"}
            </p>
            <p className="mt-1 text-2xs text-mist-400">
              Validator: {validated.length} validated, {rejected.length} rejected. LOOP will not
              claim readiness without both grounded validation and a safe investigation.
            </p>
          </div>
        )}
      </div>
    </Panel>
  );
}

function AutomationFlow({
  automation,
  isLoading,
  error,
}: {
  automation: ReturnType<typeof useAutomation>["data"];
  isLoading: boolean;
  error: Error | null;
}) {
  return (
    <Panel
      title="Generated automation"
      hint="Live persisted F4 automation · execution remains replay/mock"
      actions={automation ? <Badge tone="good">{automation.trust_level}</Badge> : undefined}
    >
      {isLoading && <p className="p-4 text-xs text-mist-400">Validating evidence…</p>}
      {error && <div className="p-4"><ErrorNote error={error} /></div>}
      {automation && (
        <div className="p-4">
          <div className="rounded-md border border-accent-500/30 bg-accent-500/5 px-3 py-2.5">
            <p className="eyebrow">Trigger</p>
            <p className="mt-1 font-mono text-xs text-accent-300">
              {automation.trigger.type ?? "manual"}
              {automation.trigger.filter &&
                ` · ${Object.entries(automation.trigger.filter)
                  .map(([key, value]) => `${key}=${String(value)}`)
                  .join(", ")}`}
            </p>
          </div>
          <ol className="mt-2 space-y-2">
            {automation.steps.map((step, index) => (
              <li key={`${step.id}-${index}`} className="flex gap-3">
                <div className="flex w-5 flex-col items-center">
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-ink-700 text-[10px] font-semibold text-mist-200">
                    {index + 1}
                  </span>
                  {index < automation.steps.length - 1 && (
                    <span className="h-full w-px bg-ink-600" />
                  )}
                </div>
                <div className="min-w-0 flex-1 rounded-md border border-ink-700 bg-ink-850 px-3 py-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-xs font-medium text-mist-200">{step.description}</p>
                    <code className="text-[10px] text-mist-500">{step.connector}</code>
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}
    </Panel>
  );
}

function Execution({
  automationId,
  automationName,
  steps,
  report,
  isPending,
  error,
  success,
  onRun,
}: {
  automationId?: string;
  automationName?: string;
  steps: NonNullable<ReturnType<typeof useAutomation>["data"]>["steps"];
  report: ReturnType<typeof useReplay>["data"];
  isPending: boolean;
  error: Error | null;
  success: boolean;
  onRun: (id: string) => void;
}) {
  return (
    <Panel
      title="Execute"
      hint="Existing F6 replay endpoint → existing F5 engine → mock connectors only"
      actions={
        <button
          className="btn-primary"
          disabled={!automationId || isPending}
          onClick={() => automationId && onRun(automationId)}
        >
          {isPending ? "Running automation…" : "Run Automation"}
        </button>
      }
    >
      <div className="grid gap-4 p-4 lg:grid-cols-[1fr_auto]">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="accent">REPLAY / MOCK EXECUTION</Badge>
            <span className="text-xs text-mist-300">{automationName ?? "Automation loading"}</span>
          </div>

          {!report && !isPending && !error && (
            <p className="mt-3 text-xs text-mist-500">
              Ready. Run the persisted automation against the last 30 days of historical triggers.
              No external action will occur.
            </p>
          )}
          {isPending && <p className="mt-3 text-xs text-accent-300">Running automation…</p>}
          {error && <div className="mt-3"><ErrorNote error={error} /></div>}

          {report && (
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {steps.map((step, index) => (
                <div
                  key={`${step.id}-${index}`}
                  className="flex items-center gap-2 rounded-md border border-good-500/25 bg-good-500/5 px-3 py-2"
                >
                  <span className="text-good-400">✓</span>
                  <span className="truncate text-2xs text-mist-300">
                    {step.description} evaluated
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="min-w-44 rounded-md border border-ink-700 bg-ink-850 p-3">
          <p className="eyebrow">Final status</p>
          <p
            className={`mt-2 text-lg font-semibold ${
              success ? "text-good-400" : report ? "text-warn-400" : "text-mist-400"
            }`}
          >
            {success ? "SUCCESS" : report ? "REVIEW" : "READY"}
          </p>
          {report && (
            <p className="tnum mt-1 text-2xs text-mist-500">
              {report.correct}/{report.total} correct · {percent(report.accuracy)} accuracy
            </p>
          )}
        </div>
      </div>
    </Panel>
  );
}

function Fact({ value, label }: { value: string; label: string }) {
  return (
    <div className="rounded-md border border-ink-700 bg-ink-850 px-3 py-2.5">
      <p className="metric text-lg text-mist-100">{value}</p>
      <p className="mt-1 text-[10px] uppercase tracking-wide text-mist-500">{label}</p>
    </div>
  );
}

function EvidenceLine({ text }: { text: string }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-good-500/20 bg-good-500/5 px-2.5 py-2">
      <span className="text-good-400">✓</span>
      <span className="text-2xs leading-relaxed text-mist-300">{text}</span>
    </div>
  );
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function evidenceSignal(evidence: InvestigationEvidence): string {
  if (evidence.description) return evidence.description;
  const label = evidence.evidence_type.replaceAll("_", " ");
  return evidence.supporting_ids.length
    ? `${label}: ${evidence.supporting_ids.join(", ")}`
    : label;
}

function ValidationLine({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 text-xs text-mist-300">
      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-good-500/10 text-good-400">
        ✓
      </span>
      {label}
    </div>
  );
}

function StepToken({ token, variant = false }: { token: string; variant?: boolean }) {
  const [, action] = token.split(":");
  return (
    <span
      className={`rounded border px-2 py-1 font-mono text-[10px] ${
        variant
          ? "border-warn-500/35 bg-warn-500/10 text-warn-300"
          : "border-ink-600 bg-ink-800 text-mist-300"
      }`}
    >
      {action ?? token}
      {variant && " · variant"}
    </span>
  );
}

function DemoLoading() {
  return (
    <div>
      <div className="border-b border-ink-700 px-8 py-6">
        <p className="eyebrow text-accent-400">LOOP · workflow intelligence</p>
        <p className="mt-2 text-xl font-semibold text-mist-100">Analyzing activity…</p>
        <p className="mt-1 text-xs text-mist-500">
          Discovering patterns, investigating meaning, and validating evidence.
        </p>
      </div>
      <PageSkeleton rows={5} />
    </div>
  );
}

function DemoState({
  title,
  detail,
  action,
}: {
  title: string;
  detail: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex min-h-[70vh] items-center justify-center p-6">
      <div className="panel max-w-xl p-6 text-center">
        <p className="text-base font-semibold text-mist-100">{title}</p>
        <p className="mt-2 text-xs leading-relaxed text-mist-400">{detail}</p>
        {action && <div className="mt-4">{action}</div>}
      </div>
    </div>
  );
}
