"use client";

import Link from "next/link";
import { initials } from "@/lib/format";

export function PageHeader({
  eyebrow,
  title,
  subtitle,
  actions,
  back,
}: {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
  back?: { href: string; label: string };
}) {
  return (
    <header className="border-b border-ink-700 bg-ink-950/70 px-8 py-6 backdrop-blur">
      {back && (
        <Link
          href={back.href}
          className="mb-3 inline-flex items-center gap-1.5 text-2xs text-mist-500 transition-colors hover:text-mist-300"
        >
          <span aria-hidden>←</span> {back.label}
        </Link>
      )}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          {eyebrow && <p className="eyebrow mb-1.5">{eyebrow}</p>}
          <h1 className="text-xl font-semibold tracking-tight text-mist-100">{title}</h1>
          {subtitle && (
            <p className="mt-1.5 max-w-2xl text-xs leading-relaxed text-mist-400">{subtitle}</p>
          )}
        </div>
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
}

export function Stat({
  label,
  value,
  unit,
  hint,
  tone = "default",
}: {
  label: string;
  value: string;
  unit?: string;
  hint?: string;
  tone?: "default" | "good" | "warn" | "bad" | "accent";
}) {
  const toneClass = {
    default: "text-mist-100",
    good: "text-good-400",
    warn: "text-warn-400",
    bad: "text-bad-400",
    accent: "text-accent-400",
  }[tone];

  return (
    <div className="panel px-4 py-3.5">
      <p className="eyebrow">{label}</p>
      <p className={`tnum mt-2 text-2xl font-semibold leading-none ${toneClass}`}>
        {value}
        {unit && <span className="ml-1 text-xs font-normal text-mist-500">{unit}</span>}
      </p>
      {hint && <p className="mt-2 text-2xs leading-snug text-mist-500">{hint}</p>}
    </div>
  );
}

export function Gauge({ value, label }: { value: number; label?: string }) {
  const clamped = Math.max(0, Math.min(1, value));
  const tone =
    clamped >= 0.6 ? "#10b981" : clamped >= 0.4 ? "#f59e0b" : "#ef4444";
  const circumference = 2 * Math.PI * 26;

  return (
    <div className="flex items-center gap-3">
      <div className="relative h-16 w-16 shrink-0">
        <svg viewBox="0 0 64 64" className="h-16 w-16 -rotate-90">
          <circle cx="32" cy="32" r="26" fill="none" stroke="#1e232c" strokeWidth="6" />
          <circle
            cx="32"
            cy="32"
            r="26"
            fill="none"
            stroke={tone}
            strokeWidth="6"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={circumference * (1 - clamped)}
            style={{ transition: "stroke-dashoffset 700ms cubic-bezier(0.16,1,0.3,1)" }}
          />
        </svg>
        <span className="tnum absolute inset-0 flex items-center justify-center text-xs font-semibold text-mist-100">
          {Math.round(clamped * 100)}
        </span>
      </div>
      {label && <p className="text-2xs leading-snug text-mist-400">{label}</p>}
    </div>
  );
}

export function AvatarRow({ userIds, max = 6 }: { userIds: string[]; max?: number }) {
  const shown = userIds.slice(0, max);
  const extra = userIds.length - shown.length;
  return (
    <div className="flex items-center">
      {shown.map((id, index) => (
        <span
          key={id}
          title={id}
          className="tnum -ml-1.5 flex h-6 w-6 items-center justify-center rounded-full border border-ink-850 bg-ink-700 text-[9px] font-semibold text-mist-200 first:ml-0"
          style={{ zIndex: shown.length - index }}
        >
          {initials(id)}
        </span>
      ))}
      {extra > 0 && (
        <span className="ml-1.5 text-2xs font-medium text-mist-500">+{extra}</span>
      )}
    </div>
  );
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "good" | "warn" | "bad" | "accent";
}) {
  const cls = {
    neutral: "border-ink-600 bg-ink-800 text-mist-300",
    good: "border-good-500/40 bg-good-500/10 text-good-400",
    warn: "border-warn-500/40 bg-warn-500/10 text-warn-400",
    bad: "border-bad-500/40 bg-bad-500/10 text-bad-400",
    accent: "border-accent-500/40 bg-accent-500/10 text-accent-300",
  }[tone];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-2xs font-medium ${cls}`}
    >
      {children}
    </span>
  );
}

export function Panel({
  title,
  hint,
  actions,
  children,
  className = "",
}: {
  title?: string;
  hint?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      {(title || actions) && (
        <div className="flex items-start justify-between gap-3 border-b border-ink-700 px-4 py-3">
          <div className="min-w-0">
            {title && <h2 className="text-xs font-semibold text-mist-200">{title}</h2>}
            {hint && <p className="mt-0.5 text-2xs leading-snug text-mist-500">{hint}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="px-4 py-10 text-center">
      <p className="text-xs font-medium text-mist-300">{title}</p>
      {hint && <p className="mx-auto mt-1.5 max-w-md text-2xs leading-relaxed text-mist-500">{hint}</p>}
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 px-4 py-10 text-2xs text-mist-500">
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent-500" />
      {label}…
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="panel border-bad-500/30 bg-bad-500/5 px-4 py-3">
      <p className="text-xs font-medium text-bad-400">Something went wrong</p>
      <p className="mt-1 text-2xs leading-relaxed text-mist-400">{message}</p>
    </div>
  );
}

/** A horizontal meter. Used for confidence, coverage and accuracy. */
export function Meter({
  value,
  tone = "accent",
  height = "h-1.5",
}: {
  value: number;
  tone?: "accent" | "good" | "warn" | "bad";
  height?: string;
}) {
  const bg = { accent: "bg-accent-500", good: "bg-good-500", warn: "bg-warn-500", bad: "bg-bad-500" }[
    tone
  ];
  return (
    <div className={`w-full overflow-hidden rounded-full bg-ink-700 ${height}`}>
      <div
        className={`bar-fill h-full rounded-full ${bg}`}
        style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }}
      />
    </div>
  );
}
