import { Link } from "react-router-dom";
import { Clock } from "lucide-react";
import type { RunIndexEntry } from "../../api/results";
import { StatusBadge } from "../StatusBadge";

function fmtDate(d: string | null) {
  if (!d) return "\u2014";
  return new Date(d).toLocaleString();
}

interface PublicRecentRunsTableProps {
  runs: RunIndexEntry[];
}

export function PublicRecentRunsTable({ runs }: PublicRecentRunsTableProps) {
  if (runs.length === 0) {
    return (
      <div className="bg-surface border border-border rounded-xl p-5 text-muted text-sm">
        No published runs yet. When a developer publishes a run from the run
        detail page, it will appear here.
      </div>
    );
  }

  return (
    <div className="border border-border rounded-xl overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-surface text-muted text-left">
          <tr>
            <th className="px-4 py-3 font-medium">Run</th>
            <th className="px-4 py-3 font-medium">Branch / Arch</th>
            <th className="px-4 py-3 font-medium">Status</th>
            <th className="px-4 py-3 font-medium">
              <Clock size={12} className="inline mr-1" />
              Started
            </th>
            <th className="px-4 py-3 font-medium">Regression</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run: RunIndexEntry, i: number) => (
            <tr
              key={`${run.branch}-${run.arch}-${run.run_id}`}
              className={`border-t border-border hover:bg-surface/50 transition-colors ${
                i % 2 === 0 ? "" : "bg-surface/20"
              }`}
            >
              <td className="px-4 py-3">
                <Link
                  to={`/public/runs/${encodeURIComponent(run.branch)}/${encodeURIComponent(run.arch)}/${encodeURIComponent(run.run_id)}`}
                  className="text-accent hover:underline font-mono text-xs"
                >
                  {run.run_id}
                </Link>
              </td>
              <td className="px-4 py-3 text-xs">
                <div>{run.branch}</div>
                <div className="text-muted">{run.arch}</div>
              </td>
              <td className="px-4 py-3">
                <StatusBadge status={run.status} />
              </td>
              <td className="px-4 py-3 text-muted text-xs">
                {fmtDate(run.started_at)}
              </td>
              <td className="px-4 py-3 text-xs">
                <span className="text-passed">{run.regression_passed}</span>
                {" / "}
                {run.regression_total}
                {run.regression_failed > 0 && (
                  <span className="text-failed ml-1">
                    ({run.regression_failed} fail)
                  </span>
                )}
                {run.regression_broken > 0 && (
                  <span className="text-broken ml-1">
                    ({run.regression_broken} broken)
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
