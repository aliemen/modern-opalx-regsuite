import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Archive } from "lucide-react";
import { getArchiveSummary } from "../api/results";
import { useLatestRuns } from "../hooks/useLatestRuns";
import { useRunSelection } from "../hooks/useRunSelection";
import { useArchiveMutations } from "../hooks/useArchiveMutations";
import { AccordionList } from "../components/AccordionList";
import { BulkActionBar } from "../components/BulkActionBar";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { GroupingControl } from "../components/GroupingControl";
import type { Group, GroupBy } from "../lib/grouping";

export function ArchivePage() {
  const { cells, branches, isLoading } = useLatestRuns("archived");
  const { data: summary } = useQuery({
    queryKey: ["archive-summary"],
    queryFn: getArchiveSummary,
    refetchInterval: 60_000,
  });
  const selection = useRunSelection();
  const mutations = useArchiveMutations();

  const [groupBy, setGroupBy] = useState<GroupBy>("branch");
  const [pendingBranchUnarchive, setPendingBranchUnarchive] = useState<
    string | null
  >(null);
  const [pendingBulkUnarchive, setPendingBulkUnarchive] = useState(false);
  const [pendingBulkHardDelete, setPendingBulkHardDelete] = useState(false);
  const [skippedToast, setSkippedToast] = useState<string | null>(null);

  const hasEntries = Object.keys(branches).length > 0;
  const busy =
    mutations.archiveBranch.isPending ||
    mutations.archiveCells.isPending ||
    mutations.hardDeleteCells.isPending;

  function groupAction(group: Group) {
    if (group.kind !== "branch") return undefined;
    return {
      label: "Unarchive branch",
      onClick: () => setPendingBranchUnarchive(group.label),
    };
  }

  const ARCHIVE_GROUP_OPTIONS: GroupBy[] = ["branch", "regtest-branch"];
  const exactRunCounts =
    groupBy === "branch"
      ? summary?.by_branch
      : summary?.by_regtest_branch;

  async function confirmBranchUnarchive() {
    const branch = pendingBranchUnarchive;
    setPendingBranchUnarchive(null);
    if (!branch) return;
    const result = await mutations.archiveBranch.mutateAsync({ branch, archived: false });
    if (result.failed_move.length > 0) {
      setSkippedToast(
        `${result.failed_move.length} run${result.failed_move.length !== 1 ? "s" : ""} failed to move`
      );
    }
  }

  async function confirmBulkUnarchive() {
    setPendingBulkUnarchive(false);
    const cellRefs = selection.selectedCells();
    if (cellRefs.length === 0) return;
    const results = await mutations.archiveCells.mutateAsync({
      cells: cellRefs,
      archived: false,
    });
    selection.clear();
    const failed = mutations.collectFailedMove(results);
    if (failed.length > 0) {
      setSkippedToast(
        `${failed.length} run${failed.length !== 1 ? "s" : ""} failed to move`
      );
    }
  }

  async function confirmBulkHardDelete() {
    setPendingBulkHardDelete(false);
    const cellRefs = selection.selectedCells();
    if (cellRefs.length === 0) return;
    const results = await mutations.hardDeleteCells.mutateAsync({
      cells: cellRefs,
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

  if (isLoading && !hasEntries) {
    return <div className="p-8 text-muted">Loading…</div>;
  }

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <h1 className="text-fg text-2xl font-semibold mb-2 flex items-center gap-3">
        <Archive size={22} className="text-muted" />
        Archive
      </h1>
      <div className="mb-3 inline-flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-1.5 text-sm">
        <span className="text-muted">Total archived runs</span>
        <span className="text-fg font-semibold tabular-nums">
          {summary?.total ?? "—"}
        </span>
      </div>
      <p className="text-muted text-sm mb-6">
        Archived runs are hidden from the dashboard but still browsable here.
        Unarchive to restore a cell, or hard-delete to permanently remove its
        archived runs from disk.
      </p>

      {!hasEntries ? (
        <div className="text-muted text-sm py-12 text-center border border-border rounded-xl">
          No archived runs.
        </div>
      ) : (
        <>
          <BulkActionBar
            selection={selection}
            view="archived"
            onArchiveToggle={() => setPendingBulkUnarchive(true)}
            onHardDelete={() => setPendingBulkHardDelete(true)}
            busy={busy}
          />
          <GroupingControl
            value={groupBy}
            onChange={setGroupBy}
            allowedValues={ARCHIVE_GROUP_OPTIONS}
          />
          <AccordionList
            cells={cells}
            groupBy={groupBy}
            storageNamespace="opalx-archive-open"
            selection={selection}
            groupAction={groupAction}
            exactRunCounts={exactRunCounts}
          />
        </>
      )}

      <ConfirmDialog
        open={pendingBranchUnarchive !== null}
        title={`Unarchive branch "${pendingBranchUnarchive}"?`}
        message={`This will restore every archived run for "${pendingBranchUnarchive}" to the dashboard.`}
        confirmLabel="Unarchive"
        onConfirm={confirmBranchUnarchive}
        onCancel={() => setPendingBranchUnarchive(null)}
      />

      <ConfirmDialog
        open={pendingBulkUnarchive}
        title={`Unarchive ${selection.count} cell${selection.count !== 1 ? "s" : ""}?`}
        message="Every archived run in the selected branch+arch cells will return to the dashboard."
        confirmLabel="Unarchive"
        onConfirm={confirmBulkUnarchive}
        onCancel={() => setPendingBulkUnarchive(false)}
      />

      <ConfirmDialog
        open={pendingBulkHardDelete}
        title={`Permanently delete ${selection.count} cell${selection.count !== 1 ? "s" : ""}?`}
        message={
          "This cannot be undone. Every archived run in the selected " +
          "branch+arch cells (logs, plots, metadata) will be removed from " +
          "disk. Active runs in the same cells are not touched."
        }
        confirmLabel="Delete forever"
        destructive
        onConfirm={confirmBulkHardDelete}
        onCancel={() => setPendingBulkHardDelete(false)}
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
