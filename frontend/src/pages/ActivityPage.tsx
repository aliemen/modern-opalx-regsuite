import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { Clock, Globe2, History, User as UserIcon } from "lucide-react";
import { getAllRuns, type RunIndexEntry } from "../api/results";
import { getUsersLeaderboard } from "../api/stats";
import { Pagination } from "../components/Pagination";
import { RunSummaryCard } from "../components/RunSummaryCard";

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

  const navigate = useNavigate();
  const [pageSize, setPageSize] = useState(25);
  const [offset, setOffset] = useState(0);
  const [copiedId, setCopiedId] = useState<string | null>(null);

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

  function copyPublicLink(run: RunIndexEntry) {
    const url = `${window.location.origin}/public/runs/${run.branch}/${run.arch}/${run.run_id}`;
    navigator.clipboard.writeText(url).then(() => {
      setCopiedId(run.run_id);
      setTimeout(() => setCopiedId(null), 2000);
    });
  }

  function handleUserChange(value: string) {
    setOffset(0);
    const next = new URLSearchParams(searchParams);
    if (value) {
      next.set("user", value);
    } else {
      next.delete("user");
    }
    setSearchParams(next, { replace: true });
  }

  return (
    <div className="p-4 sm:p-6 max-w-6xl mx-auto">
      <h1 className="text-fg text-xl font-semibold mb-1 flex items-center gap-2">
        <History size={20} />
        Activity
      </h1>
      <p className="text-muted text-sm mb-4">{total} runs total</p>

      <div className="flex flex-col items-stretch gap-2 mb-6 sm:flex-row sm:items-center sm:gap-3">
        <label
          htmlFor="activity-user-filter"
          className="flex items-center gap-1.5 text-muted text-xs shrink-0"
        >
          <UserIcon size={13} />
          User
        </label>
        <select
          id="activity-user-filter"
          value={triggeredBy ?? ""}
          onChange={(e) => handleUserChange(e.target.value)}
          disabled={userOptions.length === 0 && !triggeredBy}
          className="w-full bg-surface border border-border rounded-lg text-fg text-xs px-3 py-2 focus:outline-none focus:border-accent disabled:opacity-50 sm:w-auto sm:min-w-[10rem] sm:py-1.5"
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
          <div className="md:hidden space-y-3">
            {runs.map((run: RunIndexEntry) => (
              <RunSummaryCard
                key={`${run.branch}-${run.arch}-${run.run_id}`}
                run={run}
                to={`/results/${run.branch}/${run.arch}/${run.run_id}`}
                userLink={
                  run.triggered_by
                    ? `/activity?user=${encodeURIComponent(run.triggered_by)}`
                    : undefined
                }
                copiedPublicLink={copiedId === run.run_id}
                onCopyPublicLink={copyPublicLink}
              />
            ))}
          </div>

          <div className="hidden md:block border border-border rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-surface text-muted text-left">
                <tr>
                  <th className="px-4 py-3 font-medium w-36">OPALX Branch</th>
                  <th className="px-4 py-3 font-medium w-36">Tests Branch</th>
                  <th className="px-4 py-3 font-medium">Arch / Exec. On</th>
                  <th className="px-4 py-3 font-medium">User</th>
                  <th className="px-4 py-3 font-medium">
                    <Clock size={12} className="inline mr-1" />
                    Started
                  </th>
                  <th className="px-4 py-3 font-medium">Duration</th>
                  <th className="px-4 py-3 font-medium">Unit</th>
                  <th className="px-4 py-3 font-medium">Regression</th>
                  <th className="px-4 py-3 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run: RunIndexEntry, i: number) => (
                  <tr
                    key={`${run.branch}-${run.arch}-${run.run_id}`}
                    onClick={() => navigate(`/results/${run.branch}/${run.arch}/${run.run_id}`)}
                    className={`border-t border-border hover:bg-accent/10 transition-colors cursor-pointer ${
                      i % 2 === 0 ? "" : "bg-surface/30"
                    }`}
                  >
                    <td className="px-4 py-3 font-mono text-xs">{run.branch}</td>
                    <td className="px-4 py-3 font-mono text-xs">
                      {run.regtest_branch ?? "—"}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-muted">
                      {run.arch}{run.connection_name && run.connection_name !== "local"
                        ? ` / ${run.connection_name}`
                        : ""}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">
                      {run.triggered_by ? (
                        <Link
                          to={`/activity?user=${encodeURIComponent(run.triggered_by)}`}
                          onClick={(e) => e.stopPropagation()}
                          className="text-accent hover:underline"
                        >
                          {run.triggered_by}
                        </Link>
                      ) : (
                        <span className="text-muted">—</span>
                      )}
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
                    <td className="px-4 py-3">
                      {run.public && (
                        <button
                          type="button"
                          title={copiedId === run.run_id ? "Copied!" : "Copy public link"}
                          onClick={(e) => { e.stopPropagation(); copyPublicLink(run); }}
                          className="flex items-center gap-1 text-xs text-accent hover:brightness-125 transition-all"
                        >
                          <Globe2 size={13} />
                          {copiedId === run.run_id && (
                            <span className="text-passed">Copied!</span>
                          )}
                        </button>
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
