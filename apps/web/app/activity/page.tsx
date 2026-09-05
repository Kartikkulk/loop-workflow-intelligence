"use client";

import { useMemo, useState } from "react";
import { Badge, Empty, ErrorNote, PageHeader, PageSkeleton, Panel } from "@/components/ui";
import { useActivity, useAutoSyncConnections, useSystem } from "@/lib/api/queries";
import { relativeTime } from "@/lib/format";
import type { ActivityEvent } from "@/lib/api/types";

/**
 * What Kriyā AI has actually seen.
 *
 * The point of this screen is falsifiability. Every discovery downstream is
 * derived from these rows, so a person can check that the platform is working
 * from real observations rather than taking the claim on faith. It is also the
 * honest answer to "what are you collecting about me?" — the answer is these
 * columns and nothing else.
 */
/** What each stored source value is called in the interface. */
const SOURCE_LABELS: Record<string, string> = {
  upload: "CSV / file upload",
  browser_extension: "Browser collector",
  desktop: "Desktop recorder",
  connector: "Connected account",
  seed: "Demo data",
};

export default function ActivityPage() {
  const [app, setApp] = useState<string | null>(null);
  const [source, setSource] = useState<string | null>(null);
  const activity = useActivity(200, source ?? undefined, app ?? undefined);
  const system = useSystem();
  // Connected accounts keep pulling while this screen is open.
  useAutoSyncConnections();

  // Memoised because `?? []` builds a fresh array each render, which would
  // make the useMemo below recompute on every one of them.
  const events = useMemo(() => activity.data?.items ?? [], [activity.data]);
  // Facets come from the server, counted across the whole log rather than the
  // page in hand — so selecting a filter never makes the other options vanish.
  const apps = activity.data?.apps ?? [];
  const sources = activity.data?.sources ?? [];

  const shown = events;
  const sessions = new Set(events.map((e) => e.session_id ?? "")).size;

  if (activity.isLoading) return <PageSkeleton rows={4} />;
  if (activity.error) {
    return <div className="p-8"><ErrorNote error={activity.error} /></div>;
  }

  return (
    <div className="pb-16">
      <PageHeader
        eyebrow="Activity"
        title="What Kriyā AI has seen"
        subtitle="Every discovery is derived from these rows. No page contents, no keystrokes, no passwords — which application, which action, on what kind of thing, and for how long."
      />

      <div className="space-y-6 px-8 pt-6">
        <div className="grid gap-3 sm:grid-cols-3">
          <Tile
            label="Events stored"
            value={(system.data?.event_count ?? activity.data?.total ?? 0).toLocaleString()}
            hint="Everything Kriyā AI has observed so far"
          />
          <Tile
            label="Work sessions"
            value={String(sessions)}
            hint="Runs of activity, split on a gap in the log"
          />
          <Tile
            label="Applications"
            value={String(apps.length)}
            hint="Distinct systems the work touched"
          />
        </div>

        {sources.length > 0 && (
          <Panel
            title="By source"
            hint="Where the events came from. Detection treats them identically — this is so you can see what you are looking at."
          >
            <div className="flex flex-wrap gap-2 px-4 py-3">
              <button
                className={`rounded-md border px-2.5 py-1 text-2xs transition-colors ${
                  source === null
                    ? "border-good-500/40 bg-good-500/10 text-good-300"
                    : "border-ink-700 text-mist-400 hover:text-mist-200"
                }`}
                onClick={() => setSource(null)}
              >
                Every source
              </button>
              {sources.map((facet) => (
                <button
                  key={facet.value}
                  className={`rounded-md border px-2.5 py-1 text-2xs transition-colors ${
                    source === facet.value
                      ? "border-good-500/40 bg-good-500/10 text-good-300"
                      : "border-ink-700 text-mist-400 hover:text-mist-200"
                  }`}
                  onClick={() => setSource(facet.value)}
                >
                  {SOURCE_LABELS[facet.value] ?? facet.value}{" "}
                  <span className="tnum text-mist-600">{facet.count}</span>
                </button>
              ))}
            </div>
          </Panel>
        )}

        {apps.length > 0 && (
          <Panel title="By application" hint="Click one to filter the stream below.">
            <div className="flex flex-wrap gap-2 px-4 py-3">
              <button
                className={`rounded-md border px-2.5 py-1 text-2xs transition-colors ${
                  app === null
                    ? "border-accent-500/40 bg-accent-500/10 text-accent-300"
                    : "border-ink-700 text-mist-400 hover:text-mist-200"
                }`}
                onClick={() => setApp(null)}
              >
                Everything
              </button>
              {apps.map((facet) => (
                <button
                  key={facet.value}
                  className={`rounded-md border px-2.5 py-1 text-2xs transition-colors ${
                    app === facet.value
                      ? "border-accent-500/40 bg-accent-500/10 text-accent-300"
                      : "border-ink-700 text-mist-400 hover:text-mist-200"
                  }`}
                  onClick={() => setApp(facet.value)}
                >
                  {facet.value} <span className="tnum text-mist-600">{facet.count}</span>
                </button>
              ))}
            </div>
          </Panel>
        )}

        <Panel
          title="The stream"
          hint="Newest first, refreshing every few seconds."
          actions={
            <span className="text-2xs text-mist-500">
              showing {shown.length.toLocaleString()}
            </span>
          }
        >
          {shown.length === 0 ? (
            <Empty
              title="Nothing observed yet"
              hint="Start watching on the Dashboard, or import an activity log, and events will appear here."
            />
          ) : (
            <ul className="divide-y divide-ink-800">
              {shown.map((event) => (
                <EventRow key={event.id} event={event} />
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}

function EventRow({ event }: { event: ActivityEvent }) {
  // The payload keys are shown, not the values: what was collected is the
  // interesting part, and a value could carry something personal.
  const fields = Object.keys(event.payload ?? {}).filter((k) => k !== "workflow_hint");
  const seconds = event.duration_ms / 1000;

  return (
    <li className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-2">
      <span className="tnum w-20 shrink-0 text-2xs text-mist-600">
        {relativeTime(event.timestamp)}
      </span>
      <Badge tone="neutral">{event.app}</Badge>
      <span className="text-2xs font-medium text-mist-200">{event.action}</span>
      <span className="text-2xs text-mist-400">{event.object_type.replace(/_/g, " ")}</span>
      <span className="tnum text-2xs text-mist-600">
        {seconds < 60 ? `${seconds.toFixed(0)}s` : `${(seconds / 60).toFixed(1)}m`}
      </span>
      {fields.length > 0 && (
        <span className="truncate text-2xs text-mist-600">{fields.join(" · ")}</span>
      )}
    </li>
  );
}

function Tile({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="panel px-4 py-3.5">
      <p className="eyebrow">{label}</p>
      <p className="metric mt-1.5 text-2xl text-mist-100">{value}</p>
      <p className="mt-1.5 text-2xs leading-snug text-mist-500">{hint}</p>
    </div>
  );
}
