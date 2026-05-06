import { Archive, ArchiveRestore, Trash2, X } from "lucide-react";
import type { ViewMode } from "../api/results";
import type { SelectionHandle } from "../hooks/useRunSelection";

interface BulkActionBarProps {
  selection: SelectionHandle;
  view: ViewMode;
  /** Called when the user clicks the primary archive/unarchive button. */
  onArchiveToggle: () => void;
  /** Called when the user clicks "Hard delete" — only rendered for archived view. */
  onHardDelete?: () => void;
  /** Whether any of the underlying mutations are running. */
  busy?: boolean;
}

/**
 * Sticky bar shown above the accordion when at least one run is selected.
 *
 * - On the active dashboard: shows `Archive` (and `Clear`).
 * - On the archive page: shows `Unarchive` and `Hard delete` (and `Clear`).
 *
 * The component is purely presentational. It owns no state — selection,
 * mutations, and confirmation dialogs all live in the parent page.
 */
export function BulkActionBar({
  selection,
  view,
  onArchiveToggle,
  onHardDelete,
  busy = false,
}: BulkActionBarProps) {
  if (selection.count === 0) return null;

  const isArchived = view === "archived";

  return (
    <div className="sticky top-0 z-20 mb-4">
      <div className="bg-surface border border-accent/40 rounded-xl px-4 py-3 flex flex-col gap-3 shadow-md sm:px-5 sm:flex-row sm:items-center">
        <span className="text-fg text-sm font-medium min-w-0">
          {selection.count} run{selection.count !== 1 ? "s" : ""} selected
        </span>

        <div className="flex flex-wrap items-center gap-2 sm:ml-auto">
          <button
            onClick={onArchiveToggle}
            disabled={busy}
            className="flex items-center justify-center gap-1.5 px-3 py-1.5 text-sm text-fg bg-bg hover:bg-border/40 border border-border rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isArchived ? (
              <>
                <ArchiveRestore size={14} />
                Unarchive
              </>
            ) : (
              <>
                <Archive size={14} />
                Archive
              </>
            )}
          </button>

          {isArchived && onHardDelete && (
            <button
              onClick={onHardDelete}
              disabled={busy}
              className="flex items-center justify-center gap-1.5 px-3 py-1.5 text-sm text-failed bg-bg hover:bg-failed/10 border border-failed/40 rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Trash2 size={14} />
              Hard delete
            </button>
          )}

          <button
            onClick={selection.clear}
            disabled={busy}
            className="flex items-center justify-center gap-1.5 px-3 py-1.5 text-sm text-muted hover:text-fg border border-border hover:border-accent/40 rounded-md transition-colors disabled:opacity-50"
          >
            <X size={14} />
            Clear
          </button>
        </div>
      </div>
    </div>
  );
}
