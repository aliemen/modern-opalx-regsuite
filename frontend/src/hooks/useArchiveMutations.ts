import { useCallback } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  archiveArch,
  archiveBranch,
  hardDeleteArch,
  type ArchiveResult,
} from "../api/results";
import type { CellRef } from "./useRunSelection";

interface ArchiveBranchVars {
  branch: string;
  archived: boolean;
}

interface ArchiveCellsVars {
  cells: CellRef[];
  archived: boolean;
}

interface HardDeleteCellsVars {
  cells: CellRef[];
}

/**
 * TanStack mutation wrappers for every archive endpoint plus a single
 * `invalidateAll()` that nukes every view-namespaced query key the dashboard
 * and archive pages care about.
 *
 * The bulk mutations operate on whole (branch, arch) cells (not individual
 * run ids) because the dashboard cards are per-cell and the user's intent
 * when checking a card is "operate on the whole cell". This also fixes a
 * bug where archiving "the latest run" of a cell left the rest of the
 * history active and the cell remained visible on the dashboard.
 *
 * Why aggressive invalidation: a bulk archive can affect any combination of
 * `["branches", view]`, `["runs", branch, arch, view]`, `["all-runs", view]`,
 * `["dashboard-stats"]`, and `["trend-runs", ...]`. Rather than try to be
 * surgical (which gets fragile), we invalidate them all on every successful
 * mutation. The dataset is small so refetch cost is negligible.
 */
export function useArchiveMutations() {
  const qc = useQueryClient();

  const invalidateAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ["branches"] });
    qc.invalidateQueries({ queryKey: ["runs"] });
    qc.invalidateQueries({ queryKey: ["all-runs"] });
    qc.invalidateQueries({ queryKey: ["dashboard-stats"] });
    qc.invalidateQueries({ queryKey: ["trend-runs"] });
  }, [qc]);

  const branchMutation = useMutation<ArchiveResult, Error, ArchiveBranchVars>({
    mutationFn: ({ branch, archived }) => archiveBranch(branch, archived),
    onSuccess: invalidateAll,
  });

  const archiveCellsMutation = useMutation<ArchiveResult[], Error, ArchiveCellsVars>(
    {
      mutationFn: async ({ cells, archived }) =>
        Promise.all(cells.map((c) => archiveArch(c.branch, c.arch, archived))),
      onSuccess: invalidateAll,
    }
  );

  const hardDeleteCellsMutation = useMutation<
    ArchiveResult[],
    Error,
    HardDeleteCellsVars
  >({
    mutationFn: async ({ cells }) =>
      Promise.all(cells.map((c) => hardDeleteArch(c.branch, c.arch))),
    onSuccess: invalidateAll,
  });

  return {
    archiveBranch: branchMutation,
    archiveCells: archiveCellsMutation,
    hardDeleteCells: hardDeleteCellsMutation,
    /** Returns the union of skipped_active across an array of results, for
     *  showing a single "N runs skipped (currently running)" toast. */
    collectSkippedActive(results: ArchiveResult[]): string[] {
      const all = new Set<string>();
      for (const r of results) for (const id of r.skipped_active) all.add(id);
      return Array.from(all);
    },
  };
}
