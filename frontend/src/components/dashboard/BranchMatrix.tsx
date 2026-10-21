import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  Flame,
  GitBranch,
  HelpCircle,
  Search,
  TestTube2,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import type { MatrixCell, MatrixRow } from "../../api/results";
import type { LatestRunCell } from "../../hooks/useLatestRuns";
import type { SelectionHandle } from "../../hooks/useRunSelection";
import { resultsPath } from "../../lib/paths";
import { formatSeconds, relativeTime, secondsBetween } from "../../lib/time";

/** Rows shown before "Show all"; filtering always shows every match. */
export const MATRIX_INITIAL_ROWS = 15;

type SortMode = "recent" | "name";

// Static class map: Tailwind only generates classes it can see literally.
const CELL_STYLE: Record<string, { cls: string; icon: LucideIcon }> = {
  passed: { cls: "bg-passed/15 text-passed", icon: CheckCircle2 },
  failed: { cls: "bg-failed/15 text-failed", icon: XCircle },
  broken: { cls: "bg-broken/15 text-broken", icon: AlertTriangle },
  crashed: { cls: "bg-crashed/15 text-crashed", icon: Flame },
  cancelled: { cls: "bg-cancelled/15 text-cancelled", icon: Ban },
  unknown: { cls: "bg-muted/15 text-muted", icon: HelpCircle },
};

interface BranchMatrixProps {
  rows: MatrixRow[];
  /** `branch::arch` keys currently running, for the live dot. */
  runningCells: Set<string>;
  selection: SelectionHandle;
}

function toCells(row: MatrixRow): LatestRunCell[] {
  return Object.entries(row.cells).map(([arch, cell]) => ({
    branch: row.branch,
    arch,
    run: cell.run,
  }));
}

function cellTitle(branch: string, arch: string, cell: MatrixCell): string {
  const r = cell.run;
  const secs = secondsBetween(r.started_at, r.finished_at);
  return [
    `${branch} / ${arch}: ${r.status}`,
    `Started ${relativeTime(r.started_at)}${secs !== null ? `, took ${formatSeconds(secs)}` : ""}`,
    `Unit ${r.unit_tests_total - r.unit_tests_failed}/${r.unit_tests_total}, ` +
      `regression ${r.regression_passed}/${r.regression_total}` +
      (r.regression_failed ? `, ${r.regression_failed} failed` : "") +
      (r.regression_broken ? `, ${r.regression_broken} broken` : ""),
    `Tests branch: ${r.regtest_branch ?? "unknown"}`,
    `By: ${r.triggered_by ?? "unknown"}`,
    `${cell.run_count} run${cell.run_count !== 1 ? "s" : ""} in this cell`,
  ].join("\n");
}

function CellContent({ cell, running }: { cell: MatrixCell; running: boolean }) {
  const r = cell.run;
  const Icon = (CELL_STYLE[r.status] ?? CELL_STYLE.unknown).icon;
  const counts =
    r.regression_total > 0
      ? `${r.regression_passed}/${r.regression_total}`
      : r.unit_tests_total > 0
        ? `U ${r.unit_tests_total - r.unit_tests_failed}/${r.unit_tests_total}`
        : "";
  return (
    <>
      <Icon size={13} className="shrink-0" aria-label={r.status} />
      <span className="text-fg tabular-nums">{counts}</span>
      {r.regtest_branch && r.regtest_branch !== "master" && (
        <TestTube2 size={10} className="text-muted shrink-0" aria-label="non-master tests branch" />
      )}
      {running && (
        <span
          className="absolute top-1 right-1 w-1.5 h-1.5 rounded-full bg-accent animate-pulse"
          aria-label="running now"
        />
      )}
    </>
  );
}

/**
 * Branch × build overview: one row per branch, one column per arch, each
 * cell the newest run of that pair. Replaces the card accordion on the
 * dashboard; "Select" mode reuses the cell-based bulk archive selection.
 */
