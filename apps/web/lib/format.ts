/** Display formatting. Kept in one place so units are consistent everywhere. */

export function hours(value: number): string {
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  if (value >= 100) return Math.round(value).toLocaleString();
  return value.toFixed(1);
}

export function duration(ms: number): string {
  const totalSeconds = Math.round(ms / 1000);
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes < 60) return seconds ? `${minutes}m ${seconds}s` : `${minutes}m`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export function percent(value: number, digits = 0): string {
  return `${(value * 100).toFixed(digits)}%`;
}

/** Rupees from paise. All money is stored in minor units as integers. */
export function money(minorUnits: number): string {
  return `₹${(minorUnits / 100).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

export function stepLabel(token: string): { app: string; action: string; object: string } {
  const [app = "", action = "", object = ""] = token.split(":");
  return { app, action, object: object.replace(/_/g, " ") };
}

export function initials(userId: string): string {
  return userId.replace(/^u_/, "").slice(0, 2).toUpperCase();
}

export function displayName(userId: string): string {
  const bare = userId.replace(/^u_/, "").replace(/_/g, " ");
  return bare.charAt(0).toUpperCase() + bare.slice(1);
}

export function teamLabel(team: string): string {
  return team
    .replace(/_/g, " ")
    .replace(/\bfp and a\b/i, "FP&A")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function formatFieldValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return value.toLocaleString();
  const text = String(value);
  return text.length > 60 ? `${text.slice(0, 57)}…` : text;
}
