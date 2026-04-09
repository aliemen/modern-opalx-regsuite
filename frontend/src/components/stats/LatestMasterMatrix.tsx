import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Cpu } from "lucide-react";
import { getLatestMaster } from "../../api/stats";
import { StatusBadge } from "../StatusBadge";

/**
 * Compact per-arch matrix showing the **current** state of master.
 *
 * Replaces the old "Unit/Regression master avg %" stats — those hide the
 * "broken" state entirely and show a long-term average that lags reality.
 * This card shows raw counts side by side so a developer can answer "are
 * we green right now?" in one glance.
 */
export function LatestMasterMatrix() {
  const { data, isLoading } = useQuery({
    queryKey: ["dashboard-stats", "latest-master"],
    queryFn: () => getLatestMaster("active"),
    refetchInterval: 60_000,
  });

  return (
    <div className="bg-surface border border-border rounded-xl p-5">
      <h2 className="text-fg font-medium text-sm mb-4">Master status</h2>
      {isLoading && !data ? (
        <p className="text-muted text-xs py-2">Loading…</p>
      ) : !data || data.cells.length === 0 ? (
        <p className="text-muted text-xs py-2">No master runs yet.</p>
      ) : (
        <div className="space-y-2">
          {data.cells.map((cell) => {
            const unitPassed = cell.unit_total - cell.unit_failed;
            const href = cell.run_id
              ? `/results/master/${cell.arch}/${cell.run_id}`
              : `/results/master/${cell.arch}`;
            return (
              <Link
                key={cell.arch}
                to={href}
                className="flex items-center gap-2 text-xs text-muted hover:text-fg p-2 rounded-md hover:bg-border/30 transition-colors"
              >
                <Cpu size={11} className="shrink-0" />
                <span className="text-fg font-medium w-28 truncate">
                  {cell.arch}
                </span>
                {cell.status ? (
                  <StatusBadge status={cell.status} />
                ) : (
                  <StatusBadge status="unknown" />
                )}
                <span className="ml-auto flex items-center gap-3">
                  <span title="Unit tests">
                    U {unitPassed}/{cell.unit_total}
                  </span>
                  <span title="Regression metrics">
                    R {cell.regression_passed}/{cell.regression_total}
                  </span>
                  {cell.regression_failed > 0 && (
                    <span className="text-failed">
                      {cell.regression_failed}f
                    </span>
                  )}
                  {cell.regression_broken > 0 && (
                    <span className="text-broken">
                      {cell.regression_broken}b
                    </span>
                  )}
                </span>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