export function BranchMatrix({ rows, runningCells, selection }: BranchMatrixProps) {
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState<SortMode>("recent");
  const [showAll, setShowAll] = useState(false);
  const [selecting, setSelecting] = useState(false);

  // Columns: archs used by the most branches first.
  const archs = useMemo(() => {
    const usage = new Map<string, number>();
    for (const row of rows) {
      for (const arch of Object.keys(row.cells)) {
        usage.set(arch, (usage.get(arch) ?? 0) + 1);
      }
    }
    return [...usage.entries()]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([arch]) => arch);
  }, [rows]);

  const sorted = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return rows
      .filter((r) => !needle || r.branch.toLowerCase().includes(needle))
      .sort((a, b) => {
        if (a.branch === "master") return -1;
        if (b.branch === "master") return 1;
        return sort === "name"
          ? a.branch.localeCompare(b.branch)
          : b.last_activity.localeCompare(a.last_activity);
      });
  }, [rows, filter, sort]);

  const limited = !showAll && !filter.trim() && sorted.length > MATRIX_INITIAL_ROWS;
  const visible = limited ? sorted.slice(0, MATRIX_INITIAL_ROWS) : sorted;

  function toggleSelecting() {
    if (selecting) selection.clear();
    setSelecting(!selecting);
  }

  return (
    <section className="bg-surface border border-border rounded-xl overflow-hidden">
      <header className="flex flex-wrap items-center gap-2 px-4 py-3 border-b border-border">
        <h2 className="text-fg font-medium text-sm flex items-center gap-2 mr-auto">
          <GitBranch size={15} className="text-muted" />
          Branches
          <span className="text-muted text-xs font-normal">{rows.length}</span>
        </h2>
        <label className="relative">
          <span className="sr-only">Filter branches</span>
          <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-muted" />
          <input
            type="search"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter…"
            className="w-36 bg-bg border border-border rounded-md text-fg text-xs pl-6 pr-2 py-1.5 focus:outline-none focus:border-accent"
          />
        </label>
        <label>
          <span className="sr-only">Sort branches</span>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as SortMode)}
            className="bg-bg border border-border rounded-md text-fg text-xs px-2 py-1.5 focus:outline-none focus:border-accent"
          >
            <option value="recent">Recent activity</option>
            <option value="name">Name</option>
          </select>
        </label>
        <button
          type="button"
          onClick={toggleSelecting}
          aria-pressed={selecting}
          className={`text-xs px-2.5 py-1.5 rounded-md border transition-colors ${
            selecting
              ? "border-accent/40 bg-accent/15 text-accent"
              : "border-border text-muted hover:text-fg"
          }`}
        >
          {selecting ? "Done" : "Select"}
        </button>
      </header>

      <div className="overflow-x-auto">
        <table className="w-full text-xs border-separate border-spacing-0">
          <thead className="text-muted">
            <tr>
              <th className="sticky left-0 z-10 bg-surface text-left font-medium px-3 py-2">
                Branch
              </th>
              {archs.map((arch) => (
                <th key={arch} className="font-medium px-1 py-2 text-left">
                  <span className="block max-w-[6.5rem] truncate" title={arch}>
                    {arch}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => {
              const rowCells = toCells(row);
              return (
                <tr key={row.branch} className="group">
                  <th
                    scope="row"
                    className="sticky left-0 z-10 bg-surface group-hover:bg-bg text-left font-normal px-3 py-1.5 border-t border-border"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      {selecting && (
                        <input
                          type="checkbox"
                          aria-label={`Select all builds of ${row.branch}`}
                          checked={selection.areAllSelected(rowCells)}
                          onChange={(e) =>
                            e.target.checked
                              ? selection.selectCells(rowCells)
                              : selection.deselectCells(rowCells)
                          }
                          className="accent-accent"
                        />
                      )}
                      <div className="min-w-0">
                        <span
                          className="block font-mono text-fg truncate max-w-[9rem] sm:max-w-[14rem]"
                          title={row.branch}
                        >
                          {row.branch}
                        </span>
                        <span className="block text-muted/80 text-[11px]">
                          {relativeTime(row.last_activity)}
                        </span>
                      </div>
                    </div>
                  </th>
                  {archs.map((arch) => {
                    const cell = row.cells[arch];
                    if (!cell) {
                      return (
                        <td key={arch} className="px-1 py-1.5 border-t border-border text-muted/50 text-center">
                          &middot;
                        </td>
                      );
                    }
                    const running = runningCells.has(`${row.branch}::${arch}`);
                    const tint = (CELL_STYLE[cell.run.status] ?? CELL_STYLE.unknown).cls;
                    const base = `relative flex items-center gap-1 rounded-md px-2 py-1 min-w-[4.75rem] ${tint}`;
                    return (
                      <td key={arch} className="px-1 py-1.5 border-t border-border">
                        {selecting ? (
                          <label
                            className={`${base} cursor-pointer ${
                              selection.isSelected(row.branch, arch) ? "ring-1 ring-accent" : ""
                            }`}
                            title={cellTitle(row.branch, arch, cell)}
                          >
                            <input
                              type="checkbox"
                              aria-label={`Select ${row.branch} / ${arch}`}
                              checked={selection.isSelected(row.branch, arch)}
                              disabled={!selection.isCellSelectable({ branch: row.branch, arch, run: cell.run })}
                              onChange={() => selection.toggleCell(row.branch, arch)}
                              className="accent-accent"
                            />
                            <CellContent cell={cell} running={running} />
                          </label>
                        ) : (
                          <Link
                            to={resultsPath(row.branch, arch, cell.run.run_id)}
                            className={`${base} hover:ring-1 hover:ring-accent/60`}
                            title={cellTitle(row.branch, arch, cell)}
                          >
                            <CellContent cell={cell} running={running} />
                          </Link>
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
            {visible.length === 0 && (
              <tr>
                <td colSpan={archs.length + 1} className="px-3 py-4 text-muted">
                  No branch matches &ldquo;{filter}&rdquo;.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {limited && (
        <button
          type="button"
          onClick={() => setShowAll(true)}
          className="w-full border-t border-border py-2 text-xs text-accent hover:bg-accent/10 transition-colors"
        >
          Show all ({sorted.length})
        </button>
      )}
    </section>
  );
}
