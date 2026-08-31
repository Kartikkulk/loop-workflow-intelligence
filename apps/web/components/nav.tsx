"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useApprovalCount, useSystem } from "@/lib/api/queries";

/**
 * The navigation is the product's story, in order.
 *
 * Connect the tools you already use, let the agent watch them, see what it
 * found, approve what it proposes, and only then does anything run. Ordering
 * these by journey rather than by feature means the sidebar itself explains
 * how the product works to someone seeing it for the first time.
 */
const STEPS = [
  {
    href: "/integrations",
    step: "1",
    label: "Integrations",
    hint: "Connect your tools",
  },
  {
    href: "/",
    step: "2",
    label: "Discovery",
    hint: "What we found",
  },
  {
    href: "/approvals",
    step: "3",
    label: "Approvals",
    hint: "Needs your yes",
  },
  {
    href: "/automations",
    step: "4",
    label: "Automations",
    hint: "Running now",
  },
];

const REST = [
  { href: "/roi", label: "Impact", hint: "Effort reduced" },
  { href: "/system", label: "System", hint: "Connectors and config" },
];

export function Nav() {
  const pathname = usePathname();
  const { data: system } = useSystem();
  const pending = useApprovalCount();

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <nav className="sticky top-0 flex h-screen w-56 shrink-0 flex-col border-r border-ink-700 bg-ink-950">
      <div className="border-b border-ink-700 px-5 py-5">
        <Link href="/" className="block">
          <div className="flex items-center gap-2">
            <LoopMark />
            <span className="text-sm font-semibold tracking-tight text-mist-100">LOOP</span>
          </div>
          <p className="mt-1.5 text-2xs leading-snug text-mist-500">Workflow intelligence</p>
        </Link>
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-3">
        <p className="eyebrow px-3 pb-2">How it works</p>

        <div className="relative">
          {/* A rail joining the four steps, so they read as one sequence
              rather than four unrelated destinations. */}
          <span
            className="absolute left-[1.32rem] top-3 bottom-3 w-px bg-ink-700"
            aria-hidden
          />

          {STEPS.map((link) => {
            const active = isActive(link.href);
            const badge = link.href === "/approvals" ? pending : 0;
            return (
              <Link
                key={link.href}
                href={link.href}
                className={`relative flex items-center gap-2.5 rounded-md py-2 pl-3 pr-3 transition-colors ${
                  active
                    ? "bg-ink-800 text-mist-100"
                    : "text-mist-400 hover:bg-ink-900 hover:text-mist-200"
                }`}
              >
                <span
                  className={`relative z-10 flex h-[1.15rem] w-[1.15rem] shrink-0 items-center justify-center rounded-full border text-[9px] font-semibold transition-colors ${
                    active
                      ? "border-accent-500 bg-accent-500 text-white"
                      : "border-ink-600 bg-ink-950 text-mist-500"
                  }`}
                >
                  {link.step}
                </span>
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
        </div>

        <p className="eyebrow px-3 pb-2 pt-4">Reporting</p>
        {REST.map((link) => {
          const active = isActive(link.href);
          return (
            <Link
              key={link.href}
              href={link.href}
              className={`flex items-center rounded-md px-3 py-2 transition-colors ${
                active
                  ? "bg-ink-800 text-mist-100"
                  : "text-mist-400 hover:bg-ink-900 hover:text-mist-200"
              }`}
            >
              <span className="flex flex-col">
                <span className="text-xs font-medium">{link.label}</span>
                <span className="text-2xs text-mist-500">{link.hint}</span>
              </span>
            </Link>
          );
        })}
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
