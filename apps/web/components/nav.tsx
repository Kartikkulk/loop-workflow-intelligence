"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useExceptions, usePatches, useSystem } from "@/lib/api/queries";

const LINKS = [
  { href: "/", label: "Discovery", hint: "Detected workflows" },
  { href: "/automations", label: "Automations", hint: "Trust ladder" },
  { href: "/exceptions", label: "Review queue", hint: "Exceptions and patches" },
  { href: "/roi", label: "Impact", hint: "Hours and coverage" },
  { href: "/sources", label: "Observation", hint: "What LOOP can see" },
  { href: "/system", label: "System", hint: "Connectors and config" },
];

export function Nav() {
  const pathname = usePathname();
  const { data: exceptions } = useExceptions();
  const { data: patches } = usePatches();
  const { data: system } = useSystem();

  const pending = (exceptions?.open_count ?? 0) + (patches?.proposed_count ?? 0);

  return (
    <nav className="sticky top-0 flex h-screen w-56 shrink-0 flex-col border-r border-ink-700 bg-ink-950">
      <div className="border-b border-ink-700 px-5 py-5">
        <Link href="/" className="block">
          <div className="flex items-center gap-2">
            <LoopMark />
            <span className="text-sm font-semibold tracking-tight text-mist-100">LOOP</span>
          </div>
          <p className="mt-1.5 text-2xs leading-snug text-mist-500">
            Workflow intelligence
          </p>
        </Link>
      </div>

      <div className="flex-1 space-y-0.5 px-2 py-3">
        {LINKS.map((link) => {
          const active =
            link.href === "/" ? pathname === "/" : pathname.startsWith(link.href);
          const badge = link.href === "/exceptions" ? pending : 0;
          return (
            <Link
              key={link.href}
              href={link.href}
              className={`group flex items-center justify-between rounded-md px-3 py-2 transition-colors ${
                active
                  ? "bg-ink-800 text-mist-100"
                  : "text-mist-400 hover:bg-ink-900 hover:text-mist-200"
              }`}
            >
              <span className="flex flex-col">
                <span className="text-xs font-medium">{link.label}</span>
                <span className="text-2xs text-mist-500">{link.hint}</span>
              </span>
              {badge > 0 && (
                <span className="tnum rounded-full bg-accent-600 px-1.5 py-0.5 text-2xs font-semibold text-white">
                  {badge}
                </span>
              )}
            </Link>
          );
        })}
      </div>

      <div className="space-y-2 border-t border-ink-700 px-5 py-4 text-2xs text-mist-500">
        <Row label="Events" value={(system?.event_count ?? 0).toLocaleString()} />
        <Row label="Workflows" value={String(system?.cluster_count ?? 0)} />
        <Row
          label="Connectors"
          value={system ? (system.mock_connectors ? "mock" : "live") : "—"}
        />
        <Row label="AI" value={system?.llm_available ? "Claude" : "heuristic"} />
      </div>
    </nav>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span>{label}</span>
      <span className="tnum font-medium text-mist-300">{value}</span>
    </div>
  );
}

function LoopMark() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden>
      <circle cx="9" cy="9" r="7" stroke="#3b82f6" strokeWidth="1.75" />
      <path d="M9 2a7 7 0 0 1 7 7" stroke="#93c5fd" strokeWidth="1.75" strokeLinecap="round" />
      <circle cx="16" cy="9" r="1.75" fill="#3b82f6" />
    </svg>
  );
}
