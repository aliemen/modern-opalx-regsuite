import { useCallback, useMemo, useState } from "react";
import type { LatestRunCell } from "./useLatestRuns";

/** Encoded as `"<branch>::<arch>::<run_id>"`. */
type SelectionKey = string;

function makeKey(branch: string, arch: string, runId: string): SelectionKey {
  return `${branch}::${arch}::${runId}`;
}

function parseKey(key: SelectionKey): {
  branch: string;
  arch: string;
  runId: string;
} | null {
  const parts = key.split("::");
  if (parts.length !== 3) return null;
  return { branch: parts[0], arch: parts[1], runId: parts[2] };
}

/** A group of run ids belonging to the same branch+arch — the unit accepted
 *  by the bulk archive endpoints. */
export interface BulkScope {
  branch: string;
  arch: string;
  runIds: string[];
}

export interface SelectionHandle {
  count: number;
  isSelected: (branch: string, arch: string, runId: string) => boolean;
  toggleRun: (branch: string, arch: string, runId: string) => void;
  /** Add every run from the given cells to the selection. */
  selectCells: (cells: LatestRunCell[]) => void;
  /** Remove every run from the given cells from the selection. */
  deselectCells: (cells: LatestRunCell[]) => void;
  /** True if every cell with a run is currently selected. */
  areAllSelected: (cells: LatestRunCell[]) => boolean;
  clear: () => void;
  /** Selection bucketed per branch+arch — what the bulk endpoints want. */
  groupedScopes: () => BulkScope[];
}

/**
 * Selection state for bulk archive / unarchive / hard-delete operations.
 *
 * Selection is keyed by full run id (not group key), so switching the
 * dashboard's `groupBy` axis preserves the user's selection.
 */
export function useRunSelection(): SelectionHandle {
  const [keys, setKeys] = useState<Set<SelectionKey>>(() => new Set());

  const isSelected = useCallback(
    (branch: string, arch: string, runId: string) =>
      keys.has(makeKey(branch, arch, runId)),
    [keys]
  );

  const toggleRun = useCallback(
    (branch: string, arch: string, runId: string) => {
      setKeys((prev) => {
        const next = new Set(prev);
        const k = makeKey(branch, arch, runId);
        if (next.has(k)) next.delete(k);
        else next.add(k);
        return next;
      });
    },
    []
  );

  const selectCells = useCallback((cells: LatestRunCell[]) => {
    setKeys((prev) => {
      const next = new Set(prev);
      for (const c of cells) {
        if (c.run) next.add(makeKey(c.branch, c.arch, c.run.run_id));
      }
      return next;
    });
  }, []);

  const deselectCells = useCallback((cells: LatestRunCell[]) => {
    setKeys((prev) => {
      const next = new Set(prev);
      for (const c of cells) {
        if (c.run) next.delete(makeKey(c.branch, c.arch, c.run.run_id));
      }
      return next;
    });
  }, []);

  const areAllSelected = useCallback(
    (cells: LatestRunCell[]) => {
      const withRuns = cells.filter((c) => c.run);
      if (withRuns.length === 0) return false;
      return withRuns.every((c) =>
        keys.has(makeKey(c.branch, c.arch, c.run!.run_id))
      );
    },
    [keys]
  );

  const clear = useCallback(() => setKeys(new Set()), []);

  const groupedScopes = useCallback((): BulkScope[] => {
    const map = new Map<string, BulkScope>();
    for (const key of keys) {
      const parsed = parseKey(key);
      if (!parsed) continue;
      const groupKey = `${parsed.branch}::${parsed.arch}`;
      if (!map.has(groupKey)) {
        map.set(groupKey, {
          branch: parsed.branch,
          arch: parsed.arch,
          runIds: [],
        });
      }
      map.get(groupKey)!.runIds.push(parsed.runId);
    }
    return Array.from(map.values());
  }, [keys]);

  return useMemo(
    () => ({
      count: keys.size,
      isSelected,
      toggleRun,
      selectCells,
      deselectCells,
      areAllSelected,
      clear,
      groupedScopes,
    }),
    [
      keys,
      isSelected,
      toggleRun,
      selectCells,
      deselectCells,
      areAllSelected,
      clear,
      groupedScopes,
    ]
  );
}
