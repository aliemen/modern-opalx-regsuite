import {
  Calendar,
  ChevronDown,
  ChevronRight,
  Cpu,
  GitBranch,
  TestTube2,
} from "lucide-react";
import type { LatestRunCell } from "../hooks/useLatestRuns";
import type { SelectionHandle } from "../hooks/useRunSelection";
import type { Group, GroupBy } from "../lib/grouping";
import { LatestCard } from "./LatestCard";

const SUMMARY_COLORS: Record<string, string> = {
  passed: "text-passed",
  failed: "text-failed",
  broken: "text-broken",
  crashed: "text-crashed",
  running: "text-accent",
  cancelled: "text-cancelled",
};

function summaryCounts(cells: LatestRunCell[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const c of cells) {
    const status = c.run?.status ?? "unknown";
    counts[status] = (counts[status] ?? 0) + 1;
  }
  return counts;
}

function GroupIcon({ kind }: { kind: Group["kind"] }) {
  if (kind === "branch") return <GitBranch size={14} className="text-muted shrink-0" />;
  if (kind === "arch") return <Cpu size={14} className="text-muted shrink-0" />;
  if (kind === "regtest-branch")
    return <TestTube2 size={14} className="text-muted shrink-0" />;
  return <Calendar size={14} className="text-muted shrink-0" />;
}

interface AccordionGroupProps {
  group: Group;
  open: boolean;
  onToggle: () => void;
  selection?: SelectionHandle;
  /** Optional shortcut button rendered in the header (e.g. "Archive branch"). */
  headerAction?: {
    label: string;
    onClick: () => void;
    /** Tailwind classes overriding the default neutral button style. */
    className?: string;
  };
  /** Passed down to each child card so drill-down links can carry the
   *  dashboard grouping axis as a query param. */
  fromGroup?: GroupBy;
  exactRunCount?: number;
}

/** One accordion section: header + grid of LatestCard when open. */
export function AccordionGroup({
  group,
  open,
  onToggle,
  selection,
  headerAction,
  fromGroup,
  exactRunCount,
}: AccordionGroupProps) {
  const counts = summaryCounts(group.cells);
  const allSelected = selection ? selection.areAllSelected(group.cells) : false;
  // The "select all" checkbox only makes sense when at least one cell in the
  // group is selectable (e.g. a branch=master arch row in a date bucket
  // shouldn't make the bucket-level checkbox lit up alone).
  const hasSelectable = selection
    ? group.cells.some(
        (c) => c.run !== undefined && selection.isCellSelectable(c)
      )
    : false;

  return (
    <div className="border border-border rounded-xl overflow-hidden">
      <div className="w-full flex flex-col gap-3 px-4 py-3.5 bg-surface hover:bg-border/30 transition-colors sm:flex-row sm:items-center sm:px-5">
        <div className="flex items-start gap-3 min-w-0 flex-1">
          {/* Optional bulk-select-all checkbox (only when selection mode is on). */}
          {selection && hasSelectable && (
            <label
              className="flex items-center cursor-pointer mt-0.5 shrink-0"
              onClick={(e) => e.stopPropagation()}
            >
              <input
                type="checkbox"
                checked={allSelected}
                onChange={() =>
                  allSelected
                    ? selection.deselectCells(group.cells)
                    : selection.selectCells(group.cells)
                }
                className="w-4 h-4 rounded border-border accent-accent dark:[color-scheme:dark] cursor-pointer"
              />
            </label>
          )}

          <button
            onClick={onToggle}
            className="min-w-0 flex-1 text-left"
          >
            <div className="flex items-center gap-2 min-w-0">
              {open ? (
                <ChevronDown size={14} className="text-muted shrink-0" />
              ) : (
                <ChevronRight size={14} className="text-muted shrink-0" />
              )}
              <GroupIcon kind={group.kind} />
              <span className="text-fg font-medium text-sm truncate" title={group.label}>
                {group.label}
              </span>
            </div>

            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
              {exactRunCount !== undefined && (
                <span className="text-accent">
                  {exactRunCount} archived run{exactRunCount !== 1 ? "s" : ""}
                </span>
              )}
              <span className="text-muted">
                {group.cells.length} {group.kind === "arch" ? "branch" : "arch"}
                {group.cells.length !== 1 ? (group.kind === "arch" ? "es" : "s") : ""}
              </span>
              {Object.entries(counts)
                .filter(([s]) => s !== "unknown")
                .map(([status, count]) => (
                  <span
                    key={status}
                    className={`${SUMMARY_COLORS[status] ?? "text-muted"} font-medium`}
                  >
                    {count} {status}
                  </span>
                ))}
            </div>
          </button>
        </div>

        {headerAction && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              headerAction.onClick();
            }}
            className={
              headerAction.className ??
              "w-full px-2.5 py-1.5 text-xs text-muted hover:text-fg border border-border hover:border-accent/40 rounded-md transition-colors sm:w-auto"
            }
          >
            {headerAction.label}
          </button>
        )}
      </div>

      {open && (
        <div className="border-t border-border p-4">
          <div className="grid gap-4 sm:grid-cols-2">
            {group.cells.map((cell) => {
              const selectable =
                selection?.isCellSelectable(cell) ?? true;
              return (
                <LatestCard
                  key={`${cell.branch}::${cell.arch}`}
                  branch={cell.branch}
                  arch={cell.arch}
                  run={cell.run}
                  showCheckbox={!!selection}
                  selected={
                    selection ? selection.isSelected(cell.branch, cell.arch) : false
                  }
                  checkboxDisabled={!selectable}
                  checkboxDisabledReason={
                    !selectable ? "master cannot be archived" : undefined
                  }
                  onToggleSelect={
                    selection && selectable
                      ? () => selection.toggleCell(cell.branch, cell.arch)
                      : undefined
                  }
                  fromGroup={fromGroup}
                />
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
