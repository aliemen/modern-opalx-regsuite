/**
 * Pure data transforms for the dashboard accordion. No React in here so the
 * grouping logic is dumb and easy to test.
 *
 * The same input — a flat list of `LatestRunCell` (one per branch+arch) —
 * is reshaped into top-level groups based on the `groupBy` axis. The card
 * inside each group is identical regardless of axis: only the group header
 * differs.
 */
import type { LatestRunCell } from "../hooks/useLatestRuns";

export type GroupBy = "branch" | "arch" | "date";

export interface Group {
  /** Stable key for accordion open/close state and React keys. */
  key: string;
  /** Human-readable header label. */
  label: string;
  /** "branch" | "arch" | "date" — what kind of group this is. */
  kind: GroupBy;
  /** The cells (latest run per branch+arch) belonging to this group. */
  cells: LatestRunCell[];
}

/**
 * Group cells by the requested axis.
 *
 * For `groupBy="branch"` the master branch is always first, then the rest
 * alphabetical (matches the existing dashboard ordering). For `"arch"` archs
 * are sorted alphabetically. For `"date"` cells are bucketed into Today,
 * Yesterday, This week, Last 30 days, and Older relative to the *now*
 * argument (injected for deterministic testing).
 *
 * @param cells - flat list of latest-run-per-branch+arch cells
 * @param groupBy - axis to group by
 * @param now - reference time for date bucketing (default: `new Date()`)
 */
export function groupRuns(
  cells: LatestRunCell[],
  groupBy: GroupBy,
  now: Date = new Date()
): Group[] {
  if (groupBy === "branch") {
    return groupByBranch(cells);
  }
  if (groupBy === "arch") {
    return groupByArch(cells);
  }
  return groupByDate(cells, now);
}

// ── Branch ──────────────────────────────────────────────────────────────────

function groupByBranch(cells: LatestRunCell[]): Group[] {
  const map = new Map<string, LatestRunCell[]>();
  for (const cell of cells) {
    if (!map.has(cell.branch)) map.set(cell.branch, []);
    map.get(cell.branch)!.push(cell);
  }
  const branches = Array.from(map.keys()).sort((a, b) => {
    if (a === "master") return -1;
    if (b === "master") return 1;
    return a.localeCompare(b);
  });
  return branches.map((branch) => ({
    key: `branch:${branch}`,
    label: branch,
    kind: "branch",
    cells: (map.get(branch) ?? []).sort((a, b) => a.arch.localeCompare(b.arch)),
  }));
}

// ── Architecture ────────────────────────────────────────────────────────────

function groupByArch(cells: LatestRunCell[]): Group[] {
  const map = new Map<string, LatestRunCell[]>();
  for (const cell of cells) {
    if (!map.has(cell.arch)) map.set(cell.arch, []);
    map.get(cell.arch)!.push(cell);
  }
  const archs = Array.from(map.keys()).sort((a, b) => a.localeCompare(b));
  return archs.map((arch) => ({
    key: `arch:${arch}`,
    label: arch,
    kind: "arch",
    cells: (map.get(arch) ?? []).sort((a, b) => {
      if (a.branch === "master") return -1;
      if (b.branch === "master") return 1;
      return a.branch.localeCompare(b.branch);
    }),
  }));
}

// ── Date ────────────────────────────────────────────────────────────────────

const DATE_BUCKETS = [
  "Today",
  "Yesterday",
  "This week",
  "Last 30 days",
  "Older",
  "No runs yet",
] as const;
type DateBucketLabel = (typeof DATE_BUCKETS)[number];

function startOfLocalDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

function dateBucket(startedAt: string | undefined, now: Date): DateBucketLabel {
  if (!startedAt) return "No runs yet";
  const t = new Date(startedAt);
  if (Number.isNaN(t.getTime())) return "No runs yet";

  const todayStart = startOfLocalDay(now);
  const yesterdayStart = new Date(todayStart);
  yesterdayStart.setDate(yesterdayStart.getDate() - 1);
  const sevenDaysAgo = new Date(todayStart);
  sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 6); // includes today → 7-day window
  const thirtyDaysAgo = new Date(todayStart);
  thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 29);

  if (t >= todayStart) return "Today";
  if (t >= yesterdayStart) return "Yesterday";
  if (t >= sevenDaysAgo) return "This week";
  if (t >= thirtyDaysAgo) return "Last 30 days";
  return "Older";
}

function groupByDate(cells: LatestRunCell[], now: Date): Group[] {
  const map = new Map<DateBucketLabel, LatestRunCell[]>();
  for (const cell of cells) {
    const bucket = dateBucket(cell.run?.started_at, now);
    if (!map.has(bucket)) map.set(bucket, []);
    map.get(bucket)!.push(cell);
  }
  // Sort cells within each bucket by recency (most recent first).
  for (const arr of map.values()) {
    arr.sort((a, b) => {
      const ta = a.run?.started_at ? Date.parse(a.run.started_at) : 0;
      const tb = b.run?.started_at ? Date.parse(b.run.started_at) : 0;
      return tb - ta;
    });
  }
  // Always emit groups in canonical order, skipping empty buckets.
  return DATE_BUCKETS.filter((b) => map.has(b)).map((b) => ({
    key: `date:${b}`,
    label: b,
    kind: "date",
    cells: map.get(b) ?? [],
  }));
}
