"use client";

import { useRef, useState } from "react";
import {
  Badge,
  ErrorNote,
  PageHeader,
  PageSkeleton,
  Panel,
  Stat,
} from "@/components/ui";
import {
  useDescribeWorkflow,
  useRedetect,
  useRevokeSource,
  useSources,
  useUpdateSource,
  useUploadLog,
} from "@/lib/api/queries";
import { relativeTime } from "@/lib/format";
import type { ObservationSource } from "@/lib/api/types";

const EXAMPLE_DESCRIPTION =
  "Every Monday I download the vendor ageing report, filter for rows more than 30 days overdue, update the summary tab, and email it to the finance leads.";

/**
 * Where the data comes from.
 *
 * The problem statement names three inputs — screen recordings, activity logs,
 * and workflow descriptions — so those are the three cards, in that order, with
 * the live browser collector as a fourth. Everything else that used to be on
 * this screen (per-team tool tables, coverage tiers, blind-spot columns) has
 * gone: it explained the architecture rather than telling anyone what to do.
 */
export default function SourcesPage() {
  const { data, isLoading, error } = useSources();
  const redetect = useRedetect();
  const [notice, setNotice] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  if (isLoading) return <PageSkeleton rows={3} />;
  if (error) return <div className="p-8"><ErrorNote error={error} /></div>;
  if (!data) return null;

  const connected = data.items.filter((s) => s.status === "connected");

  return (
    <div className="pb-16">
      <PageHeader
        eyebrow="Sources"
        title="Where the data comes from"
        subtitle="LOOP can only find repetitive work in activity it can see. Give it one of these and it starts looking."
        actions={
          <button
            className="btn-ghost"
            disabled={redetect.isPending}
            onClick={() =>
              redetect.mutate(undefined, {
                onSuccess: (r) => setNotice(`${r.clusters_detected} workflows found.`),
              })
            }
          >
            {redetect.isPending ? "Looking…" : "Look again"}
          </button>
        }
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

        <div className="grid gap-3 sm:grid-cols-3">
          <Stat
            label="Activity seen"
            value={data.coverage.total_events.toLocaleString()}
            unit="events"
          />
          <Stat
            label="Applications"
            value={String(data.coverage.distinct_apps)}
            hint="Recognised automatically from the activity"
          />
          <Stat
            label="Sources connected"
            value={String(connected.length)}
            tone={connected.length > 0 ? "good" : "default"}
          />
        </div>

        {/* ── the four ways in ─────────────────────────────────────── */}
        <div className="grid gap-3 lg:grid-cols-2">
          <SourceCard
            title="Activity log"
            blurb="An export from a tool you already use. CSV or JSONL."
            detail="Fastest way to see real results. Needs a user, a timestamp, an application and an action per row — LOOP maps common column names for you."
            open={open === "log"}
            onToggle={() => setOpen(open === "log" ? null : "log")}
          >
            <UploadPanel onNotice={setNotice} />
          </SourceCard>

          <SourceCard
            title="Describe the task"
            blurb="Type out a task somebody repeats, in plain English."
            detail="No setup at all. Useful when there is no log to export, which is most of the time."
            open={open === "describe"}
            onToggle={() => setOpen(open === "describe" ? null : "describe")}
          >
            <DescribePanel onNotice={setNotice} />
          </SourceCard>

          <SourceCard
            title="Browser extension"
            blurb="Watches the web applications your team works in, live."
            detail="Two minutes to install. Records which application and what kind of action — never what was typed. Copied values are matched by hash, so LOOP can tell data moved between two systems without ever receiving it."
            badge={<Badge tone="good">Best coverage</Badge>}
            open={open === "browser"}
            onToggle={() => setOpen(open === "browser" ? null : "browser")}
          >
            <BrowserPanel onNotice={setNotice} />
          </SourceCard>

          <SourceCard
            title="Screen recording"
            blurb="Frames from a recorded session, read by a vision model."
            detail="For systems with no API and no web interface. Needs an ANTHROPIC_API_KEY — it is the one input with no offline fallback, so it is disabled rather than faked when no key is set."
            badge={<Badge tone="warn">Needs an API key</Badge>}
            open={open === "recording"}
            onToggle={() => setOpen(open === "recording" ? null : "recording")}
          >
            <p className="px-4 py-4 text-2xs leading-relaxed text-mist-400">
              Set <span className="mono">ANTHROPIC_API_KEY</span> in{" "}
              <span className="mono">.env</span> and restart the API, then post frames to{" "}
              <span className="mono">POST /api/v1/ingest/recording</span>. Frames are read and
              discarded — only the application, the action and the kind of object are kept.
            </p>
          </SourceCard>
        </div>

        {/* ── what is connected ────────────────────────────────────── */}
        {data.items.length > 0 && (
          <Panel
            title="Connected"
            hint="Pause stops capture within 30 seconds. Removing a source deletes everything it reported."
          >
            <ul className="divide-y divide-ink-700">
              {data.items.map((source) => (
                <ConnectedRow key={source.id} source={source} onNotice={setNotice} />
              ))}
            </ul>
          </Panel>
        )}
      </div>
    </div>
  );
}

