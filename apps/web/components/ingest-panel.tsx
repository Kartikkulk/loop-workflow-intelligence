"use client";

import { useRef, useState } from "react";
import { useDescribeWorkflow, useUploadLog } from "@/lib/api/queries";
import { Panel } from "./ui";

const EXAMPLE =
  "Every Monday I download the vendor ageing report, filter for rows more than 30 days overdue, update the summary tab, and email it to the finance leads.";

/**
 * The two ingestion paths, side by side.
 *
 * The prose path is not a gimmick: most teams have no usable activity log, and
 * describing the task out loud is the only input they can actually provide. It
 * doubles as the fallback if a file upload misbehaves during a demo.
 */
export function IngestPanel({ onDone }: { onDone?: () => void }) {
  const [description, setDescription] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const describe = useDescribeWorkflow();
  const upload = useUploadLog();

  const result = describe.data ?? upload.data;
  const error = describe.error ?? upload.error;
  const busy = describe.isPending || upload.isPending;

  return (
    <Panel
      title="Add activity data"
      hint="Both paths land in the same canonical event stream, so detection treats them identically."
    >
      <div className="grid gap-5 px-4 py-4 lg:grid-cols-2">
        <div>
          <p className="eyebrow mb-2">Upload an activity log</p>
          <p className="mb-3 text-2xs leading-relaxed text-mist-500">
            CSV or JSONL. Needs at minimum <span className="mono">user_id</span>,{" "}
            <span className="mono">timestamp</span>, <span className="mono">app</span>,{" "}
            <span className="mono">action</span>, <span className="mono">object_type</span>.
            Common tool vocabularies are mapped automatically.
          </p>
          <input
            ref={fileInput}
            type="file"
            accept=".csv,.jsonl,.ndjson,.json"
            className="block w-full cursor-pointer rounded-md border border-ink-600 bg-ink-850 px-3 py-2 text-2xs text-mist-400 file:mr-3 file:rounded file:border-0 file:bg-ink-700 file:px-2.5 file:py-1 file:text-2xs file:font-medium file:text-mist-200"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) upload.mutate({ file });
            }}
            disabled={busy}
          />
        </div>

        <div>
          <p className="eyebrow mb-2">Or describe the task</p>
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder={EXAMPLE}
            rows={4}
            className="w-full resize-none rounded-md border border-ink-600 bg-ink-850 px-3 py-2 text-xs leading-relaxed text-mist-200 placeholder:text-mist-600 focus:border-accent-500 focus:outline-none"
            disabled={busy}
          />
          <div className="mt-2 flex items-center gap-2">
            <button
              className="btn-primary"
              disabled={busy || description.trim().length < 10}
              onClick={() => describe.mutate({ description })}
            >
              {describe.isPending ? "Synthesising…" : "Detect from description"}
            </button>
            <button
              className="btn-ghost"
              disabled={busy}
              onClick={() => setDescription(EXAMPLE)}
            >
              Use example
            </button>
          </div>
        </div>
      </div>

      {(result || error) && (
        <div className="border-t border-ink-700 px-4 py-3">
          {error && (
            <p className="text-2xs text-bad-400">
              {error instanceof Error ? error.message : String(error)}
            </p>
          )}
          {result && (
            <div className="flex flex-wrap items-center gap-4 text-2xs">
              <span className="text-good-400">
                {result.events_ingested.toLocaleString()} events ingested
              </span>
              {result.events_rejected > 0 && (
                <span className="text-warn-400">{result.events_rejected} rows rejected</span>
              )}
              <span className="text-mist-400">
                {result.clusters_detected} workflows now detected
              </span>
              <span className="mono">via {result.source}</span>
              {onDone && (
                <button className="link ml-auto text-2xs" onClick={onDone}>
                  Done
                </button>
              )}
            </div>
          )}
          {result?.errors && result.errors.length > 0 && (
            <ul className="mt-2 space-y-0.5">
              {result.errors.slice(0, 5).map((message) => (
                <li key={message} className="mono text-mist-500">
                  {message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Panel>
  );
}
