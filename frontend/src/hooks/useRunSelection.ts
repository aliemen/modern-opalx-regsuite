import { useCallback, useMemo, useState } from "react";
import type { LatestRunCell } from "./useLatestRuns";

/** Encoded as `"<branch>::<arch>"`. */
type SelectionKey = string;

function makeKey(branch: string, arch: string): SelectionKey {
  return `${branch}::${arch}`;
}

function parseKey(key: SelectionKey): { branch: string; arch: string } | null {
  const idx = key.indexOf("::");
  if (idx < 0) return null;
  return { branch: key.slice(0, idx), arch: key.slice(idx + 2) };
}

/** A (branch, arch) cell — the unit operated on by the bulk endpoints. */
export interface CellRef {
  branch: string;
  arch: string;
}

/** Cells where the *whole* (branch+arch) — every run in it — is the action target. */
export interface SelectionHandle {
  count: number;
  isSelected: (branch: string, arch: string) => boolean;
  toggleCell: (branch: string, arch: string) => void;
  /** Add every selectable cell from the given list to the selection. */
  selectCells: (cells: LatestRunCell[]) => void;
  /** Remove every cell from the given list from the selection. */
  deselectCells: (cells: LatestRunCell[]) => void;
  /** True iff every selectable cell in the list is currently selected. */
  areAllSelected: (cells: LatestRunCell[]) => boolean;
  clear: () => void;
  /** Selected (branch, arch) pairs in flat form for the bulk endpoints. */
  selectedCells: () => CellRef[];
  /** Predicate the parent uses to filter "selectable" cells (e.g. exclude master). */
  isCellSelectable: (cell: LatestRunCell) => boolean;
}

interface UseRunSelectionOptions {
  /** Cells matching this predicate are not selectable (e.g. the master branch
   *  on the dashboard). Defaults to "everything is selectable". */
  isCellSelectable?: (cell: LatestRunCell) => boolean;
}

/**
 * Selection state for bulk archive / unarchive / hard-delete operations.
 *
 * Selection is keyed by full (branch, arch) cell — NOT by run id — because the
 * dashboard shows the latest run per cell and the user's mental model when
 * checking a card is "hide this branch+arch from my dashboard", which means
 * archiving every run for that cell, not just the latest one. Selection by
 * cell also keeps the state stable when switching `groupBy` axes.
 */
export function useRunSelection(
  options: UseRunSelectionOptions = {}
): SelectionHandle {
  const isCellSelectable = options.isCellSelectable ?? (() => true);
  const [keys, setKeys] = useState<Set<SelectionKey>>(() => new Set());

  const isSelected = useCallback(
    (branch: string, arch: string) => keys.has(makeKey(branch, arch)),
    [keys]
  );

  const toggleCell = useCallback((branch: string, arch: string) => {
    setKeys((prev) => {
      const next = new Set(prev);
      const k = makeKey(branch, arch);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  }, []);

  const selectCells = useCallback(
    (cells: LatestRunCell[]) => {
      setKeys((prev) => {
        const next = new Set(prev);
        for (const c of cells) {
          if (!isCellSelectable(c)) continue;
          next.add(makeKey(c.branch, c.arch));
        }
        return next;
      });
    },
    [isCellSelectable]
  );

  const deselectCells = useCallback((cells: LatestRunCell[]) => {
    setKeys((prev) => {
      const next = new Set(prev);
      for (const c of cells) next.delete(makeKey(c.branch, c.arch));
      return next;
    });
  }, []);

  const areAllSelected = useCallback(
    (cells: LatestRunCell[]) => {
      const selectable = cells.filter(isCellSelectable);
      if (selectable.length === 0) return false;
      return selectable.every((c) => keys.has(makeKey(c.branch, c.arch)));
    },
    [keys, isCellSelectable]
  );

  const clear = useCallback(() => setKeys(new Set()), []);

  const selectedCells = useCallback((): CellRef[] => {
    const out: CellRef[] = [];
    for (const key of keys) {
      const parsed = parseKey(key);
      if (parsed) out.push(parsed);
    }
    return out;
  }, [keys]);

  return useMemo(
    () => ({
      count: keys.size,
      isSelected,
      toggleCell,
      selectCells,
      deselectCells,
      areAllSelected,
      clear,
      selectedCells,
      isCellSelectable,
    }),
    [
      keys,
      isSelected,
      toggleCell,
      selectCells,
      deselectCells,
      areAllSelected,
      clear,
      selectedCells,
      isCellSelectable,
    ]
  );
}
