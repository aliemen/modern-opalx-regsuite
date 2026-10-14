import type { SkipConfigSnapshot } from "../../api/results";
import { StatusBadge } from "../../components/StatusBadge";

export function SkipConfigInfo({ snapshot }: { snapshot: SkipConfigSnapshot }) {
  const names = [...snapshot.regression_tests, ...snapshot.unit_tests];
  return (
    <div className="space-y-1 sm:col-span-2">
      <p className="text-muted text-xs">Test Skip Config</p>
      <p className="text-fg text-sm">{snapshot.name}</p>
      {names.length > 0 && (
        <p className="text-muted text-xs font-mono break-words">{names.join(", ")}</p>
      )}
    </div>
  );
}

export function SkippedSimulationsGroup({ names }: { names: string[] }) {
  if (names.length === 0) return null;
  return (
    <details className="bg-surface border border-dashed border-border rounded-xl">
      <summary className="cursor-pointer px-5 py-3 text-sm text-muted">
        Skipped ({names.length})
      </summary>
      <ul className="border-t border-border px-5 py-3 space-y-1">
        {names.map((name) => (
          <li key={name} className="flex items-center gap-2 text-xs">
            <span className="font-mono text-fg">{name}</span>
            <StatusBadge status="skipped" />
          </li>
        ))}
      </ul>
    </details>
  );
}
