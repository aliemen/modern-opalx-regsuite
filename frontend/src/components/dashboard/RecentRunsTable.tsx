import type { MouseEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { History, X } from "lucide-react";
import { getAllRuns } from "../../api/results";
import { cancelQueuedRun, type MachineStatus } from "../../api/runs";
import { getCurrentUser } from "../../api/user";
import { useRecentScope, type RecentScope } from "../../hooks/useRecentScope";
import { resultsPath } from "../../lib/paths";
import { mergeRecentRuns, type RecentRow } from "../../lib/recentRuns";
import { formatSeconds, relativeTime, secondsBetween } from "../../lib/time";
import { Elapsed } from "../Elapsed";
import { SkippedChip } from "../SkippedChip";
import { StatusBadge } from "../StatusBadge";

/** Finished runs shown below the live (running / queued) rows. */
export const RECENT_FINISHED_LIMIT = 6;

interface RecentRunsTableProps {
  /** Queue state, polled by the page. Undefined while loading. */
  machines: MachineStatus[] | undefined;
  /** Duration in seconds of the last finished run per `branch::arch`. */
  lastDurations: Map<string, number>;
}

interface RowView {
  status: string;
  branch: string;
  build: string;
  regtestBranch: string | null;
  user: string | null;
  startedAt: string;
  /** Navigation target, with router state for the live page. */
  to: string | null;
  state?: { branch: string; arch: string };
}

function view(row: RecentRow): RowView {
  switch (row.kind) {
    case "running":
      return {
        status: "running",
        branch: row.run.branch,
        build: row.run.build_name ?? row.run.arch,
        regtestBranch: null,
        user: row.run.triggered_by ?? null,
        startedAt: row.run.started_at,
        to: `/live/${encodeURIComponent(row.run.run_id)}`,
        state: { branch: row.run.branch, arch: row.run.arch },
      };
    case "queued":
      return {
        status: "queued",
        branch: row.item.branch,
        build: row.item.build_name ?? row.item.arch,
        regtestBranch: null,
        user: row.item.triggered_by ?? null,
        startedAt: row.item.queued_at,
        to: null,
      };
    case "finished":
      return {
        status: row.run.status,
        branch: row.run.branch,
        build: row.run.execution_snapshot?.build?.name ?? row.run.arch,
        regtestBranch: row.run.regtest_branch,
        user: row.run.triggered_by,
        startedAt: row.run.started_at,
        to: resultsPath(row.run.branch, row.run.arch, row.run.run_id),
      };
  }
}

function ScopeToggle({
  value,
  onChange,
}: {
  value: RecentScope;
  onChange: (next: RecentScope) => void;
}) {
  const options: { value: RecentScope; label: string }[] = [
    { value: "all", label: "Everyone" },
    { value: "mine", label: "Mine" },
  ];
  return (
    <div className="inline-flex border border-border rounded-lg overflow-hidden bg-surface">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          aria-pressed={value === opt.value}
          onClick={() => onChange(opt.value)}
          className={`px-3 py-1 text-xs transition-colors ${
            value === opt.value
              ? "bg-accent/15 text-accent"
              : "text-muted hover:text-fg hover:bg-border/30"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function Counts({ row }: { row: Extract<RecentRow, { kind: "finished" }> }) {
  const r = row.run;
  return (
    <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1 tabular-nums">
      <span>
        <span className="text-muted">U</span>{" "}
        {r.unit_tests_total > 0
          ? `${r.unit_tests_total - r.unit_tests_failed}/${r.unit_tests_total}`
          : "—"}
      </span>
      <span>
        <span className="text-muted">R</span>{" "}
        {r.regression_total > 0 ? (
          <>
            {r.regression_passed}/{r.regression_total}
            {r.regression_failed > 0 && (
              <span className="text-failed ml-1">{r.regression_failed} fail</span>
            )}
            {r.regression_broken > 0 && (
              <span className="text-broken ml-1">{r.regression_broken} broken</span>
            )}
          </>
        ) : (
          "—"
        )}
      </span>
      <SkippedChip unit={r.unit_tests_skipped} regression={r.regression_skipped} />
    </span>
  );
}

/**
 * Dashboard landing table: everything running or queued right now, then the
 * newest finished runs, one row each, so the run someone just started is
 * one click away. "Mine" narrows both parts to the signed-in user.
 */
export function RecentRunsTable({ machines, lastDurations }: RecentRunsTableProps) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [scope, setScope] = useRecentScope();

  const { data: me } = useQuery({ queryKey: ["auth-me"], queryFn: getCurrentUser });
  const username = me?.username ?? null;
  const userFilter = scope === "mine" ? username : null;
  const waitingForUser = scope === "mine" && username === null;

  const finishedQuery = useQuery({
    queryKey: ["all-runs", "recent", userFilter],
    queryFn: () => getAllRuns(RECENT_FINISHED_LIMIT, 0, "active", userFilter),
    enabled: !waitingForUser,
    // Completed runs normally arrive through useRunCompletionRefresh; this is
    // only a fallback for runs started and finished between two queue polls.
    refetchInterval: 60_000,
  });

  const cancel = useMutation({
    mutationFn: cancelQueuedRun,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["queue-state"] }),
  });

  const loading = waitingForUser || machines === undefined || finishedQuery.isLoading;
  const rows = loading
    ? []
    : mergeRecentRuns(machines, finishedQuery.data?.runs ?? [], userFilter);

  const activityHref =
    scope === "mine" && username
      ? `/activity?user=${encodeURIComponent(username)}`
      : "/activity";

  function onRowClick(e: MouseEvent, v: RowView) {
    // Links and buttons inside the row handle their own clicks.
    if ((e.target as HTMLElement).closest("a, button")) return;
    if (v.to) navigate(v.to, { state: v.state });
  }

  function durationCell(row: RecentRow) {
    if (row.kind === "finished") {
      const secs = secondsBetween(row.run.started_at, row.run.finished_at);
      return secs === null ? "—" : formatSeconds(secs);
    }
    if (row.kind === "running") {
      const last = lastDurations.get(`${row.run.branch}::${row.run.arch}`);
      return (
        <>
          <span className="text-fg">
            <Elapsed since={row.run.started_at} />
          </span>
          {last !== undefined && (
            <span className="text-muted/70 ml-1" title="Duration of the previous run of this branch and build">
              (last {formatSeconds(last)})
            </span>
          )}
        </>
      );
    }
    return "—";
  }

  function resultCell(row: RecentRow) {
    if (row.kind === "finished") return <Counts row={row} />;
    if (row.kind === "running") {
      return (
        <span className="inline-flex items-center gap-1.5">
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-accent/15 text-accent font-medium">
            {row.run.phase}
          </span>
          <span className="text-muted">on {row.machineLabel}</span>
        </span>
      );
    }
    return (
      <span className="text-muted">
        #{row.position} on {row.machineLabel}
      </span>
    );
  }

  function actionCell(row: RecentRow) {
    if (row.kind !== "queued" || !username || row.item.triggered_by !== username) {
      return null;
    }
    return (
      <button
        type="button"
        onClick={() => cancel.mutate(row.item.queue_id)}
        disabled={cancel.isPending}
        className="text-muted hover:text-failed transition-colors p-1 disabled:opacity-50"
        title="Remove from queue"
        aria-label={`Remove ${row.item.branch} / ${row.item.arch} from queue`}
      >
        <X size={13} />
      </button>
    );
  }

  function branchLabel(v: RowView) {
    return (
      <>
        <span className="text-fg truncate" title={v.branch}>
          {v.branch}
        </span>{" "}
        <span className="text-muted shrink-0">&middot;</span>{" "}
        <span className="text-muted truncate" title={v.build}>
          {v.build}
        </span>
      </>
    );
  }

  function userCell(v: RowView) {
    return v.user ? (
      <Link
        to={`/activity?user=${encodeURIComponent(v.user)}`}
        className="text-accent hover:underline"
      >
        {v.user}
      </Link>
    ) : (
      <span className="text-muted">&mdash;</span>
    );
  }

  return (
    <section className="bg-surface border border-border rounded-xl mb-6 overflow-hidden">
      <header className="flex flex-wrap items-center gap-3 px-4 py-3 sm:px-5 border-b border-border">
        <h2 className="text-fg font-medium text-sm flex items-center gap-2">
          <History size={15} className="text-muted" />
          Recent runs
        </h2>
        <ScopeToggle value={scope} onChange={setScope} />
        <Link to={activityHref} className="ml-auto text-xs text-accent hover:underline">
          View all in Activity &rarr;
        </Link>
      </header>

      {loading ? (
        <p className="text-muted text-xs px-5 py-6">Loading&hellip;</p>
      ) : rows.length === 0 ? (
        <p className="text-muted text-sm px-5 py-6">
          {scope === "mine" ? "You haven't started any runs yet. " : "No runs yet. "}
          <Link to="/trigger" className="text-accent hover:underline">
            Start a run
          </Link>
        </p>
      ) : (
        <>
          <table className="hidden md:table w-full text-xs">
            <thead className="text-muted text-left">
              <tr>
                <th className="px-4 py-2 font-medium w-24">Status</th>
                <th className="px-4 py-2 font-medium">Branch &middot; build</th>
                <th className="px-4 py-2 font-medium">User</th>
                <th className="px-4 py-2 font-medium">Started</th>
                <th className="px-4 py-2 font-medium">Duration</th>
                <th className="px-4 py-2 font-medium">Result</th>
                <th className="px-2 py-2 w-8">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const v = view(row);
                return (
                  <tr
                    key={row.key}
                    onClick={(e) => onRowClick(e, v)}
                    className={`border-t border-border transition-colors ${
                      v.to ? "hover:bg-accent/10 cursor-pointer" : ""
                    }`}
                  >
                    <td className="px-4 py-2">
                      <StatusBadge status={v.status} />
                    </td>
                    <td className="px-4 py-2 font-mono max-w-0 w-[40%]">
                      {v.to ? (
                        <Link
                          to={v.to}
                          state={v.state}
                          className="flex items-center gap-1.5 min-w-0 hover:underline"
                        >
                          {branchLabel(v)}
                        </Link>
                      ) : (
                        <span className="flex items-center gap-1.5 min-w-0">{branchLabel(v)}</span>
                      )}
                      {v.regtestBranch && v.regtestBranch !== "master" && (
                        <span className="block text-muted/80 truncate" title={`Tests branch: ${v.regtestBranch}`}>
                          tests: {v.regtestBranch}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2 font-mono">{userCell(v)}</td>
                    <td
                      className="px-4 py-2 text-muted whitespace-nowrap"
                      title={new Date(v.startedAt).toLocaleString()}
                    >
                      {row.kind === "queued" ? "queued " : ""}
                      {relativeTime(v.startedAt)}
                    </td>
                    <td className="px-4 py-2 text-muted whitespace-nowrap tabular-nums">
                      {durationCell(row)}
                    </td>
                    <td className="px-4 py-2">{resultCell(row)}</td>
                    <td className="px-2 py-2 text-right">{actionCell(row)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          <ul className="md:hidden divide-y divide-border">
            {rows.map((row) => {
              const v = view(row);
              const body = (
                <>
                  <div className="flex items-center gap-2 min-w-0">
                    <StatusBadge status={v.status} />
                    <span className="flex items-center gap-1.5 min-w-0 font-mono text-xs">
                      {branchLabel(v)}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                    <span>{v.user ?? "—"}</span>
                    <span>{relativeTime(v.startedAt)}</span>
                    <span className="tabular-nums">{durationCell(row)}</span>
                    <span className="text-fg">{resultCell(row)}</span>
                  </div>
                </>
              );
              return (
                <li key={row.key} className="flex items-start gap-2 px-4 py-3">
                  {v.to ? (
                    <Link to={v.to} state={v.state} className="block min-w-0 flex-1">
                      {body}
                    </Link>
                  ) : (
                    <div className="min-w-0 flex-1">{body}</div>
                  )}
                  {actionCell(row)}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}
