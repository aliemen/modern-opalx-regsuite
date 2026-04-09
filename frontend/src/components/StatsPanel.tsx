import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Clock } from "lucide-react";
import { getDashboardStats } from "../api/runs";
import { LatestMasterMatrix } from "./stats/LatestMasterMatrix";
import { NewlyBrokenCard } from "./stats/NewlyBrokenCard";
import { SuiteDurationCard } from "./stats/SuiteDurationCard";
import { ActivitySparkline } from "./stats/ActivitySparkline";
import { StatusBadge } from "./StatusBadge";

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

/** Tiny "Last run" tile, top of the stats column. Lightweight liveness check. */
function LastRunTile() {
  const { data: stats } = useQuery({
    queryKey: ["dashboard-stats"],
    queryFn: getDashboardStats,
    refetchInterval: 60_000,
  });

  if (!stats) return null;

  const href =
    stats.last_run_branch && stats.last_run_arch
      ? `/results/${stats.last_run_branch}/${stats.last_run_arch}`
      : null;

  const inner = (
    <div className="bg-surface border border-border rounded-xl p-5 hover:border-accent/40 transition-colors">
      <div className="flex items-center gap-2 mb-2">
        <Clock size={13} className="text-muted" />
        <span className="text-muted text-xs">Last run</span>
        {stats.last_run_status && (
          <span className="ml-auto">
            <StatusBadge status={stats.last_run_status} />
          </span>
        )}
      </div>
      <p className="text-fg font-medium text-sm">
        {stats.last_run ? relativeTime(stats.last_run) : "—"}
      </p>
      {stats.last_run_branch && stats.last_run_arch && (
        <p className="text-muted text-xs mt-1">
          {stats.last_run_branch} / {stats.last_run_arch}
        </p>
      )}
    </div>
  );

  return href ? <Link to={href}>{inner}</Link> : inner;
}

/**
 * Composes the developer-facing stats column. Each card fetches its own
 * endpoint via React Query so the cards are independently shippable and
 * any single-card failure doesn't take down the whole panel.
 */
export function StatsPanel() {
  return (
    <div className="space-y-4">
      <LastRunTile />
      <LatestMasterMatrix />
      <NewlyBrokenCard />
      <SuiteDurationCard />
      <ActivitySparkline />
    </div>
  );
}
