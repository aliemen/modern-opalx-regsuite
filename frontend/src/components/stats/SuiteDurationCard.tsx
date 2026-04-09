import { useQuery } from "@tanstack/react-query";
import { Clock, TrendingDown, TrendingUp } from "lucide-react";
import { getSuiteDuration } from "../../api/stats";

function fmtSeconds(s: number | null): string {
  if (s == null) return "—";
  if (s < 60) return `${s.toFixed(0)}s`;
  const m = Math.floor(s / 60);
  const rem = Math.round(s - m * 60);
  return `${m}m ${rem}s`;
}

function deltaClass(delta: number | null): string {
  if (delta == null) return "text-muted";
  if (delta > 20) return "text-failed";
  if (delta > 5) return "text-broken";
  if (delta < -5) return "text-passed";
  return "text-muted";
}

/**
 * "Suite duration (master)" — current run vs avg of the previous 10
 * completed master runs, per arch.
 *
 * Catches performance regressions that pass/fail counts hide entirely.
 * Threshold colours: >20% slower = failed, >5% slower = broken, <-5% =
 * faster (passed), else muted.
 */
export function SuiteDurationCard() {
  const { data, isLoading } = useQuery({
    queryKey: ["dashboard-stats", "suite-duration"],
    queryFn: () => getSuiteDuration("active"),
    refetchInterval: 60_000,
  });

  return (
    <div className="bg-surface border border-border rounded-xl p-5">
      <h2 className="text-fg font-medium text-sm mb-4 flex items-center gap-2">
        <Clock size={14} className="text-muted" />
        Suite duration (master)
      </h2>
      {isLoading && !data ? (
        <p className="text-muted text-xs py-2">Loading…</p>
      ) : !data || data.cells.length === 0 ? (
        <p className="text-muted text-xs py-2">No master runs yet.</p>
      ) : (
        <div className="space-y-2">
          {data.cells.map((cell) => {
            const cls = deltaClass(cell.delta_pct);
            const Icon =
              cell.delta_pct != null && cell.delta_pct > 0
                ? TrendingUp
                : TrendingDown;
            return (
              <div
                key={cell.arch}
                className="flex items-center gap-2 text-xs"
              >
                <span className="text-muted w-28 truncate">{cell.arch}</span>
                <span className="text-fg font-medium">
                  {fmtSeconds(cell.current_seconds)}
                </span>
                {cell.delta_pct != null && (
                  <span className={`flex items-center gap-0.5 ${cls}`}>
                    <Icon size={11} />
                    {cell.delta_pct > 0 ? "+" : ""}
                    {cell.delta_pct.toFixed(1)}%
                  </span>
                )}
                {cell.avg_last_10_seconds != null && (
                  <span className="ml-auto text-muted/70">
                    avg {fmtSeconds(cell.avg_last_10_seconds)}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
