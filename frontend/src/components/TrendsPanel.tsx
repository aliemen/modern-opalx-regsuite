import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { TrendingUp } from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { getRuns, type RunIndexEntry } from "../api/results";
import { useThemeColors } from "../hooks/useThemeColors";

interface TrendPoint {
  date: string;
  unitPassRate: number | null;
  regressionPassRate: number | null;
}

function toTrendData(runs: RunIndexEntry[]): TrendPoint[] {
  return [...runs]
    .sort(
      (a, b) =>
        new Date(a.started_at).getTime() - new Date(b.started_at).getTime()
    )
    .map((r) => ({
      date: new Date(r.started_at).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
      }),
      unitPassRate:
        r.unit_tests_total > 0
          ? ((r.unit_tests_total - r.unit_tests_failed) / r.unit_tests_total) *
            100
          : null,
      regressionPassRate:
        r.regression_total > 0
          ? (r.regression_passed / r.regression_total) * 100
          : null,
    }));
}

export function TrendsPanel({ archs }: { archs: string[] }) {
  const [selectedArch, setSelectedArch] = useState(archs[0] ?? "");
  const colors = useThemeColors();

  const { data: runs } = useQuery({
    queryKey: ["trend-runs", "master", selectedArch],
    queryFn: () => getRuns("master", selectedArch, 20, 0),
    refetchInterval: 60_000,
    enabled: !!selectedArch,
  });

  const trendData = useMemo(() => toTrendData(runs ?? []), [runs]);

  return (
    <div className="bg-surface border border-border rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-fg font-medium text-sm flex items-center gap-2">
          <TrendingUp size={15} />
          Pass Rate Trends
        </h2>
        <select
          value={selectedArch}
          onChange={(e) => setSelectedArch(e.target.value)}
          className="bg-bg border border-border rounded-md px-2 py-1 text-fg text-xs focus:outline-none focus:border-accent"
        >
          {archs.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
      </div>

      {trendData.length === 0 ? (
        <p className="text-muted text-sm py-12 text-center">
          No data yet for master / {selectedArch}.
        </p>
      ) : (
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={trendData}>
            <CartesianGrid strokeDasharray="3 3" stroke={colors.border} />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 11, fill: colors.muted }}
              tickLine={false}
              axisLine={{ stroke: colors.border }}
            />
            <YAxis
              domain={[0, 100]}
              tick={{ fontSize: 11, fill: colors.muted }}
              tickLine={false}
              axisLine={{ stroke: colors.border }}
              tickFormatter={(v: number) => `${v}%`}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: colors.surface,
                border: `1px solid ${colors.border}`,
                borderRadius: 8,
                fontSize: 12,
              }}
              labelStyle={{ color: colors.fg }}
              formatter={(value) => value != null ? `${Number(value).toFixed(1)}%` : ""}
            />
            <Legend wrapperStyle={{ fontSize: 12, color: colors.muted }} />
            <Line
              type="monotone"
              dataKey="unitPassRate"
              name="Unit Tests"
              stroke={colors.accent}
              strokeWidth={2}
              dot={{ r: 3 }}
              activeDot={{ r: 5 }}
              connectNulls
            />
            <Line
              type="monotone"
              dataKey="regressionPassRate"
              name="Regression"
              stroke="#22c55e"
              strokeWidth={2}
              dot={{ r: 3 }}
              activeDot={{ r: 5 }}
              connectNulls
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
