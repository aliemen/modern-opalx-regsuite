import { useEffect } from "react";
import { AlertTriangle, X } from "lucide-react";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  /** Label of the confirm button. */
  confirmLabel?: string;
  /** When true, the confirm button uses the "destructive" red styling. */
  destructive?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Minimal modal for destructive confirmations (unarchive, hard-delete).
 *
 * Closes on Escape, click-outside, or the X button. No portals; renders at
 * the top of the React tree wherever it's mounted because it's `fixed`.
 */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Confirm",
  destructive = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  if (!open) return null;

  const confirmCls = destructive
    ? "bg-failed/90 hover:bg-failed text-white"
    : "bg-accent/90 hover:bg-accent text-white";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={onCancel}
    >
      <div
        className="bg-surface border border-border rounded-xl p-6 max-w-md w-full mx-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3 mb-4">
          {destructive && (
            <AlertTriangle
              size={20}
              className="text-failed shrink-0 mt-0.5"
            />
          )}
          <div className="flex-1">
            <h2 className="text-fg font-semibold text-base mb-1">{title}</h2>
            <p className="text-muted text-sm leading-relaxed whitespace-pre-line">
              {message}
            </p>
          </div>
          <button
            onClick={onCancel}
            className="text-muted hover:text-fg transition-colors"
          >
            <X size={16} />
          </button>
        </div>
        <div className="flex items-center justify-end gap-2 mt-5">
          <button
            onClick={onCancel}
            className="px-4 py-1.5 text-sm text-muted hover:text-fg border border-border rounded-md transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className={`px-4 py-1.5 text-sm rounded-md transition-colors ${confirmCls}`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
