import { useCallback, useEffect, useMemo, useState } from "react";
import type { LatestRunCell } from "../hooks/useLatestRuns";
import type { SelectionHandle } from "../hooks/useRunSelection";
import { groupRuns, type Group, type GroupBy } from "../lib/grouping";
import { AccordionGroup } from "./AccordionGroup";

interface AccordionListProps {
  cells: LatestRunCell[];
  groupBy: GroupBy;
  /** Used as part of the localStorage key for accordion open state, so the
   *  archive page and dashboard remember their open groups independently. */
  storageNamespace: string;
  selection?: SelectionHandle;
  /** Called when the user clicks the per-group action button. The handler
   *  decides what the action means (archive / unarchive). Returning undefined
   *  hides the button for that group. */
  groupAction?: (group: Group) =>
    | { label: string; onClick: () => void; className?: string }
    | undefined;
  /** If provided, drill-down links from each card append ``?group=<this>``
   *  so the downstream pages can build breadcrumbs back to the same view. */
  fromGroup?: GroupBy;
}

function loadOpenGroups(key: string): Set<string> {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    if (!Array.isArray(arr)) return new Set();
    return new Set(arr.filter((x): x is string => typeof x === "string"));
  } catch {
    return new Set();
  }
}

function saveOpenGroups(key: string, set: Set<string>): void {
  try {
    localStorage.setItem(key, JSON.stringify(Array.from(set)));
  } catch {
    /* ignore quota errors */
  }
}

/**
 * Generic accordion container that takes a flat list of latest-run-per-cell
 * data, groups it by the requested axis, and renders one `AccordionGroup`
 * per resulting bucket.
 *
 * Open/closed state is persisted per (storageNamespace, groupBy) so the
 * dashboard's "branch → opened master" doesn't collide with "date → opened
 * Today".
 */
export function AccordionList({
  cells,
  groupBy,
  storageNamespace,
  selection,
  groupAction,
  fromGroup,
}: AccordionListProps) {
  const storageKey = `${storageNamespace}:${groupBy}`;

  const [openGroups, setOpenGroups] = useState<Set<string>>(() =>
    loadOpenGroups(storageKey)
  );

  // Reload from storage when the namespace+groupBy combo changes.
  useEffect(() => {
    setOpenGroups(loadOpenGroups(storageKey));
  }, [storageKey]);

  const groups = useMemo(
    () => groupRuns(cells, groupBy, new Date()),
    [cells, groupBy]
  );

  // Auto-open the first group on first render if nothing is currently open
  // (so the dashboard isn't a wall of collapsed accordions on first visit).
  useEffect(() => {
    if (openGroups.size === 0 && groups.length > 0) {
      const first = new Set([groups[0].key]);
      setOpenGroups(first);
      saveOpenGroups(storageKey, first);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey, groups.length]);

  const toggle = useCallback(
    (key: string) => {
      setOpenGroups((prev) => {
        const next = new Set(prev);
        if (next.has(key)) next.delete(key);
        else next.add(key);
        saveOpenGroups(storageKey, next);
        return next;
      });
    },
    [storageKey]
  );

  if (groups.length === 0) {
    return (
      <div className="text-muted text-sm py-6 text-center border border-border rounded-xl">
        Nothing here yet.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {groups.map((group) => (
        <AccordionGroup
          key={group.key}
          group={group}
          open={openGroups.has(group.key)}
          onToggle={() => toggle(group.key)}
          selection={selection}
          headerAction={groupAction?.(group)}
          fromGroup={fromGroup}
        />
      ))}
    </div>
  );
}
