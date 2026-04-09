import { useState } from "react";
import { Archive, User as UserIcon } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useLatestRuns } from "../hooks/useLatestRuns";
import { useRunSelection } from "../hooks/useRunSelection";
import { useArchiveMutations } from "../hooks/useArchiveMutations";
import { AccordionList } from "../components/AccordionList";
import { BulkActionBar } from "../components/BulkActionBar";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { getUsersLeaderboard } from "../api/stats";
import type { Group } from "../lib/grouping";

export function ArchivePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const userParam = searchParams.get("user");
  const triggeredBy = userParam && userParam !== "" ? userParam : null;

  // Enumerate users that have at least one archived run, so the dropdown
  // never offers a filter that would always produce zero rows.
  const { data: leaderboard } = useQuery({
    queryKey: ["users-leaderboard", "archived"],
    queryFn: () => getUsersLeaderboard("archived"),
    refetchInterval: 60_000,
  });
  const userOptions = leaderboard?.users ?? [];

  function handleUserChange(value: string) {
    const next = new URLSearchParams(searchParams);
    if (value) {
      next.set("user", value);
    } else {
      next.delete("user");
    }
    setSearchParams(next, { replace: true });
  }

  const { cells, branches, isLoading } = useLatestRuns("archived", triggeredBy);
  const selection = useRunSelection();
  const mutations = useArchiveMutations();

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

  async function confirmBranchUnarchive() {
    const branch = pendingBranchUnarchive;
    setPendingBranchUnarchive(null);
    if (!branch) return;
    await mutations.archiveBranch.mutateAsync({ branch, archived: false });
  }

  async function confirmBulkUnarchive() {
    setPendingBulkUnarchive(false);
    const cellRefs = selection.selectedCells();
    if (cellRefs.length === 0) return;
    await mutations.archiveCells.mutateAsync({
      cells: cellRefs,
      archived: false,
    });
    selection.clear();
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
    if (skipped.length > 0) {
      setSkippedToast(
        `${skipped.length} run${skipped.length !== 1 ? "s" : ""} skipped (currently running)`
      );
    }
  }

  if (isLoading && !hasEntries) {
    return <div className="p-8 text-muted">Loading…</div>;
  }

  const noUsersAvailable = userOptions.length === 0;
  const emptyMessage = triggeredBy
    ? `No archived runs triggered by "${triggeredBy}".`
    : "No archived runs.";

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <h1 className="text-fg text-2xl font-semibold mb-2 flex items-center gap-3">
        <Archive size={22} className="text-muted" />
        Archive
      </h1>
      <p className="text-muted text-sm mb-6">
        Archived runs are hidden from the dashboard but still browsable here.
        Unarchive to restore a cell, or hard-delete to permanently remove its
        archived runs from disk.
      </p>

      <div className="flex items-center gap-3 mb-6">
        <label
          htmlFor="archive-user-filter"
          className="flex items-center gap-1.5 text-muted text-xs"
        >
          <UserIcon size={13} />
          User
        </label>
        <select
          id="archive-user-filter"
          value={triggeredBy ?? ""}
          onChange={(e) => handleUserChange(e.target.value)}
          disabled={noUsersAvailable && !triggeredBy}
          className="bg-surface border border-border rounded-lg text-fg text-xs px-3 py-1.5 focus:outline-none focus:border-accent disabled:opacity-50 min-w-[10rem]"
        >
          <option value="">All users</option>
          {userOptions.map((u) => (
            <option key={u.username} value={u.username}>
              {u.username} ({u.count})
            </option>
          ))}
          {/* Make sure a deep-linked user that no longer has archived runs
              still appears in the dropdown so the user understands what is
              filtered, instead of the select silently snapping to "All". */}
          {triggeredBy &&
            !userOptions.some((u) => u.username === triggeredBy) && (
              <option value={triggeredBy}>{triggeredBy} (0)</option>
            )}
        </select>
      </div>

      {!hasEntries ? (
        <div className="text-muted text-sm py-12 text-center border border-border rounded-xl">
          {emptyMessage}
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
          <AccordionList
            cells={cells}
            groupBy="branch"
            storageNamespace="opalx-archive-open"
            selection={selection}
            groupAction={groupAction}
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