function SourceCard({
  title,
  blurb,
  detail,
  badge,
  open,
  onToggle,
  children,
}: {
  title: string;
  blurb: string;
  detail: string;
  badge?: React.ReactNode;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <section className={`panel shadow-lift ${open ? "border-accent-500/40" : ""}`}>
      <button
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-start gap-3 px-4 py-4 text-left transition-colors hover:bg-ink-850/60"
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-medium text-mist-100">{title}</h3>
            {badge}
          </div>
          <p className="mt-1 text-xs text-mist-300">{blurb}</p>
          <p className="mt-1.5 max-w-prose text-2xs leading-relaxed text-mist-500">{detail}</p>
        </div>
        <span
          className={`mt-0.5 shrink-0 text-mist-500 transition-transform ${open ? "rotate-90" : ""}`}
          aria-hidden
        >
          ›
        </span>
      </button>
      {open && <div className="border-t border-ink-700">{children}</div>}
    </section>
  );
}

function UploadPanel({ onNotice }: { onNotice: (m: string) => void }) {
  const upload = useUploadLog();
  const input = useRef<HTMLInputElement>(null);

  return (
    <div className="px-4 py-4">
      <input
        ref={input}
        type="file"
        accept=".csv,.jsonl,.ndjson,.json"
        disabled={upload.isPending}
        className="block w-full cursor-pointer rounded-md border border-ink-600 bg-ink-850 px-3 py-2 text-2xs text-mist-400 file:mr-3 file:rounded file:border-0 file:bg-ink-700 file:px-2.5 file:py-1 file:text-2xs file:font-medium file:text-mist-200"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (!file) return;
          upload.mutate(
            { file },
            {
              onSuccess: (r) =>
                onNotice(
                  `${r.events_ingested.toLocaleString()} events read. ${r.clusters_detected} workflows found.`,
                ),
            },
          );
        }}
      />
      {upload.error && (
        <p className="mt-2 text-2xs text-bad-400">
          {upload.error instanceof Error ? upload.error.message : "Upload failed"}
        </p>
      )}
      {upload.isPending && <p className="mt-2 text-2xs text-mist-500">Reading…</p>}
    </div>
  );
}

function DescribePanel({ onNotice }: { onNotice: (m: string) => void }) {
  const describe = useDescribeWorkflow();
  const [text, setText] = useState("");

  return (
    <div className="px-4 py-4">
      <textarea
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder={EXAMPLE_DESCRIPTION}
        rows={3}
        disabled={describe.isPending}
        className="w-full resize-none rounded-md border border-ink-600 bg-ink-850 px-3 py-2 text-xs leading-relaxed text-mist-200 placeholder:text-mist-600 focus:border-accent-500 focus:outline-none"
      />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button
          className="btn-primary"
          disabled={describe.isPending || text.trim().length < 10}
          onClick={() =>
            describe.mutate(
              { description: text },
              {
                onSuccess: (r) =>
                  onNotice(
                    `Read as "${r.workflow_name ?? "a workflow"}". ${r.clusters_detected} workflows found.`,
                  ),
              },
            )
          }
        >
          {describe.isPending ? "Reading…" : "Find the workflow"}
        </button>
        <button
          className="btn-ghost"
          disabled={describe.isPending}
          onClick={() => setText(EXAMPLE_DESCRIPTION)}
        >
          Use an example
        </button>
      </div>
      {describe.error && (
        <p className="mt-2 text-2xs text-bad-400">
          {describe.error instanceof Error ? describe.error.message : "Failed"}
        </p>
      )}
    </div>
  );
}

