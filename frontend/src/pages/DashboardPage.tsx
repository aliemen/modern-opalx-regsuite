import { useCallback, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Radio } from "lucide-react";
import { getQueueState } from "../api/runs";
import { useLatestRuns, type LatestRunCell } from "../hooks/useLatestRuns";
import { useRunSelection } from "../hooks/useRunSelection";
import { useArchiveMutations } from "../hooks/useArchiveMutations";
import { useGroupBy } from "../hooks/useGroupBy";
import { AccordionList } from "../components/AccordionList";
import { BulkActionBar } from "../components/BulkActionBar";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { GroupingControl } from "../components/GroupingControl";
import { TrendsPanel } from "../components/TrendsPanel";
import { StatsPanel } from "../components/StatsPanel";
import { QueuePanel } from "../components/QueuePanel";
import type { Group } from "../lib/grouping";

/** master holds canonical history; we never let the user archive it from
 *  the dashboard. The backend enforces this too (returns 409). */
const PROTECTED_BRANCH = "master";

export function DashboardPage() {
  const { cells, branches, runCounts, isLoading } = useLatestRuns("active");

  const { data: queueState } = useQuery({
    queryKey: ["queue-state"],
    queryFn: getQueueState,
    refetchInterval: 5000,
  });

  // Master is filtered out of selection so the bulk-archive bar reflects only
  // archivable cells; per-card checkboxes for master are also disabled below.
  const isCellSelectable = useCallback(
    (cell: LatestRunCell) => cell.branch !== PROTECTED_BRANCH,
    []
  );

  const selection = useRunSelection({ isCellSelectable });
  const mutations = useArchiveMutations();
  const [groupBy, setGroupBy] = useGroupBy();

  // Confirmation state for the per-group "Archive branch" shortcut.
  const [pendingBranchArchive, setPendingBranchArchive] = useState<string | null>(
    null
  );
  // Confirmation for the bulk-bar "Archive selected" action.
  const [pendingBulkArchive, setPendingBulkArchive] = useState(false);
  // Toast for "N runs skipped (currently running)".
  const [skippedToast, setSkippedToast] = useState<string | null>(null);

  if (isLoading && Object.keys(branches).length === 0) {
    return <div className="p-8 text-muted">Loading…</div>;
  }

  const masterArchs = [...(branches?.["master"] ?? [])].sort(
    (a, b) => (runCounts.get(`master/${b}`) ?? 0) - (runCounts.get(`master/${a}`) ?? 0)
  );

  // Active/queued counts from queue state.
  const machines = queueState?.machines ?? [];
  const activeRuns = machines.flatMap((m) =>
    m.active_run ? [m.active_run] : []
  );
  const totalQueued = machines.reduce((s, m) => s + m.queue.length, 0);

  function groupAction(group: Group) {
    // Hide the per-group "Archive branch" shortcut for master.
    if (group.kind !== "branch") return undefined;
    if (group.label === PROTECTED_BRANCH) return undefined;
    return {
      label: "Archive branch",
      onClick: () => setPendingBranchArchive(group.label),
    };
  }

  async function confirmBranchArchive() {
    const branch = pendingBranchArchive;
    setPendingBranchArchive(null);
    if (!branch) return;
    const result = await mutations.archiveBranch.mutateAsync({
      branch,
      archived: true,
    });
    if (result.skipped_active.length > 0) {
      setSkippedToast(
        `${result.skipped_active.length} run${result.skipped_active.length !== 1 ? "s" : ""} skipped (currently running)`
      );
    }
  }

  async function confirmBulkArchive() {
    setPendingBulkArchive(false);
    const cellRefs = selection.selectedCells();
    if (cellRefs.length === 0) return;
    const results = await mutations.archiveCells.mutateAsync({
      cells: cellRefs,
      archived: true,
    });
    selection.clear();
    const skipped = mutations.collectSkippedActive(results);
    if (skipped.length > 0) {
      setSkippedToast(
        `${skipped.length} run${skipped.length !== 1 ? "s" : ""} skipped (currently running)`
      );
    }
  }

  const busy =
    mutations.archiveBranch.isPending || mutations.archiveCells.isPending;
  const hasEntries = Object.keys(branches).length > 0;

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {activeRuns.length > 0 ? (
        <Link
          to={`/live/${activeRuns[0].run_id}`}
          className="flex items-center gap-3 bg-accent/10 border border-accent/30 rounded-xl px-5 py-3 mb-6 text-accent text-sm hover:bg-accent/20 transition-colors"
        >
          <span className="w-2 h-2 rounded-full bg-accent animate-ping inline-block" />
          {activeRuns.length === 1 ? (
            <>
              Run in progress — {activeRuns[0].branch} / {activeRuns[0].arch} —
              phase: {activeRuns[0].phase}
            </>
          ) : (
            <>
              {activeRuns.length} runs in progress
              {totalQueued > 0 && <>, {totalQueued} queued</>}
            </>
          )}
          <span className="ml-auto text-xs underline">View live output →</span>
        </Link>
      ) : (
        <Link
          to="/live"
          className="flex items-center gap-2 text-muted hover:text-fg text-sm mb-6 w-fit transition-colors"
        >
          <Radio size={13} /> Latest run log
        </Link>
      )}

      <h1 className="text-fg text-2xl font-semibold mb-6">Dashboard</h1>

      {!hasEntries ? (
        <div className="text-muted text-sm">
          No results yet.{" "}
          <Link to="/trigger" className="text-accent hover:underline">
            Start a run
          </Link>{" "}
          to get started.
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
          {/* Left: grouping control + bulk action bar + accordion */}
          <div className="lg:col-span-3">
            <GroupingControl value={groupBy} onChange={setGroupBy} />
            <BulkActionBar
              selection={selection}
              view="active"
              onArchiveToggle={() => setPendingBulkArchive(true)}
              busy={busy}
            />
            <AccordionList
              cells={cells}
              groupBy={groupBy}
              storageNamespace="opalx-dashboard-open"
              selection={selection}
              groupAction={groupAction}
            />
          </div>

          {/* Right: trends + stats + queue */}
          <div className="lg:col-span-2 space-y-4">
            {masterArchs.length > 0 && <TrendsPanel archs={masterArchs} />}
            <StatsPanel />
            <QueuePanel />
          </div>
        </div>
      )}

      <ConfirmDialog
        open={pendingBranchArchive !== null}
        title={`Archive branch "${pendingBranchArchive}"?`}
        message={`This will hide every run for "${pendingBranchArchive}" from the dashboard. You can restore them from the Archive tab at any time. Currently-running runs are skipped.`}
        confirmLabel="Archive"
        onConfirm={confirmBranchArchive}
        onCancel={() => setPendingBranchArchive(null)}
      />

      <ConfirmDialog
        open={pendingBulkArchive}
        title={`Archive ${selection.count} cell${selection.count !== 1 ? "s" : ""}?`}
        message="The selected branch+arch cells (every run in each) will be hidden from the dashboard. You can restore them from the Archive tab at any time."
        confirmLabel="Archive"
        onConfirm={confirmBulkArchive}
        onCancel={() => setPendingBulkArchive(false)}
      />

      {skippedToast && (
        <div
          className="fixed bottom-6 right-6 z-40 bg-surface border border-broken/40 rounded-xl px-4 py-3 text-sm text-fg shadow-lg cursor-pointer"
          onClick={() => setSkippedToast(null)}
        >
          {skippedToast}
          <span className="text-muted text-xs ml-3">(click to dismiss)</span>
        </div>
      )}
    </div>
  );
}
