"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useCurrentUser, useLogout } from "@/lib/api/queries";

/**
 * Who is signed in, and the way out.
 *
 * Which workspace you are in matters more here than in most products: every
 * person's uploads and discoveries are separate, so a screen that shows no
 * data is ambiguous — is this workspace empty, or am I signed in as somebody
 * else? Naming the account on every screen answers that without being asked.
 */
export function ProfileMenu() {
  const me = useCurrentUser();
  const logout = useLogout();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on an outside click or Escape — a menu that can only be dismissed by
  // choosing something from it is a trap.
  useEffect(() => {
    if (!open) return;
    const onPointer = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!me.data?.signed_in) return null;

  const name = me.data.name || me.data.username;
  const initials = name
    .split(" ")
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <div ref={ref} className="relative border-t border-ink-700 px-3 py-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-ink-800"
      >
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-good-500/15 text-2xs font-semibold text-good-300">
          {initials}
        </span>
        <span className="flex min-w-0 flex-col">
          <span className="truncate text-2xs font-medium text-mist-200">{name}</span>
          <span className="text-2xs text-mist-600">Your workspace</span>
        </span>
        <span aria-hidden className="ml-auto text-2xs text-mist-600">
          {open ? "▾" : "▸"}
        </span>
      </button>

      {open && (
        <div
          role="menu"
          className="absolute bottom-full left-3 right-3 mb-1 overflow-hidden rounded-lg border border-ink-600 bg-ink-850 shadow-lift"
        >
          <div className="border-b border-ink-700 px-3 py-2.5">
            <p className="text-2xs font-medium text-mist-200">{name}</p>
            <p className="mt-0.5 text-2xs leading-relaxed text-mist-600">
              Uploads and discoveries here are yours alone.
            </p>
          </div>
          <button
            type="button"
            role="menuitem"
            disabled={logout.isPending}
            onClick={() =>
              logout.mutate(undefined, { onSuccess: () => router.replace("/login") })
            }
            className="w-full px-3 py-2.5 text-left text-2xs text-mist-300 transition-colors hover:bg-ink-800 hover:text-bad-300 disabled:opacity-50"
          >
            {logout.isPending ? "Signing out…" : "Sign out"}
          </button>
        </div>
      )}
    </div>
  );
}
