export function fmtNum(n: number | null | undefined, digits = 4) {
  if (n === null || n === undefined) return "—";
  return n.toExponential(digits);
}

export function fmtDate(d: string | null) {
  if (!d) return "—";
  return new Date(d).toLocaleString();
}

export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

export function duration(start: string, end: string | null) {
  if (!end) return "—";
  const s = Math.floor((new Date(end).getTime() - new Date(start).getTime()) / 1000);
  const m = Math.floor(s / 60);
  return `${m}m ${(s % 60).toString().padStart(2, "0")}s`;
}
