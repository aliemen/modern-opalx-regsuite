import { useState } from "react";
import { useQuery, useQueries } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ChevronDown, ChevronRight, Clock, Cpu, FlaskConical, GitBranch } from "lucide-react";
import { getRuns, type RunIndexEntry } from "../api/results";
import { StatusBadge } from "./StatusBadge";

function fmtDate(d: string | null) {
  if (!d) return "\u2014";
  return new Date(d).toLocaleString();
}

function LatestCard({
  branch,
  arch,
  run,
}: {
  branch: string;
  arch: string;
  run: RunIndexEntry | undefined;
}) {
  return (
    <Link
      to={
        run
          ? `/results/${branch}/${arch}/${run.run_id}`
          : `/results/${branch}/${arch}`
      }
      className="block bg-surface border border-border rounded-xl p-5 hover:border-accent/40 transition-colors"
    >
      <div className="flex items-start justify-between mb-3">
        <p className="text-muted text-xs flex items-center gap-1">
          <Cpu size={11} />
          {arch}
        </p>
        {run ? (
          <StatusBadge status={run.status} />
        ) : (
          <StatusBadge status="unknown" />
        )}
      </div>
      {run ? (
        <div className="text-xs text-muted space-y-1">
          <p className="flex items-center gap-1">
            <Clock size={11} />
            {fmtDate(run.started_at)}
          </p>
          <p className="flex items-center gap-1">
            <FlaskConical size={11} />
            Regression: {run.regression_passed}/{run.regression_total} passed
            {run.regression_failed > 0 && (
              <span className="text-failed">
                , {run.regression_failed} failed
              </span>
            )}
          </p>
          <p>
            Unit: {run.unit_tests_total - run.unit_tests_failed}/
            {run.unit_tests_total} passed
          </p>
        </div>
      ) : (
        <p className="text-xs text-muted">No runs yet.</p>
      )}
    </Link>
  );
}

function useLatestRun(branch: string, arch: string) {
  return useQuery({
    queryKey: ["runs", branch, arch],
    queryFn: () => getRuns(branch, arch, 1, 0),
    refetchInterval: 30_000,
    select: (data) => data[0] as RunIndexEntry | undefined,
  });
}

function ArchCard({
  branch,
  arch,
}: {
  branch: string;
  arch: string;
}) {
  const { data: run } = useLatestRun(branch, arch);
  return <LatestCard branch={branch} arch={arch} run={run} />;
}

/** Count how many archs have each status using a single useQueries call. */
function useSummary(branch: string, archs: string[]) {
  const results = useQueries({
    queries: archs.map((arch) => ({
      queryKey: ["runs", branch, arch],
      queryFn: () => getRuns(branch, arch, 1, 0),
      refetchInterval: 30_000,
      select: (data: RunIndexEntry[]) => data[0] as RunIndexEntry | undefined,
    })),
  });
  const counts: Record<string, number> = {};
  for (const { data: run } of results) {
    const status = run?.status ?? "unknown";
    counts[status] = (counts[status] ?? 0) + 1;
  }
  return counts;
}

const SUMMARY_COLORS: Record<string, string> = {
  passed: "text-passed",
  failed: "text-failed",
  broken: "text-broken",
  running: "text-accent",
  cancelled: "text-cancelled",
};

export function BranchSection({
  branch,
  archs,
  defaultOpen = false,
}: {
  branch: string;
  archs: string[];
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const counts = useSummary(branch, archs);

  return (
    <div className="border border-border rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-5 py-3.5 bg-surface hover:bg-border/30 text-left transition-colors"
      >
        {open ? (
          <ChevronDown size={14} className="text-muted shrink-0" />
        ) : (
          <ChevronRight size={14} className="text-muted shrink-0" />
        )}
        <GitBranch size={14} className="text-muted shrink-0" />
        <span className="text-fg font-medium text-sm">{branch}</span>
        <span className="text-muted text-xs ml-1">
          {archs.length} arch{archs.length !== 1 ? "s" : ""}
        </span>

        {/* Summary badges */}
        <div className="ml-auto flex items-center gap-3 text-xs">
          {Object.entries(counts)
            .filter(([s]) => s !== "unknown")
            .map(([status, count]) => (
              <span
                key={status}
                className={`${SUMMARY_COLORS[status] ?? "text-muted"} font-medium`}
              >
                {count} {status}
              </span>
            ))}
        </div>
      </button>

      {open && (
        <div className="border-t border-border p-4">
          <div className="grid gap-4 sm:grid-cols-2">
            {archs.map((arch) => (
              <ArchCard key={arch} branch={branch} arch={arch} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
