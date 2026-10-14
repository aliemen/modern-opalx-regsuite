export type TestStatus =
  | "running"
  | "passed"
  | "failed"
  | "broken"
  | "cancelled"
  | "skipped";

export interface TestInfo {
  name: string;
  status: TestStatus;
  startTime: number;
  durationMs: number | null;
}

/**
 * Apply one pipeline.log line to the regression tracker state. Returns `prev`
 * unchanged for unrelated lines so React can skip the re-render.
 */
export function applyTrackerLine(prev: TestInfo[], line: string, now: number): TestInfo[] {
  const skipMatch = line.match(/\[regression\] SKIP (\S+)/);
  if (skipMatch) {
    const name = skipMatch[1];
    if (prev.some((t) => t.name === name)) return prev;
    return [...prev, { name, status: "skipped", startTime: now, durationMs: null }];
  }
  const startMatch = line.match(/\[regression\] START (\S+)/);
  if (startMatch) {
    const name = startMatch[1];
    if (prev.some((t) => t.name === name)) return prev;
    return [...prev, { name, status: "running", startTime: now, durationMs: null }];
  }
  const endMatch = line.match(/\[regression\] END (\S+) state=(\S+)/);
  if (!endMatch) return prev;
  const name = endMatch[1];
  const state = endMatch[2] as TestStatus;
  // The backend embeds duration_ms in END lines so late subscribers still show
  // the right time; fall back to the local clock for older runs.
  const durationMatch = line.match(/\bduration_ms=(\d+)\b/);
  const authoritativeMs = durationMatch ? parseInt(durationMatch[1], 10) : null;
  const existing = prev.find((t) => t.name === name);
  if (!existing) {
    // Late subscriber: START scrolled off before we connected.
    return [...prev, { name, status: state, startTime: now, durationMs: authoritativeMs }];
  }
  return prev.map((t) =>
    t.name === name && t.status === "running"
      ? { ...t, status: state, durationMs: authoritativeMs ?? now - t.startTime }
      : t,
  );
}
