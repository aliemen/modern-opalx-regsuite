import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Shuffle } from "lucide-react";
import { getFlakiness, getLatestMaster } from "../../api/stats";

export function FlakinessCard({ archs: sortedArchs }: { archs?: string[] }) {
  const [selectedArch, setSelectedArch] = useState<string | null>(null);
  const { data: master } = useQuery({
    queryKey: ["dashboard-stats", "latest-master", "flakiness-archs"],
    queryFn: () => getLatestMaster("active"),
    refetchInterval: 60_000,
  });

  const archs = useMemo(() => {
    if (sortedArchs && sortedArchs.length > 0) return sortedArchs;
    return [...(master?.cells ?? [])]
      .sort((a, b) => b.regression_total - a.regression_total || a.arch.localeCompare(b.arch))
      .map((cell) => cell.arch);
  }, [master, sortedArchs]);
  const arch = selectedArch && archs.includes(selectedArch) ? selectedArch : archs[0] ?? "";

  const { data, isLoading } = useQuery({
    queryKey: ["dashboard-stats", "flakiness", "master", arch, "master"],
    queryFn: () => getFlakiness("master", arch, "master", 20),
    enabled: !!arch,
    refetchInterval: 60_000,
  });

  return (
    <div className="bg-surface border border-border rounded-xl p-5">
      <div className="flex items-center justify-between gap-3 mb-4">
        <h2 className="text-fg font-medium text-sm flex items-center gap-2">
          <Shuffle size={14} className="text-muted" />
          Flaky suspects
        </h2>
        {archs.length > 0 && (
          <select
            value={arch}
            onChange={(e) => setSelectedArch(e.target.value)}
            className="bg-bg border border-border rounded-md px-2 py-1 text-fg text-xs focus:outline-none focus:border-accent"
          >
            {archs.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        )}
      </div>

      {!arch ? (
        <p className="text-muted text-xs py-2">No master archs yet.</p>
      ) : isLoading && !data ? (
        <p className="text-muted text-xs py-2">Loading…</p>
      ) : !data || data.simulations.length === 0 ? (
        <p className="text-passed text-xs py-2">
          No flaky simulations in the last 20 master/master runs.
        </p>
      ) : (
        <div className="space-y-2">
          <p className="text-muted text-xs">
            {data.simulations.length} suspect
            {data.simulations.length !== 1 ? "s" : ""} across{" "}
            {data.runs_considered} runs.
          </p>
          <ul className="space-y-1">
            {data.simulations.slice(0, 6).map((sim) => (
              <li key={sim.name} className="text-xs">
                <p className="font-mono text-fg truncate" title={sim.name}>
                  {sim.name}
                </p>
                <p className="text-muted tabular-nums">
                  {sim.passed} pass / {sim.failed + sim.broken + sim.crashed} bad
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
