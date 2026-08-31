"use client";

import { useState } from "react";
import {
  Badge,
  Empty,
  ErrorNote,
  Loading,
  Meter,
  PageHeader,
  Panel,
  Stat,
} from "@/components/ui";
import {
  useRedetect,
  useRegisterSource,
  useRevokeSource,
  useSources,
  useUpdateSource,
} from "@/lib/api/queries";
import { percent, relativeTime, teamLabel } from "@/lib/format";
import type { Capability, ObservationSource } from "@/lib/api/types";

export default function SourcesPage() {
  const { data, isLoading, error } = useSources();
  const [connecting, setConnecting] = useState<Capability | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const redetect = useRedetect();

  if (isLoading) return <Loading label="Reading observation sources" />;
  if (error) return <div className="p-8"><ErrorNote error={error} /></div>;
  if (!data) return null;

  const coverage = data.coverage;

  return (
    <div className="pb-16">
      <PageHeader
        eyebrow="Observation"
        title="How LOOP sees the work"
        subtitle="Detection is only as good as what LOOP can observe. Each tier below buys coverage and costs either deployment effort or intrusiveness — the trade is stated rather than hidden, because a source people switch off is worth nothing."
        actions={
          <button
            className="btn-ghost"
            disabled={redetect.isPending}
            onClick={() =>
              redetect.mutate(undefined, {
                onSuccess: (r) =>
                  setNotice(`Detection re-run: ${r.clusters_detected} workflows now detected.`),
              })
            }
          >
            {redetect.isPending ? "Re-running…" : "Re-run detection"}
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

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            label="Connected sources"
            value={String(coverage.connected_sources)}
            hint={
              coverage.total_sources > coverage.connected_sources
                ? `${coverage.total_sources - coverage.connected_sources} paused or revoked`
                : "All onboarded sources are reporting"
            }
          />
          <Stat
            label="Estimated coverage"
            value={percent(coverage.estimated_coverage)}
            tone={coverage.estimated_coverage >= 0.6 ? "good" : "warn"}
            hint="Best connected tier, not the sum — the tiers overlap heavily"
          />
          <Stat
            label="Applications seen"
            value={String(coverage.distinct_apps)}
            hint="Including tools nobody configured, discovered by being used"
          />
          <Stat
            label="Observed events"
            value={coverage.observed_events.toLocaleString()}
            hint={`of ${coverage.total_events.toLocaleString()} total, the rest seeded or uploaded`}
          />
        </div>

        {connecting && (
          <ConnectPanel
            capability={connecting}
            onClose={() => setConnecting(null)}
            onConnected={(message) => {
              setNotice(message);
              setConnecting(null);
            }}
          />
        )}

        <Panel
          title="Ways to observe"
          hint="Pick the least intrusive tier that covers the work you care about."
        >
          <ul className="divide-y divide-ink-700">
            {data.capabilities.map((capability) => (
              <CapabilityRow
                key={capability.kind}
                capability={capability}
                connectedCount={
                  data.items.filter(
                    (s) => s.kind === capability.kind && s.status === "connected",
                  ).length
                }
                onConnect={() => setConnecting(capability)}
              />
            ))}
          </ul>
        </Panel>

        <Panel
          title="Onboarded sources"
          hint="Pausing stops capture immediately. Revoking invalidates the token and deletes everything that source reported."
        >
          {data.items.length === 0 ? (
            <Empty
              title="Nothing is observing yet"
              hint="Connect a browser to start seeing real activity, or describe a task from the Discovery screen."
            />
          ) : (
            <ul className="divide-y divide-ink-700">
              {data.items.map((source) => (
                <SourceRow key={source.id} source={source} onNotice={setNotice} />
              ))}
            </ul>
          )}
        </Panel>

        {coverage.apps_observed.length > 0 && (
          <Panel
            title="Applications observed"
            hint="Anything marked discovered was onboarded automatically the first time someone opened it."
          >
            <div className="flex flex-wrap gap-1.5 px-4 py-4">
              {coverage.apps_observed.map(({ app, events }) => (
                <span key={app} className="chip">
                  <span className="font-medium text-mist-200">{app}</span>
                  <span className="tnum text-mist-500">{events.toLocaleString()}</span>
                </span>
              ))}
            </div>
          </Panel>
        )}
      </div>
    </div>
  );
}

function CapabilityRow({
  capability,
  connectedCount,
  onConnect,
}: {
  capability: Capability;
  connectedCount: number;
  onConnect: () => void;
}) {
  const invasivenessTone = capability.invasiveness.startsWith("none")
    ? "good"
    : capability.invasiveness.startsWith("low")
      ? "good"
      : capability.invasiveness.startsWith("medium")
        ? "warn"
        : "bad";

  return (
    <li className="px-4 py-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-medium text-mist-100">{capability.label}</h3>
            {connectedCount > 0 && <Badge tone="good">{connectedCount} connected</Badge>}
            {!capability.available && <Badge tone="neutral">Not in this build</Badge>}
            <Badge tone={invasivenessTone as "good" | "warn" | "bad"}>
              {capability.invasiveness.split("—")[0].trim()}
            </Badge>
          </div>
          <p className="mt-1.5 max-w-3xl text-2xs leading-relaxed text-mist-400">
            {capability.summary}
          </p>

          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            <div>
              <p className="eyebrow mb-1.5">Can see</p>
              <ul className="space-y-1">
                {capability.sees.map((item) => (
                  <li key={item} className="flex gap-2 text-2xs leading-snug text-mist-300">
                    <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-good-500" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <p className="eyebrow mb-1.5">Blind to</p>
              <ul className="space-y-1">
                {capability.blind_to.map((item) => (
                  <li key={item} className="flex gap-2 text-2xs leading-snug text-mist-500">
                    <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink-500" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <p className="mt-3 text-2xs text-mist-500">
            <span className="text-mist-400">Setup:</span> {capability.setup}{" "}
            <span className="text-mist-600">· {capability.effort}</span>
          </p>
          {!capability.available && (
            <p className="mt-1.5 max-w-3xl text-2xs leading-relaxed text-warn-400">
              {capability.unavailable_reason}
            </p>
          )}
        </div>

        <div className="flex w-40 shrink-0 flex-col items-end gap-2">
          <div className="w-full text-right">
            <p className="eyebrow">Coverage</p>
            <p className="tnum mt-1 text-lg font-semibold leading-none text-mist-100">
              {percent(capability.coverage_estimate)}
            </p>
            <div className="mt-2">
              <Meter
                value={capability.coverage_estimate}
                tone={capability.available ? "accent" : "warn"}
              />
            </div>
          </div>
          <button
            className={capability.available ? "btn-primary w-full" : "btn-ghost w-full"}
            disabled={!capability.available}
            onClick={onConnect}
          >
            {capability.available ? "Connect" : "Unavailable"}
          </button>
        </div>
      </div>
    </li>
  );
}

function ConnectPanel({
  capability,
  onClose,
  onConnected,
}: {
  capability: Capability;
  onClose: () => void;
  onConnected: (message: string) => void;
}) {
  const register = useRegisterSource();
  const [label, setLabel] = useState(`${capability.label} — new`);
  const [userId, setUserId] = useState("u_asha");
  const [team, setTeam] = useState("accounts_payable");
  const [denylist, setDenylist] = useState("bank\npayroll\nmyhealth");
  const [withValues, setWithValues] = useState(false);
  const [consent, setConsent] = useState(false);
  const [issued, setIssued] = useState<{ token: string; sourceId: string } | null>(null);

  if (issued) {
    return (
      <Panel
        title="Source connected"
        hint="This token is shown once and cannot be retrieved again."
        actions={
          <button className="btn-ghost" onClick={onClose}>
            Done
          </button>
        }
      >
        <div className="space-y-4 px-4 py-4">
          <div>
            <p className="eyebrow mb-1.5">Source token</p>
            <div className="flex items-center gap-2">
              <code className="min-w-0 flex-1 overflow-x-auto rounded-md border border-ink-600 bg-ink-950 px-3 py-2 font-mono text-2xs text-accent-300">
                {issued.token}
              </code>
              <button
                className="btn-ghost shrink-0"
                onClick={() => void navigator.clipboard?.writeText(issued.token)}
              >
                Copy
              </button>
            </div>
          </div>

          {capability.kind === "browser_extension" && (
            <div className="rounded-md border border-ink-700 bg-ink-950/60 px-3.5 py-3">
              <p className="eyebrow mb-2">Install the collector</p>
              <ol className="space-y-1.5 text-2xs leading-relaxed text-mist-400">
                <li>
                  1. Open <span className="mono">chrome://extensions</span> and turn on
                  Developer mode.
                </li>
                <li>
                  2. Choose <b className="text-mist-200">Load unpacked</b> and select{" "}
                  <span className="mono">collectors/browser-extension</span> from this repo.
                </li>
                <li>3. The options page opens. Paste the token above and save.</li>
                <li>
                  4. Work normally. The collector flushes every 20 seconds; this page
                  updates on its own.
                </li>
              </ol>
            </div>
          )}
        </div>
      </Panel>
    );
  }

  return (
    <Panel
      title={`Connect: ${capability.label}`}
      hint={capability.summary}
      actions={
        <button className="btn-ghost" onClick={onClose}>
          Cancel
        </button>
      }
    >
      <div className="grid gap-4 px-4 py-4 lg:grid-cols-2">
        <div className="space-y-3">
          <Field label="Label" value={label} onChange={setLabel} />
          <Field label="Observes which person" value={userId} onChange={setUserId} />
          <Field label="Team" value={team} onChange={setTeam} />
        </div>

        <div className="space-y-3">
          <div>
            <p className="eyebrow mb-1.5">Never observe (one per line)</p>
            <textarea
              value={denylist}
              onChange={(event) => setDenylist(event.target.value)}
              rows={4}
              className="w-full resize-none rounded-md border border-ink-600 bg-ink-850 px-3 py-2 font-mono text-2xs text-mist-200 focus:border-accent-500 focus:outline-none"
            />
            <p className="mt-1 text-2xs leading-snug text-mist-500">
              Matched against the whole URL, and enforced on the server as well as in the
              collector.
            </p>
          </div>

          <label className="flex cursor-pointer items-start gap-2.5">
            <input
              type="checkbox"
              checked={withValues}
              onChange={(event) => setWithValues(event.target.checked)}
              className="mt-0.5 accent-accent-500"
            />
            <span className="text-2xs leading-snug text-mist-300">
              Also capture field values and page titles
              <span className="block text-mist-500">
                Off by default. Detection does not need values — leaving this off records
                that a field called <span className="mono">amount</span> was filled, never
                what was typed into it.
              </span>
            </span>
          </label>
        </div>
      </div>

      <div className="border-t border-ink-700 px-4 py-4">
        <label className="flex cursor-pointer items-start gap-2.5">
          <input
            type="checkbox"
            checked={consent}
            onChange={(event) => setConsent(event.target.checked)}
            className="mt-0.5 accent-accent-500"
          />
          <span className="text-2xs leading-relaxed text-mist-300">
            The person being observed has agreed to this, understands they can pause it at
            any time, and understands that revoking it deletes every event this source
            reported.
          </span>
        </label>

        {register.error && (
          <div className="mt-3">
            <ErrorNote error={register.error} />
          </div>
        )}

        <div className="mt-3.5 flex items-center gap-2">
          <button
            className="btn-primary"
            disabled={!consent || register.isPending || !label.trim() || !userId.trim()}
            onClick={() =>
              register.mutate(
                {
                  kind: capability.kind,
                  label: label.trim(),
                  user_id: userId.trim(),
                  team: team.trim() || "unknown",
                  capture_scope: withValues ? "with_values" : "metadata_only",
                  consent: true,
                  denylist: denylist.split("\n").map((s) => s.trim()).filter(Boolean),
                },
                {
                  onSuccess: (result) => {
                    setIssued({ token: result.token, sourceId: result.source.id });
                    onConnected(`Source ${result.source.id} connected.`);
                  },
                },
              )
            }
          >
            {register.isPending ? "Connecting…" : "Connect and issue token"}
          </button>
          {!consent && (
            <span className="text-2xs text-mist-500">Consent is required to continue.</span>
          )}
        </div>
      </div>
    </Panel>
  );
}

function Field({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <p className="eyebrow mb-1.5">{label}</p>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-md border border-ink-600 bg-ink-850 px-3 py-2 text-xs text-mist-200 focus:border-accent-500 focus:outline-none"
      />
    </div>
  );
}

function SourceRow({
  source,
  onNotice,
}: {
  source: ObservationSource;
  onNotice: (message: string) => void;
}) {
  const update = useUpdateSource();
  const revoke = useRevokeSource();
  const [confirming, setConfirming] = useState(false);

  const tone =
    source.status === "connected" ? "good" : source.status === "paused" ? "warn" : "neutral";

  return (
    <li className="px-4 py-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-medium text-mist-100">{source.label}</h3>
            <Badge tone={tone as "good" | "warn" | "neutral"}>{source.status}</Badge>
            <Badge tone={source.capture_scope === "metadata_only" ? "good" : "warn"}>
              {source.capture_scope === "metadata_only" ? "metadata only" : "captures values"}
            </Badge>
          </div>
          <div className="tnum mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-mist-500">
            <span className="mono">{source.kind}</span>
            <span>{source.user_id.replace(/^u_/, "")} · {teamLabel(source.team)}</span>
            <span>{source.event_count.toLocaleString()} events reported</span>
            {source.rejected_count > 0 && (
              <span className="text-warn-400">{source.rejected_count} excluded</span>
            )}
            {source.last_event_at && <span>last {relativeTime(source.last_event_at)}</span>}
          </div>
          {source.denylist.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {source.denylist.map((entry) => (
                <span key={entry} className="chip">
                  excluded <span className="font-mono">{entry}</span>
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {source.status !== "revoked" && (
            <button
              className="btn-ghost"
              disabled={update.isPending}
              onClick={() =>
                update.mutate(
                  {
                    id: source.id,
                    status: source.status === "paused" ? "connected" : "paused",
                  },
                  {
                    onSuccess: (next) =>
                      onNotice(
                        next.status === "paused"
                          ? "Capture paused. The collector stops within 30 seconds."
                          : "Capture resumed.",
                      ),
                  },
                )
              }
            >
              {source.status === "paused" ? "Resume" : "Pause"}
            </button>
          )}
          {source.status !== "revoked" &&
            (confirming ? (
              <button
                className="btn-danger"
                disabled={revoke.isPending}
                onClick={() =>
                  revoke.mutate(
                    { id: source.id },
                    {
                      onSuccess: (result) => {
                        onNotice(result.message);
                        setConfirming(false);
                      },
                    },
                  )
                }
              >
                {revoke.isPending ? "Revoking…" : "Confirm: delete its events"}
              </button>
            ) : (
              <button className="btn-ghost" onClick={() => setConfirming(true)}>
                Revoke
              </button>
            ))}
        </div>
      </div>
    </li>
  );
}
