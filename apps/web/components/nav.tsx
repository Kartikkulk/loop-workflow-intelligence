"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useApprovalCount, useSystem } from "@/lib/api/queries";

/**
 * Seven destinations, in the order the product actually happens.
 *
 * The order is the story: Kriyā AI watches, you see what it saw, it finds
 * something, you approve it, it runs. Connections and Settings sit below
 * because they are set up once and then forgotten.
 *
 * Impact and System are deliberately absent. Their useful numbers moved onto
 * the Dashboard; the pages still resolve so existing links do not break, but
 * nothing sends anyone to a screen of graphs.
 */
const LINKS = [
  { href: "/dashboard", label: "Dashboard", hint: "What's happening" },
  { href: "/activity", label: "Activity", hint: "What Kriyā AI has seen" },
  { href: "/discovery", label: "Discoveries", hint: "Repetitive work found" },
  { href: "/approvals", label: "Approval", hint: "Needs your yes" },
  { href: "/automations", label: "Automation", hint: "Running now" },
];

const FOOTER_LINKS = [
  { href: "/sources", label: "Connections" },
  { href: "/settings", label: "Settings" },
];

export function Nav() {
  const pathname = usePathname();
  const { data: system } = useSystem();
  const pending = useApprovalCount();

  const isActive = (href: string) => pathname.startsWith(href);

  // The landing page is not part of the console and carries no sidebar. Hidden
  // here rather than by giving the marketing route its own layout, so the
  // console's data providers stay mounted and moving between the two does not
  // refetch everything.
  if (pathname === "/" || pathname === "/login") return null;

  return (
    <nav className="sticky top-0 flex h-screen w-56 shrink-0 flex-col border-r border-ink-700 bg-ink-950">
      <div className="border-b border-ink-700 px-5 py-5">
        <Link href="/dashboard" className="block">
          <div className="flex items-center gap-2">
            <LoopMark />
            <span className="text-sm font-semibold tracking-tight text-mist-100">Kriyā AI</span>
          </div>
          <p className="mt-1.5 text-2xs leading-snug text-mist-500">From Repetitive Work to Intelligent Action</p>
        </Link>
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-3">
        {LINKS.map((link) => {
          const active = isActive(link.href);
          const badge = link.href === "/approvals" ? pending : 0;
          return (
            <Link
              key={link.href}
              href={link.href}
              className={`flex items-center gap-2 rounded-md px-3 py-2 transition-colors ${
                active
                  ? "bg-ink-800 text-mist-100"
                  : "text-mist-400 hover:bg-ink-900 hover:text-mist-200"
              }`}
            >
              <span className="flex min-w-0 flex-col">
                <span className="text-xs font-medium">{link.label}</span>
                <span className="truncate text-2xs text-mist-500">{link.hint}</span>
              </span>
              {badge > 0 && (
                <span className="tnum ml-auto rounded-full bg-warn-500 px-1.5 py-0.5 text-2xs font-semibold text-ink-950">
                  {badge}
                </span>
              )}
            </Link>
          );
        })}

        <div className="mt-3 flex gap-1 border-t border-ink-800 px-3 pt-3">
          {FOOTER_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={`rounded px-2 py-1 text-2xs transition-colors ${
                isActive(link.href)
                  ? "bg-ink-800 text-mist-200"
                  : "text-mist-500 hover:text-mist-300"
              }`}
            >
              {link.label}
            </Link>
          ))}
        </div>
      </div>

      <div className="space-y-2 border-t border-ink-700 px-5 py-4 text-2xs text-mist-500">
        <Row label="Events seen" value={(system?.event_count ?? 0).toLocaleString()} />
        <Row label="Workflows" value={String(system?.cluster_count ?? 0)} />
        <Row
          label="Side effects"
          value={system ? (system.mock_connectors ? "mocked" : "live") : "—"}
        />
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
