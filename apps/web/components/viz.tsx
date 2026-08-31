"use client";

/**
 * Small visual encodings for dense rows.
 *
 * These exist because a screen of numbers is read one value at a time, while a
 * screen of bars is read at a glance. The console's job is to rank workflows by
 * what automating them returns, and ranking is exactly what a proportional bar
 * communicates faster than a figure does.
 */

/** A proportional bar, scaled against the largest value in its group. */
export function ProportionBar({
  value,
  max,
  secondary = 0,
  tone = "accent",
  label,
}: {
  value: number;
  max: number;
  /** Rendered as a second segment continuing from the first — e.g. tax on top of hours. */
  secondary?: number;
  tone?: "accent" | "good" | "warn";
  label?: string;
}) {
  const total = Math.max(max, 1);
  const primary = Math.max(0, Math.min(1, value / total));
  const extra = Math.max(0, Math.min(1 - primary, secondary / total));

  const fill = { accent: "bg-accent-500", good: "bg-good-500", warn: "bg-warn-500" }[tone];

  return (
    <div
      className="flex h-1.5 w-full overflow-hidden rounded-full bg-ink-800"
      role="img"
      aria-label={label}
    >
      <div className={`bar-fill h-full ${fill}`} style={{ width: `${primary * 100}%` }} />
      {extra > 0 && (
        <div
          className="bar-fill h-full bg-warn-500/55"
          style={{ width: `${extra * 100}%` }}
        />
      )}
    </div>
  );
}

/**
 * Inline sparkline. Renders an area fill plus an emphasised endpoint, because a
 * bare polyline reads as decoration while a marked endpoint reads as "this is
 * where it stands now".
 */
export function Sparkline({
  points,
  width = 88,
  height = 24,
  tone = "accent",
}: {
  points: number[];
  width?: number;
  height?: number;
  tone?: "accent" | "good" | "warn" | "bad";
}) {
  if (points.length < 2) {
    return (
      <div
        className="flex items-center text-2xs text-mist-600"
        style={{ width, height }}
        aria-hidden
      >
        —
      </div>
    );
  }

  const stroke = {
    accent: "#3b82f6",
    good: "#10b981",
    warn: "#f59e0b",
    bad: "#ef4444",
  }[tone];

  const min = Math.min(...points);
  const max = Math.max(...points);
  // A flat series must not collapse onto the baseline; centre it instead.
  const span = max - min || 1;
  const pad = 2;
  const usable = height - pad * 2;

  const coords = points.map((value, index) => {
    const x = (index / (points.length - 1)) * width;
    const y = pad + usable - ((value - min) / span) * usable;
    return [x, y] as const;
  });

  const line = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${line} L${width},${height} L0,${height} Z`;
  const [lastX, lastY] = coords[coords.length - 1];
  const gradientId = `spark-${tone}-${points.length}-${Math.round(points[0] * 1000)}`;

  return (
    <svg width={width} height={height} className="overflow-visible" aria-hidden>
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.28" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gradientId})`} />
      <path
        d={line}
        fill="none"
        stroke={stroke}
        strokeWidth="1.25"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle cx={lastX} cy={lastY} r="2" fill={stroke} />
      <circle cx={lastX} cy={lastY} r="4" fill={stroke} opacity="0.22" />
    </svg>
  );
}

/**
 * A compact severity/state stripe. Encodes state in form as well as colour, so
 * it survives being printed or read by someone who cannot separate the hues.
 */
export function StateStripe({
  state,
}: {
  state: "good" | "warn" | "bad" | "idle";
}) {
  const cls = {
    good: "bg-good-500",
    warn: "bg-warn-500",
    bad: "bg-bad-500",
    idle: "bg-ink-600",
  }[state];
  return <span className={`block h-full w-0.5 shrink-0 rounded-full ${cls}`} aria-hidden />;
}

/** Segmented bar: how the instances of a workflow split across its variants. */
export function VariantBar({
  shares,
  max = 6,
}: {
  shares: number[];
  max?: number;
}) {
  const shown = shares.slice(0, max);
  const rest = shares.slice(max).reduce((sum, s) => sum + s, 0);
  const segments = rest > 0 ? [...shown, rest] : shown;

  return (
    <div className="flex h-1.5 w-full gap-px overflow-hidden rounded-full bg-ink-800">
      {segments.map((share, index) => (
        <div
          key={index}
          className="bar-fill h-full first:rounded-l-full last:rounded-r-full"
          style={{
            width: `${Math.max(share, 0) * 100}%`,
            // The dominant variant is the signal; the tail fades back so the
            // eye reads "one common path plus noise" rather than seven equals.
            backgroundColor: index === 0 ? "#3b82f6" : "#2a3140",
            opacity: index === 0 ? 1 : Math.max(0.35, 1 - index * 0.12),
          }}
        />
      ))}
    </div>
  );
}