function BrowserPanel({ onNotice }: { onNotice: (m: string) => void }) {
  return (
    <div className="space-y-3 px-4 py-4">
      <ol className="space-y-1.5 text-2xs leading-relaxed text-mist-400">
        <li>
          <span className="text-mist-200">1.</span> Run{" "}
          <span className="mono">make collectors</span> in the project.
        </li>
        <li>
          <span className="text-mist-200">2.</span> Open{" "}
          <span className="mono">chrome://extensions</span>, turn on Developer mode, choose{" "}
          <b className="text-mist-200">Load unpacked</b>, pick{" "}
          <span className="mono">collectors/dist/chrome</span>.
        </li>
        <li>
          <span className="text-mist-200">3.</span> Press the button below, copy the token, paste
          it into the extension.
        </li>
      </ol>
      <ConnectBrowser onNotice={onNotice} />
    </div>
  );
}

function ConnectBrowser({ onNotice }: { onNotice: (m: string) => void }) {
  const [token, setToken] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);

  async function connect() {
    setPending(true);
    setFailed(null);
    try {
      const { http } = await import("@/lib/api/client");
      const result = await http.post<{ token: string; source: { id: string } }>(
        "/api/v1/sources",
        {
          kind: "browser_extension",
          label: "Browser",
          user_id: "u_me",
          team: "unknown",
          consent: true,
          denylist: ["bank", "payroll"],
        },
      );
      setToken(result.token);
      onNotice("Browser connected. Paste the token into the extension.");
    } catch (error) {
      setFailed(error instanceof Error ? error.message : "Could not connect");
    } finally {
      setPending(false);
    }
  }

  if (token) {
    return (
      <div>
        <p className="eyebrow mb-1.5">Token — shown once</p>
        <div className="flex items-center gap-2">
          <code className="min-w-0 flex-1 overflow-x-auto rounded-md border border-ink-600 bg-ink-950 px-3 py-2 font-mono text-2xs text-accent-300">
            {token}
          </code>
          <button
            className="btn-ghost shrink-0"
            onClick={() => void navigator.clipboard?.writeText(token)}
          >
            Copy
          </button>
        </div>
      </div>
    );
  }

  return (
    <div>
      <button className="btn-primary" onClick={connect} disabled={pending}>
        {pending ? "Connecting…" : "Connect a browser"}
      </button>
      <p className="mt-2 text-2xs text-mist-500">
        Records metadata only. Pause or remove it at any time.
      </p>
      {failed && <p className="mt-2 text-2xs text-bad-400">{failed}</p>}
    </div>
  );
}

function ConnectedRow({
  source,
  onNotice,
}: {
  source: ObservationSource;
  onNotice: (m: string) => void;
}) {
  const update = useUpdateSource();
  const revoke = useRevokeSource();
  const [confirming, setConfirming] = useState(false);

  const tone =
    source.status === "connected" ? "good" : source.status === "paused" ? "warn" : "neutral";

  return (
    <li className="flex flex-wrap items-center justify-between gap-4 px-4 py-3.5">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-mist-100">{source.label}</span>
          <Badge tone={tone as "good" | "warn" | "neutral"}>{source.status}</Badge>
        </div>
        <div className="tnum mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-mist-500">
          <span>{source.event_count.toLocaleString()} events</span>
          {source.last_event_at && <span>last {relativeTime(source.last_event_at)}</span>}
          <span>metadata only</span>
        </div>
      </div>

      {source.status !== "revoked" && (
        <div className="flex shrink-0 items-center gap-2">
          <button
            className="btn-ghost"
            disabled={update.isPending}
            onClick={() =>
              update.mutate({
                id: source.id,
                status: source.status === "paused" ? "connected" : "paused",
              })
            }
          >
            {source.status === "paused" ? "Resume" : "Pause"}
          </button>
          {confirming ? (
            <button
              className="btn-danger"
              disabled={revoke.isPending}
              onClick={() =>
                revoke.mutate(
                  { id: source.id },
                  {
                    onSuccess: (r) => {
                      onNotice(r.message);
                      setConfirming(false);
                    },
                  },
                )
              }
            >
              {revoke.isPending ? "Removing…" : "Confirm — deletes its data"}
            </button>
          ) : (
            <button className="btn-ghost" onClick={() => setConfirming(true)}>
              Remove
            </button>
          )}
        </div>
      )}
    </li>
  );
}
