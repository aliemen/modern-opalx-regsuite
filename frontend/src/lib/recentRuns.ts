import type { RunIndexEntry } from "../api/results";
import type { CurrentRunStatus, MachineStatus, QueuedRunItem } from "../api/runs";

/**
 * One row of the dashboard "Recent runs" table. Running and queued runs exist
 * only in the in-memory queue state until they finish, so the table merges
 * the queue snapshot with the newest finished runs from the runs index.
 */
export type RecentRow =
  | { kind: "running"; key: string; run: CurrentRunStatus; machineLabel: string }
  | {
      kind: "queued";
      key: string;
      item: QueuedRunItem;
      position: number;
      machineLabel: string;
    }
  | { kind: "finished"; key: string; run: RunIndexEntry };

/** `run_id` is a 1s timestamp and can repeat across cells, so key on all three. */
export function runKey(r: { branch: string; arch: string; run_id: string }): string {
  return `${r.branch}::${r.arch}::${r.run_id}`;
}

function machineLabel(
  machineId: string,
  r: { machine_name?: string | null }
): string {
  if (r.machine_name) return r.machine_name;
  return machineId === "local" ? "Local" : machineId;
}

/**
 * Running rows first (newest start first), then queued rows (oldest queued
 * first, with their position in the machine queue), then finished runs.
 * With *me* set, live rows are limited to runs triggered by that user; the
 * finished list is expected to be filtered server-side already.
 */
export function mergeRecentRuns(
  machines: MachineStatus[],
  finished: RunIndexEntry[],
  me: string | null
): RecentRow[] {
  const mine = (triggeredBy?: string | null) => me === null || triggeredBy === me;

  const running: RecentRow[] = machines
    .flatMap((m) =>
      m.active_run && mine(m.active_run.triggered_by)
        ? [
            {
              kind: "running" as const,
              key: runKey(m.active_run),
              run: m.active_run,
              machineLabel: machineLabel(m.machine_id, m.active_run),
            },
          ]
        : []
    )
    .sort((a, b) => b.run.started_at.localeCompare(a.run.started_at));

  const queued = machines
    .flatMap((m) =>
      m.queue.map((item, i) => ({
        kind: "queued" as const,
        key: runKey(item),
        item,
        position: i + 1,
        machineLabel: machineLabel(m.machine_id, item),
      }))
    )
    .filter((row) => mine(row.item.triggered_by))
    .sort((a, b) => a.item.queued_at.localeCompare(b.item.queued_at));

  const live: RecentRow[] = [...running, ...queued];
  const seen = new Set(live.map((r) => r.key));
  const done: RecentRow[] = [];
  for (const run of finished) {
    const key = runKey(run);
    if (seen.has(key)) continue;
    seen.add(key);
    done.push({ kind: "finished", key, run });
  }
  return [...live, ...done];
}
