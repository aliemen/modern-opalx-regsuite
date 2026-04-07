import { useQuery } from "@tanstack/react-query";
import {
  BarChart3,
  Calendar,
  Clock,
  GitBranch,
  FlaskConical,
  TestTubes,
} from "lucide-react";
import { getDashboardStats } from "../api/runs";

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

function MiniBar({ value }: { value: number }) {
  const color =
    value >= 90 ? "bg-passed" : value >= 70 ? "bg-broken" : "bg-failed";
  return (
    <div className="w-full h-1.5 bg-border rounded-full mt-1">
      <div
        className={`h-full rounded-full ${color}`}
        style={{ width: `${Math.min(value, 100)}%` }}
      />
    </div>
  );
}

export function StatsPanel() {
  const { data: stats } = useQuery({
    queryKey: ["dashboard-stats"],
    queryFn: getDashboardStats,
    refetchInterval: 60_000,
  });

  if (!stats) return null;

  const items = [
    {
      icon: Clock,
      label: "Last Run",
      value: stats.last_run ? relativeTime(stats.last_run) : "—",
    },
    {
      icon: BarChart3,
      label: "Runs Overall",
      value: stats.runs_total.toString(),
    },
    {
      icon: Calendar,
      label: "Last 7 Days",
      value: stats.runs_last_week.toString(),
    },
    {
      icon: GitBranch,
      label: "Branches",
      value: stats.branches_covered.toString(),
    },
  ];

  return (
    <div className="bg-surface border border-border rounded-xl p-5">
      <h2 className="text-fg font-medium text-sm mb-4">Statistics</h2>

      <div className="grid grid-cols-2 gap-3">
        {items.map((item) => (
          <div key={item.label} className="flex items-start gap-2">
            <item.icon size={13} className="text-muted mt-0.5 shrink-0" />
            <div>
              <p className="text-muted text-xs">{item.label}</p>
              <p className="text-fg font-medium text-sm">{item.value}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Pass rates */}
      <div className="mt-4 pt-3 border-t border-border space-y-2.5">
        <div>
          <div className="flex items-center justify-between">
            <span className="text-muted text-xs flex items-center gap-1.5">
              <TestTubes size={11} /> Unit Tests (master avg)
            </span>
            <span className="text-fg text-xs font-medium">
              {stats.avg_unit_pass_rate_master != null
                ? `${stats.avg_unit_pass_rate_master.toFixed(1)}%`
                : "—"}
            </span>
          </div>
          {stats.avg_unit_pass_rate_master != null && (
            <MiniBar value={stats.avg_unit_pass_rate_master} />
          )}
        </div>
        <div>
          <div className="flex items-center justify-between">
            <span className="text-muted text-xs flex items-center gap-1.5">
              <FlaskConical size={11} /> Regression (master avg)
            </span>
            <span className="text-fg text-xs font-medium">
              {stats.avg_regression_pass_rate_master != null
                ? `${stats.avg_regression_pass_rate_master.toFixed(1)}%`
                : "—"}
            </span>
          </div>
          {stats.avg_regression_pass_rate_master != null && (
            <MiniBar value={stats.avg_regression_pass_rate_master} />
          )}
        </div>
      </div>
    </div>
  );
}
