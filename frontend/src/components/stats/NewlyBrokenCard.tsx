import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Check } from "lucide-react";
import { getNewlyBroken } from "../../api/stats";

/**
 * "Newly broken (master)" — diff of failing regression simulations between
 * the latest two completed master runs, per arch.
 *
 * The single most actionable signal on the dashboard: tells a developer
 * which simulations they just broke. Empty (and a green check) when
 * everything that was passing is still passing.
 */
export function NewlyBrokenCard() {
  const { data, isLoading } = useQuery({
    queryKey: ["dashboard-stats", "newly-broken"],
    queryFn: () => getNewlyBroken("active"),
    refetchInterval: 60_000,
  });

  return (
    <div className="bg-surface border border-border rounded-xl p-5">
      <h2 className="text-fg font-medium text-sm mb-4 flex items-center gap-2">
        <AlertTriangle size={14} className="text-muted" />
        Newly broken (master)
      </h2>
      {isLoading && !data ? (
        <p className="text-muted text-xs py-2">Loading…</p>
      ) : !data || data.entries.length === 0 ? (
        <p className="text-muted text-xs py-2">No master runs yet.</p>
      ) : (
        <div className="space-y-3">
          {data.entries.map((entry) => (
            <div key={entry.arch} className="text-xs">
              <p className="text-muted mb-1">{entry.arch}</p>
              {!entry.enough_runs ? (
                <p className="text-muted/70 italic">
                  Need 2+ completed master runs.
                </p>
              ) : entry.sim_names.length === 0 ? (
                <p className="text-passed flex items-center gap-1">
                  <Check size={12} />
                  No new regressions.
                </p>
              ) : (
                <ul className="space-y-0.5">
                  {entry.sim_names.map((name) => (
                    <li
                      key={name}
                      className="text-failed font-mono truncate"
                      title={name}
                    >
                      {name}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
