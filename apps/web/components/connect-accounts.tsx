"use client";

import { useState } from "react";
import { Badge } from "@/components/ui";
import {
  useDisconnect,
  useForgetCredentials,
  useProviders,
  useSaveCredentials,
  useStartConnect,
  useSyncProvider,
} from "@/lib/api/queries";
import { relativeTime } from "@/lib/format";
import type { Provider } from "@/lib/api/types";

/**
 * Connect your own accounts.
 *
 * LOOP runs on one laptop and reads one person's own work, so this is ordinary
 * personal sign-in: press a button, sign in with the account you already use,
 * come back. No administrator has to enable anything.
 *
 * The one unavoidable step is that LOOP has no cloud service behind it and so
 * ships with no client secret of its own — each person registers a personal app
 * once. That is a real cost and this panel does not hide it: the steps are
 * listed, the redirect URI is one click to copy, and the whole thing collapses
 * out of the way the moment it is done.
 *
 * Nothing typed here is ever sent back to the browser. The API reports that a
 * secret is set; it never reports what it is.
 */
export function ConnectAccounts({ onNotice }: { onNotice: (message: string) => void }) {
  const { data, isLoading } = useProviders();

  if (isLoading) {
    return <p className="px-4 py-5 text-2xs text-mist-500">Loading…</p>;
  }
  if (!data) return null;

  return (
    <ul className="divide-y divide-ink-800">
      {data.items.map((provider) => (
        <ProviderRow key={provider.key} provider={provider} onNotice={onNotice} />
      ))}
    </ul>
  );
}

