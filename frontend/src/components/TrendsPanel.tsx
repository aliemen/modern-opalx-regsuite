import { useState, useMemo } from "react";
import { useQuery, useQueries } from "@tanstack/react-query";
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
  /** Tick label including time (e.g. "Apr 9, 14:23").
   *
   * Older versions used just `Apr 9` which collapsed multiple runs on the
   * same day into duplicated x-axis labels. Recharts treated each row as a
   * separate slot (so the tooltip values were correct), but visually it
   * looked like the tooltip didn't match the dot positions. Including the
   * minute disambiguates them.
   */
  label: string;
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
      label: new Date(r.started_at).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
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
  // Reuse the counts already cached by useLatestRuns (same query keys) to sort
  // the dropdown by number of runs descending — no extra network requests.
  const countQueries = useQueries({
    queries: archs.map((arch) => ({
      queryKey: ["runs", "master", arch, "active", null] as const,
      queryFn: () => getRuns("master", arch, 1, 0, "active", null),
      staleTime: 30_000,
    })),
  });

  const sortedArchs = useMemo(() => {
    const counts = new Map(
      archs.map((arch, i) => [arch, countQueries[i]?.data?.total ?? 0])
    );
    return [...archs].sort((a, b) => (counts.get(b) ?? 0) - (counts.get(a) ?? 0));
  }, [archs, countQueries]);

  // Default to the arch with the most runs; user selection overrides.
  const [selectedArch, setSelectedArch] = useState("");
  const effectiveArch = selectedArch || sortedArchs[0] || "";

  const colors = useThemeColors();

  const { data } = useQuery({
    queryKey: ["trend-runs", "master", effectiveArch],
    queryFn: () => getRuns("master", effectiveArch, 20, 0),
    refetchInterval: 60_000,
    enabled: !!effectiveArch,
  });

  const trendData = useMemo(() => toTrendData(data?.runs ?? []), [data]);

  return (
    <div className="bg-surface border border-border rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-fg font-medium text-sm flex items-center gap-2">
          <TrendingUp size={15} />
          Pass Rate Trends
        </h2>
        <select
          value={effectiveArch}
          onChange={(e) => setSelectedArch(e.target.value)}
          className="bg-bg border border-border rounded-md px-2 py-1 text-fg text-xs focus:outline-none focus:border-accent"
        >
          {sortedArchs.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
      </div>

      {trendData.length === 0 ? (
        <p className="text-muted text-sm py-12 text-center">
          No data yet for master / {effectiveArch}.
        </p>
      ) : (
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={trendData} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={colors.border} />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 10, fill: colors.muted }}
              tickLine={false}
              axisLine={{ stroke: colors.border }}
              interval="preserveStartEnd"
              minTickGap={24}
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
