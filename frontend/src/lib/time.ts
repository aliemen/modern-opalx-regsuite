/** Compact "12m 04s" / "1h 05m" label for a span in seconds. */
export function formatSeconds(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  if (h > 0) return `${h}h ${(m % 60).toString().padStart(2, "0")}m`;
  if (m > 0) return `${m}m ${(s % 60).toString().padStart(2, "0")}s`;
  return `${s}s`;
}

/** Seconds between two ISO timestamps, or null when the end is missing. */
export function secondsBetween(start: string, end: string | null): number | null {
  if (!end) return null;
  return (new Date(end).getTime() - new Date(start).getTime()) / 1000;
}

/** "just now" / "12m ago" / "3h ago" / "2d ago" relative to *now*. */
export function relativeTime(iso: string, now: number = Date.now()): string {
  const mins = Math.floor((now - new Date(iso).getTime()) / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}
