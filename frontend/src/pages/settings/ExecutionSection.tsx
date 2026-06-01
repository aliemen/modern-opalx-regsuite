import { useState } from "react";
import { AlertTriangle, Database, PlaySquare, X } from "lucide-react";
import { ExecutionSettingsSection } from "./ExecutionSettingsSection";
import { RunProfilesSection } from "./RunProfilesSection";

type ExecutionTab = "profiles" | "public";

function tabCls(active: boolean): string {
  return active
    ? "bg-accent text-bg"
    : "text-muted hover:text-fg border border-border";
}

export function ExecutionSection() {
  const [tab, setTab] = useState<ExecutionTab>("profiles");
  const [publicAcknowledged, setPublicAcknowledged] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmChecked, setConfirmChecked] = useState(false);

  function openPublicSettings() {
    if (tab === "public") return;
    if (publicAcknowledged) {
      setTab("public");
      return;
    }
    setConfirmChecked(false);
    setConfirmOpen(true);
  }

  function confirmPublicSettings() {
    if (!confirmChecked) return;
    setPublicAcknowledged(true);
    setConfirmOpen(false);
    setTab("public");
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2 sm:flex-row">
        <button
          type="button"
          onClick={() => setTab("profiles")}
          className={`inline-flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition ${tabCls(tab === "profiles")}`}
        >
          <PlaySquare size={15} />
          Run Profiles
        </button>
        <button
          type="button"
          onClick={openPublicSettings}
          className={`inline-flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition ${tabCls(tab === "public")}`}
        >
          <Database size={15} />
          Public Settings
        </button>
      </div>
      {tab === "profiles" ? <RunProfilesSection /> : <ExecutionSettingsSection />}
      {confirmOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
          onClick={() => setConfirmOpen(false)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="public-settings-warning-title"
            className="w-full max-w-lg rounded-xl border border-failed/40 bg-surface p-5 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start gap-3">
              <AlertTriangle size={22} className="mt-0.5 shrink-0 text-failed" />
              <div className="min-w-0 flex-1">
                <h2
                  id="public-settings-warning-title"
                  className="text-base font-semibold text-fg"
                >
                  Public settings warning
                </h2>
                <p className="mt-2 text-sm leading-relaxed text-muted">
                  DANGER: If you don't know what you're doing, don't change
                  anything here! Generally, this doesn't need to be changed.
                  Please confirm that you know what you're doing.
                </p>
              </div>
              <button
                type="button"
                aria-label="Close public settings warning"
                onClick={() => setConfirmOpen(false)}
                className="rounded-md p-1 text-muted hover:text-fg"
              >
                <X size={16} />
              </button>
            </div>
            <label className="mt-5 flex items-start gap-2 text-sm text-fg">
              <input
                type="checkbox"
                checked={confirmChecked}
                onChange={(e) => setConfirmChecked(e.target.checked)}
                className="mt-0.5 h-4 w-4 accent-accent"
              />
              Yes I know what I'm doing
            </label>
            <div className="mt-5 flex flex-wrap justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmOpen(false)}
                className="rounded-md border border-border px-4 py-1.5 text-sm text-muted transition hover:text-fg"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirmPublicSettings}
                disabled={!confirmChecked}
                className="rounded-md bg-failed/90 px-4 py-1.5 text-sm font-medium text-white transition hover:bg-failed disabled:cursor-not-allowed disabled:opacity-50"
              >
                Continue
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
