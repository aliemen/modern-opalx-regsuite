import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { Clock, History } from "lucide-react";
import { getAllRuns, type RunIndexEntry } from "../api/results";
import { StatusBadge } from "../components/StatusBadge";
import { Pagination } from "../components/Pagination";

function fmtDate(d: string | null) {
  if (!d) return "\u2014";
  return new Date(d).toLocaleString();
}

function duration(start: string, end: string | null) {
  if (!end) return "\u2014";
  const s = Math.floor(
    (new Date(end).getTime() - new Date(start).getTime()) / 1000
  );
  const m = Math.floor(s / 60);
  return `${m}m ${(s % 60).toString().padStart(2, "0")}s`;
}

export function ActivityPage() {
  const [pageSize, setPageSize] = useState(25);
  const [offset, setOffset] = useState(0);

  const { data, isLoading } = useQuery({
    queryKey: ["all-runs", pageSize, offset],
    queryFn: () => getAllRuns(pageSize, offset),
    placeholderData: keepPreviousData,
  });

  const runs = data?.runs ?? [];
  const total = data?.total ?? 0;

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <h1 className="text-fg text-xl font-semibold mb-1 flex items-center gap-2">
        <History size={20} />
        Activity
      </h1>
      <p className="text-muted text-sm mb-6">{total} runs total</p>

      {isLoading && !data ? (
        <div className="text-muted text-sm">Loading...</div>
      ) : runs.length === 0 ? (
        <div className="text-muted text-sm">No runs found.</div>
      ) : (
        <>
          <div className="border border-border rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-surface text-muted text-left">
                <tr>
                  <th className="px-4 py-3 font-medium">Run ID</th>
                  <th className="px-4 py-3 font-medium">Branch</th>
                  <th className="px-4 py-3 font-medium">Arch</th>
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
                {runs.map((run: RunIndexEntry, i: number) => (
                  <tr
                    key={`${run.branch}-${run.arch}-${run.run_id}`}
                    className={`border-t border-border hover:bg-surface/50 transition-colors ${
                      i % 2 === 0 ? "" : "bg-surface/20"
                    }`}
                  >
                    <td className="px-4 py-3">
                      <Link
                        to={`/results/${run.branch}/${run.arch}/${run.run_id}`}
                        className="text-accent hover:underline font-mono text-xs"
                      >
                        {run.run_id}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-xs">{run.branch}</td>
                    <td className="px-4 py-3 text-xs">{run.arch}</td>
                    <td className="px-4 py-3">
                      <StatusBadge status={run.status} />
                    </td>
                    <td className="px-4 py-3 text-muted text-xs">
                      {fmtDate(run.started_at)}
                    </td>
                    <td className="px-4 py-3 text-muted text-xs">
                      {duration(run.started_at, run.finished_at)}
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {run.unit_tests_total - run.unit_tests_failed}/
                      {run.unit_tests_total}
                    </td>
                    <td className="px-4 py-3 text-xs">
                      <span className="text-passed">
                        {run.regression_passed}
                      </span>
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

          <Pagination
            total={total}
            pageSize={pageSize}
            offset={offset}
            onPageSizeChange={(s) => {
              setPageSize(s);
              setOffset(0);
            }}
            onOffsetChange={setOffset}
          />
        </>
      )}
    </div>
  );
}
