import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { Clock, History, User as UserIcon } from "lucide-react";
import { getAllRuns, type RunIndexEntry } from "../api/results";
import { getUsersLeaderboard } from "../api/stats";
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
  const [searchParams, setSearchParams] = useSearchParams();
  const userParam = searchParams.get("user");
  const triggeredBy = userParam && userParam !== "" ? userParam : null;

  const [pageSize, setPageSize] = useState(25);
  const [offset, setOffset] = useState(0);

  // Reset paging whenever the user filter changes so we don't end up
  // looking at offset 200 of a freshly-narrowed result set.
  useEffect(() => {
    setOffset(0);
  }, [triggeredBy]);

  const { data, isLoading } = useQuery({
    queryKey: ["all-runs", pageSize, offset, triggeredBy],
    queryFn: () => getAllRuns(pageSize, offset, "active", triggeredBy),
    placeholderData: keepPreviousData,
  });

  // Enumerate users that have at least one active run for the dropdown.
  const { data: leaderboard } = useQuery({
    queryKey: ["users-leaderboard", "active"],
    queryFn: () => getUsersLeaderboard("active"),
    refetchInterval: 60_000,
  });
  const userOptions = leaderboard?.users ?? [];

  const runs = data?.runs ?? [];
  const total = data?.total ?? 0;

  function handleUserChange(value: string) {
    const next = new URLSearchParams(searchParams);
    if (value) {
      next.set("user", value);
    } else {
      next.delete("user");
    }
    setSearchParams(next, { replace: true });
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <h1 className="text-fg text-xl font-semibold mb-1 flex items-center gap-2">
        <History size={20} />
        Activity
      </h1>
      <p className="text-muted text-sm mb-4">{total} runs total</p>

      <div className="flex items-center gap-3 mb-6">
        <label
          htmlFor="activity-user-filter"
          className="flex items-center gap-1.5 text-muted text-xs"
        >
          <UserIcon size={13} />
          User
        </label>
        <select
          id="activity-user-filter"
          value={triggeredBy ?? ""}
          onChange={(e) => handleUserChange(e.target.value)}
          disabled={userOptions.length === 0 && !triggeredBy}
          className="bg-surface border border-border rounded-lg text-fg text-xs px-3 py-1.5 focus:outline-none focus:border-accent disabled:opacity-50 min-w-[10rem]"
        >
          <option value="">All users</option>
          {userOptions.map((u) => (
            <option key={u.username} value={u.username}>
              {u.username} ({u.count})
            </option>
          ))}
          {/* Keep a deep-linked user visible even if they have no active runs
              so the select doesn't silently snap back to "All". */}
          {triggeredBy &&
            !userOptions.some((u) => u.username === triggeredBy) && (
              <option value={triggeredBy}>{triggeredBy} (0)</option>
            )}
        </select>
      </div>

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
