import { useState } from "react";
import { Database, PlaySquare } from "lucide-react";
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
          onClick={() => setTab("public")}
          className={`inline-flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition ${tabCls(tab === "public")}`}
        >
          <Database size={15} />
          Public Settings
        </button>
      </div>
      {tab === "profiles" ? <RunProfilesSection /> : <ExecutionSettingsSection />}
    </div>
  );
}