function ProviderRow({
  provider,
  onNotice,
}: {
  provider: Provider;
  onNotice: (message: string) => void;
}) {
  const [setupOpen, setSetupOpen] = useState(false);

  const start = useStartConnect();
  const sync = useSyncProvider();
  const disconnect = useDisconnect();

  const failed = start.error ?? sync.error ?? disconnect.error;

  return (
    <li className="px-4 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-mist-100">{provider.label}</span>
            {provider.connected ? (
              <Badge tone="good">Connected</Badge>
            ) : provider.configured ? (
              <Badge tone="accent">Ready to sign in</Badge>
            ) : (
              <Badge tone="warn">Two-minute setup</Badge>
            )}
          </div>

          <p className="mt-1 max-w-prose text-2xs leading-relaxed text-mist-400">
            {provider.reads}
          </p>

          {provider.connected && (
            <p className="tnum mt-1.5 text-2xs text-mist-500">
              {provider.account_label || "signed in"}
              {provider.last_sync_at
                ? ` · last read ${relativeTime(provider.last_sync_at)} · ${provider.events_imported.toLocaleString()} things you did`
                : " · not read yet"}
            </p>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {provider.connected ? (
            <>
              <button
                className="btn-primary"
                disabled={sync.isPending}
                onClick={() =>
                  sync.mutate(
                    { provider: provider.key },
                    { onSuccess: (result) => onNotice(result.message) },
                  )
                }
              >
                {sync.isPending ? "Reading…" : "Read my activity"}
              </button>
              <button
                className="btn-ghost"
                disabled={disconnect.isPending}
                onClick={() =>
                  disconnect.mutate(
                    { provider: provider.key },
                    { onSuccess: (result) => onNotice(result.message) },
                  )
                }
              >
                Disconnect
              </button>
            </>
          ) : provider.configured ? (
            <>
              <button
                className="btn-primary"
                disabled={start.isPending}
                onClick={() => start.mutate({ provider: provider.key })}
              >
                {start.isPending ? "Opening…" : `Sign in with ${provider.label}`}
              </button>
              <button className="btn-ghost" onClick={() => setSetupOpen(!setupOpen)}>
                {setupOpen ? "Hide setup" : "Setup"}
              </button>
            </>
          ) : (
            <button className="btn-primary" onClick={() => setSetupOpen(!setupOpen)}>
              {setupOpen ? "Hide setup" : "Set it up"}
            </button>
          )}
        </div>
      </div>

      {failed && (
        <p className="mt-2.5 text-2xs leading-relaxed text-bad-400">
          {failed instanceof Error ? failed.message : String(failed)}
        </p>
      )}

      {provider.connected && provider.last_error && (
        <p className="mt-2.5 text-2xs leading-relaxed text-warn-400">
          Last read failed: {provider.last_error}
        </p>
      )}

      {setupOpen && <SetupForm provider={provider} onDone={() => setSetupOpen(false)} />}
    </li>
  );
}

function SetupForm({ provider, onDone }: { provider: Provider; onDone: () => void }) {
  const save = useSaveCredentials();
  const forget = useForgetCredentials();
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [copied, setCopied] = useState(false);

  const ready = clientId.trim().length > 0 && clientSecret.trim().length > 0;

  return (
    <div className="mt-3.5 rounded-md border border-ink-700 bg-ink-900/60 px-3.5 py-3.5">
      <p className="text-2xs leading-relaxed text-mist-400">
        LOOP has no server of its own, so it cannot hold a {provider.label} client secret for
        you — you register a personal app once and it stays on this machine.
      </p>

      <ol className="mt-3 space-y-1.5">
        {provider.setup_steps.map((step, index) => (
          <li key={step} className="flex gap-2.5 text-2xs leading-relaxed text-mist-300">
            <span className="mt-px shrink-0 text-mist-600 tnum">{index + 1}.</span>
            <span>{step}</span>
          </li>
        ))}
      </ol>

      <div className="mt-3">
        <p className="eyebrow">Redirect URI to paste in</p>
        <div className="mt-1.5 flex items-center gap-2">
          <code className="mono min-w-0 flex-1 truncate rounded border border-ink-700 bg-ink-950 px-2 py-1.5">
            {provider.redirect_uri}
          </code>
          <button
            className="btn-ghost shrink-0"
            onClick={() => {
              void navigator.clipboard.writeText(provider.redirect_uri);
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1600);
            }}
          >
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      </div>

      <a className="link mt-3 inline-block text-2xs" href={provider.setup_url} target="_blank" rel="noreferrer">
        Open the {provider.label} console →
      </a>

      <div className="mt-4 grid gap-2.5 sm:grid-cols-2">
        <label className="block">
          <span className="eyebrow">Client ID</span>
          <input
            className="mt-1.5 w-full rounded-md border border-ink-600 bg-ink-850 px-2.5 py-1.5 text-2xs text-mist-200 placeholder:text-mist-600 focus:border-accent-500 focus:outline-none"
            value={clientId}
            placeholder={provider.client_id_hint || "from the provider's console"}
            onChange={(event) => setClientId(event.target.value)}
          />
        </label>
        <label className="block">
          <span className="eyebrow">Client secret</span>
          <input
            type="password"
            autoComplete="off"
            className="mt-1.5 w-full rounded-md border border-ink-600 bg-ink-850 px-2.5 py-1.5 text-2xs text-mist-200 placeholder:text-mist-600 focus:border-accent-500 focus:outline-none"
            value={clientSecret}
            placeholder={provider.has_secret ? "saved — type to replace" : "from the provider's console"}
            onChange={(event) => setClientSecret(event.target.value)}
          />
        </label>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          className="btn-primary"
          disabled={!ready || save.isPending}
          onClick={() =>
            save.mutate(
              {
                provider: provider.key,
                client_id: clientId.trim(),
                client_secret: clientSecret.trim(),
              },
              {
                onSuccess: () => {
                  setClientId("");
                  setClientSecret("");
                  onDone();
                },
              },
            )
          }
        >
          {save.isPending ? "Saving…" : "Save"}
        </button>

        {provider.has_secret && (
          <button
            className="btn-danger"
            disabled={forget.isPending}
            onClick={() => forget.mutate({ provider: provider.key })}
          >
            Forget these
          </button>
        )}

        <p className="text-2xs leading-relaxed text-mist-500">
          Stored in LOOP&rsquo;s database on this machine. Never sent back to this page, never
          committed, never sent anywhere except {provider.label}.
        </p>
      </div>

      {(save.error ?? forget.error) != null && (
        <p className="mt-2 text-2xs text-bad-400">
          {String((save.error ?? forget.error) as Error)}
        </p>
      )}

      <details className="mt-3">
        <summary className="cursor-pointer text-2xs text-mist-500">
          What LOOP will be allowed to read
        </summary>
        <ul className="mt-1.5 space-y-1">
          {provider.scopes.map((scope) => (
            <li key={scope} className="mono">
              {scope}
            </li>
          ))}
        </ul>
        <p className="mt-1.5 text-2xs leading-relaxed text-mist-500">
          Read-only, and only your own account. Nothing here lets LOOP write anything or see a
          colleague&rsquo;s activity.
        </p>
      </details>
    </div>
  );
}
