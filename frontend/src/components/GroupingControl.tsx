import { Calendar, Cpu, GitBranch, Group as GroupIcon } from "lucide-react";
import type { GroupBy } from "../lib/grouping";

interface GroupingControlProps {
  value: GroupBy;
  onChange: (value: GroupBy) => void;
  /** Restrict which options are shown. Defaults to all four options. */
  allowedValues?: GroupBy[];
}

const OPTIONS: {
  value: GroupBy;
  label: string;
  icon: typeof GitBranch;
}[] = [
  { value: "branch", label: "Branch", icon: GitBranch },
  { value: "arch", label: "Architecture", icon: Cpu },
  { value: "date", label: "Last run", icon: Calendar },
  { value: "regtest-branch", label: "Reg Branch", icon: GitBranch },
];

/**
 * Pill-style segmented control above the accordion. Lets the user pick the
 * grouping axis. Stateless — the parent owns the value and persistence
 * (URL query param + localStorage fallback).
 */
export function GroupingControl({ value, onChange, allowedValues }: GroupingControlProps) {
  const visibleOptions = allowedValues
    ? OPTIONS.filter((o) => allowedValues.includes(o.value))
    : OPTIONS;
  return (
    <div className="flex items-center gap-3 mb-4">
      <span className="flex items-center gap-1.5 text-muted text-xs">
        <GroupIcon size={13} />
        Group by
      </span>
      <div className="inline-flex border border-border rounded-lg overflow-hidden bg-surface">
        {visibleOptions.map((opt) => {
          const Icon = opt.icon;
          const active = value === opt.value;
          return (
            <button
              key={opt.value}
              onClick={() => onChange(opt.value)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs transition-colors ${
                active
                  ? "bg-accent/15 text-accent"
                  : "text-muted hover:text-fg hover:bg-border/30"
              }`}
            >
              <Icon size={12} />
              {opt.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
