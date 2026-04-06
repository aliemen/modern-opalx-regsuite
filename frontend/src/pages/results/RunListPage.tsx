import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Clock } from "lucide-react";
import { getRuns } from "../../api/results";
import { StatusBadge } from "../../components/StatusBadge";

function fmtDate(d: string | null) {
  if (!d) return "—";
  return new Date(d).toLocaleString();
}

function duration(start: string, end: string | null) {
  if (!end) return "—";
  const s = Math.floor((new Date(end).getTime() - new Date(start).getTime()) / 1000);
  const m = Math.floor(s / 60);
  return `${m}m ${(s % 60).toString().padStart(2, "0")}s`;
}

export function RunListPage() {
  const { branch, arch } = useParams<{ branch: string; arch: string }>();

  const { data: runs, isLoading } = useQuery({
    queryKey: ["runs", branch, arch],
    queryFn: () => getRuns(branch!, arch!, 50, 0),
    enabled: !!branch && !!arch,
  });

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <Link
        to="/"
        className="flex items-center gap-1.5 text-muted hover:text-white text-sm mb-4 transition-colors"
      >
        <ArrowLeft size={14} /> Dashboard
      </Link>
      <h1 className="text-white text-xl font-semibold mb-1">
        {branch} / {arch}
      </h1>
      <p className="text-muted text-sm mb-6">{runs?.length ?? 0} runs</p>

      {isLoading ? (
        <div className="text-muted text-sm">Loading…</div>
      ) : !runs || runs.length === 0 ? (
        <div className="text-muted text-sm">No runs found.</div>
      ) : (
        <div className="border border-border rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-surface text-muted text-left">
              <tr>
                <th className="px-4 py-3 font-medium">Run ID</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">
                  <Clock size={12} className="inline mr-1" />
                  Started
                </th>
                <th className="px-4 py-3 font-medium">Duration</th>
                <th className="px-4 py-3 font-medium">Unit</th>
                <th className="px-4 py-3 font-medium">Regression</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run, i) => (
                <tr
                  key={run.run_id}
                  className={`border-t border-border hover:bg-surface/50 transition-colors ${i % 2 === 0 ? "" : "bg-surface/20"}`}
                >
                  <td className="px-4 py-3">
                    <Link
                      to={`/results/${branch}/${arch}/${run.run_id}`}
                      className="text-accent hover:underline font-mono text-xs"
                    >
                      {run.run_id}
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={run.status} />
                  </td>
                  <td className="px-4 py-3 text-muted text-xs">{fmtDate(run.started_at)}</td>
                  <td className="px-4 py-3 text-muted text-xs">
                    {duration(run.started_at, run.finished_at)}
                  </td>
                  <td className="px-4 py-3 text-xs">
                    {run.unit_tests_total - run.unit_tests_failed}/{run.unit_tests_total}
                  </td>
                  <td className="px-4 py-3 text-xs">
                    <span className="text-passed">{run.regression_passed}</span>
                    {" / "}
                    {run.regression_total}
                    {run.regression_failed > 0 && (
                      <span className="text-failed ml-1">({run.regression_failed} fail)</span>
                    )}
                    {run.regression_broken > 0 && (
                      <span className="text-broken ml-1">({run.regression_broken} broken)</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
