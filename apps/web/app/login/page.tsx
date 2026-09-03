"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useCurrentUser, useLogin, useLoginUsers } from "@/lib/api/queries";

/**
 * Sign-in for the shared demo deployment.
 *
 * Each person gets their own database, so what they upload and discover is
 * theirs alone. The password is shared across the named accounts, which is a
 * demo trade-off rather than a security model — the separation here is between
 * colleagues, not against an attacker, and the page says so rather than
 * implying otherwise.
 */
export default function LoginPage() {
  const router = useRouter();
  const users = useLoginUsers();
  const login = useLogin();
  const me = useCurrentUser();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  // Already signed in: don't make someone log in twice.
  if (me.data?.signed_in) {
    router.replace("/dashboard");
    return null;
  }

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!username || !password) return;
    login.mutate({ username, password }, { onSuccess: () => router.replace("/dashboard") });
  };

  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-ink-950 px-6">
      <div
        aria-hidden
        className="pointer-events-none fixed left-1/2 top-0 h-[30rem] w-[40rem] -translate-x-1/2 animate-drift rounded-full bg-good-600/[0.10] blur-[110px]"
      />

      <div className="relative w-full max-w-sm">
        <div className="mb-8 flex items-center gap-2.5">
          <span aria-hidden className="relative flex h-3.5 w-3.5">
            <span className="absolute inset-0 animate-pulse-ring rounded-full border-2 border-good-500" />
          </span>
          <span className="flex flex-col leading-none">
            <span className="text-xl font-semibold tracking-tight text-mist-100">Kriyā AI</span>
            <span className="mt-1.5 text-2xs text-mist-600">
              From Repetitive Work to Intelligent Action
            </span>
          </span>
        </div>

        <h1 className="text-2xl font-semibold tracking-tight text-mist-100">Sign in</h1>
        <p className="mt-2 text-2xs leading-relaxed text-mist-500">
          Pick your name. Everything you upload and discover stays in your own workspace —
          nobody else signed in here can see it.
        </p>

        <form onSubmit={submit} className="mt-7 space-y-4">
          <div>
            <label className="eyebrow mb-2 block text-mist-500" htmlFor="who">
              Who are you
            </label>
            <select
              id="who"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              className="w-full appearance-none rounded-md border border-ink-700 bg-ink-900 px-3 py-2.5 text-xs text-mist-100 focus:border-good-500/50 focus:outline-none"
            >
              <option value="">Select your name…</option>
              {(users.data?.users ?? []).map((option) => (
                <option key={option.username} value={option.username}>
                  {option.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="eyebrow mb-2 block text-mist-500" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              className="w-full rounded-md border border-ink-700 bg-ink-900 px-3 py-2 text-xs text-mist-100 placeholder:text-mist-600 focus:border-good-500/50 focus:outline-none"
              placeholder="••••••••"
            />
          </div>

          {login.error && (
            <p className="text-2xs text-bad-400">
              {login.error instanceof Error ? login.error.message : "Could not sign in."}
            </p>
          )}

          <button
            type="submit"
            disabled={!username || !password || login.isPending}
            className="btn-primary w-full justify-center px-4 py-2.5 text-xs disabled:opacity-40"
          >
            {login.isPending ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p className="mt-6 text-2xs leading-relaxed text-mist-600">
          A shared demo deployment. Workspaces are separated per person, and data lives on the
          instance, so treat it as a demo rather than a place for anything real.
        </p>
      </div>
    </div>
  );
}
