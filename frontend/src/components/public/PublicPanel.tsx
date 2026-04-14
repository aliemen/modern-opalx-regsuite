import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Globe2, GitBranch } from "lucide-react";
import { getPublicActivity, getPublicRuns } from "../../api/public";
import { ActivitySparkline } from "../stats/ActivitySparkline";
import { PublicRecentRunsTable } from "./PublicRecentRunsTable";

interface KpiTileProps {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  hint?: string;
}

function KpiTile({ icon, label, value, hint }: KpiTileProps) {
  return (
    <div className="bg-surface border border-border rounded-xl p-4 flex-1 min-w-[8rem]">
      <div className="text-muted text-xs flex items-center gap-1.5 mb-1">
        {icon}
        {label}
      </div>
      <div className="text-fg text-2xl font-semibold leading-tight">{value}</div>
      {hint && <div className="text-muted text-xs mt-1">{hint}</div>}
    </div>
  );
}

export function PublicPanel() {
  const { data: runsData } = useQuery({
    queryKey: ["public", "all-runs"],
    queryFn: () => getPublicRuns(10, 0),
    refetchInterval: 60_000,
  });

  const { data: activityData } = useQuery({
    queryKey: ["public", "activity"],
    queryFn: () => getPublicActivity(14),
    refetchInterval: 60_000,
  });

  const runs = runsData?.runs ?? [];
  const total = runsData?.total ?? 0;

  const { passedLast14d, failedLast14d, uniqueBranches } = useMemo(() => {
    const days = activityData?.days ?? [];
    const passed = days.reduce((s, d) => s + d.passed, 0);
    const failedOrBroken = days.reduce((s, d) => s + d.failed + d.broken, 0);
    const branchSet = new Set(runs.map((r) => r.branch));
    return {
      passedLast14d: passed,
      failedLast14d: failedOrBroken,
      uniqueBranches: branchSet.size,
    };
  }, [activityData, runs]);

  return (
    <div className="flex flex-col gap-4 w-full">
      <div>
        <h2 className="text-fg text-lg font-semibold flex items-center gap-2">
          <Globe2 size={18} />
          Public regression runs
        </h2>
        <p className="text-muted text-xs mt-1">
          A curated stream of OPALX regression runs that developers have
          chosen to publish. No login required.
        </p>
      </div>

      <div className="flex gap-3 flex-wrap">
        <KpiTile
          icon={<Globe2 size={12} />}
          label="Total public"
          value={total}
        />
        <KpiTile
          icon={<CheckCircle2 size={12} className="text-passed" />}
          label="Passed (14d)"
          value={passedLast14d}
          hint={failedLast14d > 0 ? `${failedLast14d} failed / broken` : undefined}
        />
        <KpiTile
          icon={<GitBranch size={12} />}
          label="Public branches"
          value={uniqueBranches}
          hint="in last 10 runs"
        />
      </div>

      <ActivitySparkline
        queryKey={["public", "activity-sparkline"]}
        fetcher={() => getPublicActivity(14)}
        title="Public activity (14d)"
      />

      <div>
        <h3 className="text-fg text-sm font-medium mb-2">Recent published runs</h3>
        <PublicRecentRunsTable runs={runs} />
      </div>
    </div>
  );
}
