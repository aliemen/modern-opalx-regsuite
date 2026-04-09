import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getActivity, type ActivityDay } from "../../api/stats";
import { useThemeColors } from "../../hooks/useThemeColors";

interface ChartPoint {
  label: string;
  passed: number;
  failed: number;
  broken: number;
}

function toChartData(days: ActivityDay[]): ChartPoint[] {
  return days.map((d) => ({
    label: new Date(d.date).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    }),
    passed: d.passed,
    failed: d.failed,
    broken: d.broken,
  }));
}

/**
 * "Activity (14d)" — daily run-count breakdown over the last 14 days
 * across all branches and archs. Shows volume + health at a glance,
 * complementing the per-master-arch trend chart with a CI-wide view.
 */
export function ActivitySparkline() {
  const colors = useThemeColors();

  const { data } = useQuery({
    queryKey: ["dashboard-stats", "activity"],
    queryFn: () => getActivity(14, "active"),
    refetchInterval: 60_000,
  });

  const chartData = useMemo(() => toChartData(data?.days ?? []), [data]);
  const hasAnyRuns = chartData.some(
    (c) => c.passed + c.failed + c.broken > 0
  );

  return (
    <div className="bg-surface border border-border rounded-xl p-5">
      <h2 className="text-fg font-medium text-sm mb-4 flex items-center gap-2">
        <Activity size={14} className="text-muted" />
        Activity (14d)
      </h2>
      {!hasAnyRuns ? (
        <p className="text-muted text-xs py-2">
          No runs in the last 14 days.
        </p>
      ) : (
        <ResponsiveContainer width="100%" height={140}>
          <BarChart data={chartData} barCategoryGap={2}>
            <CartesianGrid strokeDasharray="3 3" stroke={colors.border} />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 10, fill: colors.muted }}
              tickLine={false}
              axisLine={{ stroke: colors.border }}
              interval={1}
            />
            <YAxis
              tick={{ fontSize: 10, fill: colors.muted }}
              tickLine={false}
              axisLine={{ stroke: colors.border }}
              allowDecimals={false}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: colors.surface,
                border: `1px solid ${colors.border}`,
                borderRadius: 8,
                fontSize: 12,
              }}
              labelStyle={{ color: colors.fg }}
            />
            <Legend wrapperStyle={{ fontSize: 11, color: colors.muted }} />
            <Bar dataKey="passed" stackId="s" fill="#22c55e" name="passed" />
            <Bar dataKey="failed" stackId="s" fill="#ef4444" name="failed" />
            <Bar dataKey="broken" stackId="s" fill="#f59e0b" name="broken" />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
