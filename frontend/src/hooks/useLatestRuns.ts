import { useMemo } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import {
  getBranches,
  getRuns,
  type RunIndexEntry,
  type ViewMode,
} from "../api/results";

/** A flat row representing the latest run for one branch+arch combination. */
export interface LatestRunCell {
  branch: string;
  arch: string;
  run?: RunIndexEntry;
}

interface UseLatestRunsResult {
  cells: LatestRunCell[];
  branches: Record<string, string[]>;
  isLoading: boolean;
}

/**
 * Fetch the latest run for every (branch, arch) combination visible under
 * *view*. Owns the per-card `useQueries` fan-out so the dashboard and
 * archive pages don't need to know about it.
 *
 * Each cell maps 1:1 to a TanStack React Query cache entry keyed by
 * `["runs", branch, arch, view]`, so bulk-archive mutations can invalidate
 * exactly the affected entries.
 */
export function useLatestRuns(view: ViewMode = "active"): UseLatestRunsResult {
  const branchesQuery = useQuery({
    queryKey: ["branches", view],
    queryFn: () => getBranches(view),
    refetchInterval: 60_000,
  });

  const branches = branchesQuery.data ?? {};

  // Flatten branches → list of (branch, arch) tuples in stable order so the
  // useQueries call below stays stable across renders.
  const tuples = useMemo(() => {
    const out: { branch: string; arch: string }[] = [];
    const branchNames = Object.keys(branches).sort((a, b) => {
      if (a === "master") return -1;
      if (b === "master") return 1;
      return a.localeCompare(b);
    });
    for (const branch of branchNames) {
      for (const arch of branches[branch] ?? []) {
        out.push({ branch, arch });
      }
    }
    return out;
  }, [branches]);

  const runQueries = useQueries({
    queries: tuples.map(({ branch, arch }) => ({
      queryKey: ["runs", branch, arch, view] as const,
      queryFn: () => getRuns(branch, arch, 1, 0, view),
      refetchInterval: 30_000,
      select: (data: { runs: RunIndexEntry[]; total: number }) =>
        data.runs[0] as RunIndexEntry | undefined,
    })),
  });

  const cells: LatestRunCell[] = tuples.map((t, i) => ({
    branch: t.branch,
    arch: t.arch,
    run: runQueries[i]?.data,
  }));

  const isLoading =
    branchesQuery.isLoading || runQueries.some((q) => q.isLoading);

  return { cells, branches, isLoading };
}
