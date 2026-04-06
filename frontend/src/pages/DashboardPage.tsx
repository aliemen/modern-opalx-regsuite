import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Clock, FlaskConical, Cpu, Radio } from "lucide-react";
import { getBranches, getRuns, type RunIndexEntry } from "../api/results";
import { getCurrentRun } from "../api/runs";
import { StatusBadge } from "../components/StatusBadge";

function fmtDate(d: string | null) {
  if (!d) return "—";
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
      to={run ? `/results/${branch}/${arch}/${run.run_id}` : `/results/${branch}/${arch}`}
      className="block bg-surface border border-border rounded-xl p-5 hover:border-accent/40 transition-colors"
    >
      <div className="flex items-start justify-between mb-3">
        <div>
          <p className="text-white font-medium text-sm">{branch}</p>
          <p className="text-muted text-xs flex items-center gap-1 mt-0.5">
            <Cpu size={11} />
            {arch}
          </p>
        </div>
        {run ? <StatusBadge status={run.status} /> : <StatusBadge status="unknown" />}
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
              <span className="text-failed">, {run.regression_failed} failed</span>
            )}
          </p>
          <p>Unit: {run.unit_tests_total - run.unit_tests_failed}/{run.unit_tests_total} passed</p>
        </div>
      ) : (
        <p className="text-xs text-muted">No runs yet.</p>
      )}
    </Link>
  );
}

function ArchCard({ branch, arch }: { branch: string; arch: string }) {
  const { data: runs } = useQuery({
    queryKey: ["runs", branch, arch],
    queryFn: () => getRuns(branch, arch, 1, 0),
    refetchInterval: 30_000,
  });
  return <LatestCard branch={branch} arch={arch} run={runs?.[0]} />;
}

export function DashboardPage() {
  const { data: branches, isLoading } = useQuery({
    queryKey: ["branches"],
    queryFn: getBranches,
    refetchInterval: 60_000,
  });

  const { data: activeRun } = useQuery({
    queryKey: ["current-run"],
    queryFn: getCurrentRun,
    refetchInterval: 5000,
  });

  if (isLoading) {
    return <div className="p-8 text-muted">Loading…</div>;
  }

  const entries = Object.entries(branches ?? {});

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {activeRun && activeRun.status === "running" ? (
        <Link
          to="/live"
          className="flex items-center gap-3 bg-accent/10 border border-accent/30 rounded-xl px-5 py-3 mb-6 text-accent text-sm hover:bg-accent/20 transition-colors"
        >
          <span className="w-2 h-2 rounded-full bg-accent animate-ping inline-block" />
          Run in progress — {activeRun.branch} / {activeRun.arch} — phase: {activeRun.phase}
          <span className="ml-auto text-xs underline">View live output →</span>
        </Link>
      ) : (
        <Link
          to="/live"
          className="flex items-center gap-2 text-muted hover:text-white text-sm mb-6 w-fit transition-colors"
        >
          <Radio size={13} /> Latest run log
        </Link>
      )}

      <h1 className="text-white text-2xl font-semibold mb-6">Dashboard</h1>

      {entries.length === 0 ? (
        <div className="text-muted text-sm">
          No results yet.{" "}
          <Link to="/trigger" className="text-accent hover:underline">
            Start a run
          </Link>{" "}
          to get started.
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {entries.flatMap(([branch, archs]) =>
            archs.map((arch) => (
              <ArchCard key={`${branch}-${arch}`} branch={branch} arch={arch} />
            ))
          )}
        </div>
      )}
    </div>
  );
}
