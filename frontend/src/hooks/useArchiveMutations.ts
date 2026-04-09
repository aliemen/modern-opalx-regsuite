import { useCallback } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  archiveArch,
  archiveBranch,
  archiveRuns,
  hardDeleteRuns,
  type ArchiveResult,
} from "../api/results";
import type { BulkScope } from "./useRunSelection";

interface ArchiveBranchVars {
  branch: string;
  archived: boolean;
}

interface ArchiveArchVars {
  branch: string;
  arch: string;
  archived: boolean;
}

interface ArchiveRunsVars {
  scopes: BulkScope[];
  archived: boolean;
}

interface HardDeleteVars {
  scopes: BulkScope[];
}

/**
 * TanStack mutation wrappers for every archive endpoint plus a single
 * `invalidateAll()` that nukes every view-namespaced query key the dashboard
 * and archive pages care about.
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

  const archMutation = useMutation<ArchiveResult, Error, ArchiveArchVars>({
    mutationFn: ({ branch, arch, archived }) =>
      archiveArch(branch, arch, archived),
    onSuccess: invalidateAll,
  });

  const runsMutation = useMutation<ArchiveResult[], Error, ArchiveRunsVars>({
    mutationFn: async ({ scopes, archived }) =>
      Promise.all(
        scopes.map((s) => archiveRuns(s.branch, s.arch, s.runIds, archived))
      ),
    onSuccess: invalidateAll,
  });

  const hardDeleteMutation = useMutation<ArchiveResult[], Error, HardDeleteVars>(
    {
      mutationFn: async ({ scopes }) =>
        Promise.all(
          scopes.map((s) => hardDeleteRuns(s.branch, s.arch, s.runIds))
        ),
      onSuccess: invalidateAll,
    }
  );

  return {
    archiveBranch: branchMutation,
    archiveArch: archMutation,
    archiveRuns: runsMutation,
    hardDeleteRuns: hardDeleteMutation,
    /** Returns the union of skipped_active across an array of results, for
     *  showing a single "N runs skipped (currently running)" toast. */
    collectSkippedActive(results: ArchiveResult[]): string[] {
      const all = new Set<string>();
      for (const r of results) for (const id of r.skipped_active) all.add(id);
      return Array.from(all);
    },
  };
}
