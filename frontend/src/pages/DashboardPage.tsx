import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Play } from "lucide-react";
import { getLatestMatrix } from "../api/results";
import { getQueueState } from "../api/runs";
import { useRunSelection } from "../hooks/useRunSelection";
import { useArchiveMutations } from "../hooks/useArchiveMutations";
import { useRunCompletionRefresh } from "../hooks/useRunCompletionRefresh";
import { secondsBetween } from "../lib/time";
import { BulkActionBar } from "../components/BulkActionBar";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { TrendsPanel } from "../components/TrendsPanel";
import { StatsPanel } from "../components/StatsPanel";
import { RecentRunsTable } from "../components/dashboard/RecentRunsTable";
import { BranchMatrix } from "../components/dashboard/BranchMatrix";

export function DashboardPage() {
  const { data: queueState } = useQuery({
    queryKey: ["queue-state"],
    queryFn: getQueueState,
    refetchInterval: 5000,
  });
  const machines = queueState?.machines;
  useRunCompletionRefresh(machines);

  // Under the ["branches"] prefix so every existing archive/delete
  // invalidation refreshes it too.
  const { data: matrixRows, isLoading: matrixLoading } = useQuery({
    queryKey: ["branches", "matrix"],
    queryFn: () => getLatestMatrix("active"),
    refetchInterval: 60_000,
  });
  const rows = useMemo(() => matrixRows ?? [], [matrixRows]);

  const selection = useRunSelection();
  const mutations = useArchiveMutations();
  // Confirmation for the bulk-bar "Archive selected" action.
  const [pendingBulkArchive, setPendingBulkArchive] = useState(false);
  // Toast for "N runs skipped (currently running)".
  const [skippedToast, setSkippedToast] = useState<string | null>(null);

  // Master's archs, most-run first, drive the trends and flakiness cards.
  const masterArchs = useMemo(() => {
    const master = rows.find((r) => r.branch === "master");
    if (!master) return [];
    return Object.entries(master.cells)
      .sort((a, b) => b[1].run_count - a[1].run_count)
      .map(([arch]) => arch);
  }, [rows]);

  // "last 41m" hint for running rows: duration of the newest finished run of
  // the same branch and arch, when it ran to a verdict.
  const lastDurations = useMemo(() => {
    const out = new Map<string, number>();
    for (const row of rows) {
      for (const [arch, cell] of Object.entries(row.cells)) {
        if (cell.run.status !== "passed" && cell.run.status !== "failed") continue;
        const secs = secondsBetween(cell.run.started_at, cell.run.finished_at);
        if (secs !== null) out.set(`${row.branch}::${arch}`, secs);
      }
    }
    return out;
  }, [rows]);

  const runningCells = useMemo(
    () =>
      new Set(
        (machines ?? []).flatMap((m) =>
          m.active_run ? [`${m.active_run.branch}::${m.active_run.arch}`] : []
        )
      ),
    [machines]
  );

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
    const failed = mutations.collectFailedMove(results);
    const messages: string[] = [];
    if (skipped.length > 0) {
      messages.push(
        `${skipped.length} run${skipped.length !== 1 ? "s" : ""} skipped (currently running)`
      );
    }
    if (failed.length > 0) {
      messages.push(
        `${failed.length} run${failed.length !== 1 ? "s" : ""} failed to move`
      );
    }
    if (messages.length > 0) {
      setSkippedToast(messages.join("; "));
    }
  }

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <h1 className="text-fg text-2xl font-semibold">Dashboard</h1>
        <Link
          to="/trigger"
          className="ml-auto flex items-center gap-1.5 px-3 py-1.5 text-sm bg-accent text-bg font-medium rounded-md hover:brightness-110 transition"
        >
          <Play size={14} />
          Start run
        </Link>
      </div>

      <RecentRunsTable machines={machines} lastDurations={lastDurations} />

      {matrixLoading ? (
        <div className="text-muted text-sm">Loading branches&hellip;</div>
      ) : rows.length > 0 ? (
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
          <div className="lg:col-span-3 min-w-0">
            <BulkActionBar
              selection={selection}
              view="active"
              onArchiveToggle={() => setPendingBulkArchive(true)}
              busy={mutations.archiveCells.isPending}
            />
            <BranchMatrix rows={rows} runningCells={runningCells} selection={selection} />
          </div>

          <div className="lg:col-span-2 space-y-4 min-w-0">
            {masterArchs.length > 0 && <TrendsPanel archs={masterArchs} />}
            <StatsPanel flakinessArchs={masterArchs} />
          </div>
        </div>
      ) : null}

      <ConfirmDialog
        open={pendingBulkArchive}
        title={`Archive ${selection.count} branch/build cell${selection.count !== 1 ? "s" : ""}?`}
        message="Every run in the selected branch/build cells will be hidden from the dashboard. You can restore them from the Archive tab at any time. Currently-running runs are skipped."
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
