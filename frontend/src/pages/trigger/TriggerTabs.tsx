export type TriggerTab = "basic" | "advanced";

interface TriggerTabsProps {
  activeTab: TriggerTab;
  onChange: (tab: TriggerTab) => void;
}

export function TriggerTabs({ activeTab, onChange }: TriggerTabsProps) {
  return (
    <div className="grid grid-cols-2 rounded-md border border-border bg-bg p-1 text-sm">
      <button
        type="button"
        onClick={() => onChange("basic")}
        className={`rounded px-3 py-1.5 transition ${
          activeTab === "basic"
            ? "bg-border/70 text-fg"
            : "text-muted hover:text-fg"
        }`}
      >
        Basic
      </button>
      <button
        type="button"
        onClick={() => onChange("advanced")}
        className={`rounded px-3 py-1.5 transition ${
          activeTab === "advanced"
            ? "bg-border/70 text-fg"
            : "text-muted hover:text-fg"
        }`}
      >
        Advanced
      </button>
    </div>
  );
}
