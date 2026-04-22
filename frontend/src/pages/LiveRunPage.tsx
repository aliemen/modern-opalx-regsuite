import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Download, XCircle } from "lucide-react";
import {
  cancelRunById,
  getQueueState,
  type CurrentRunStatus,
} from "../api/runs";
import { LogViewer } from "../components/LogViewer";
import { StatusBadge } from "../components/StatusBadge";

// ── Elapsed timer ────────────────────────────────────────────────────────────

function useElapsed(startedAt: string | undefined) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!startedAt) return;
    const t = setInterval(() => {
      setElapsed(Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000));
    }, 1000);
    return () => clearInterval(t);
  }, [startedAt]);
  const m = Math.floor(elapsed / 60);
  const s = elapsed % 60;
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

// ── Test tracker ─────────────────────────────────────────────────────────────

type TestStatus = "running" | "passed" | "failed" | "broken" | "cancelled";

interface TestInfo {
  name: string;
  status: TestStatus;
  startTime: number;
  durationMs: number | null;
}

function fmtMs(ms: number): string {
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${(s % 60).toString().padStart(2, "0")}s`;
}

function TestTrackerPanel({
  tests,
  phase,
  finalStatus,
}: {
  tests: TestInfo[];
  phase: string;
  finalStatus: string | null;
}) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (tests.some((t) => t.status === "running")) {
      const timer = setInterval(() => setNow(Date.now()), 1000);
      return () => clearInterval(timer);
    }
  }, [tests]);

  const inRegression = phase === "regression" || tests.length > 0;
  const passedCount = tests.filter((t) => t.status === "passed").length;
  const failedCount = tests.filter((t) => t.status === "failed").length;
  const brokenCount = tests.filter((t) => t.status === "broken").length;
  const runningCount = tests.filter((t) => t.status === "running").length;
  const totalCount = tests.length;

  return (
    <div className="flex flex-col h-[60vh]">
      <div className="flex items-center justify-between mb-2">
        <p className="text-xs font-medium text-muted uppercase tracking-wider">
          {inRegression ? "Regression Tests" : `Phase: ${phase || "…"}`}
        </p>
        {tests.length > 0 && (
          <p className="text-xs text-muted tabular-nums">
            <span className="text-passed">{passedCount}&#x2713;</span>
            {failedCount > 0 && (
              <span className="text-failed ml-1.5">{failedCount}&#x2717;</span>
            )}
            {brokenCount > 0 && (
              <span className="text-broken ml-1.5">{brokenCount}?</span>
            )}
            {runningCount > 0 && (
              <span className="text-accent ml-1.5">{runningCount} running</span>
            )}
          </p>
        )}
      </div>

      {finalStatus && finalStatus !== "running" && tests.length > 0 && (
        <div
          className={`flex items-center justify-between text-xs px-3 py-2 rounded-md mb-2 border ${
            failedCount > 0 || brokenCount > 0
              ? "bg-failed/10 border-failed/30 text-failed"
              : "bg-passed/10 border-passed/30 text-passed"
          }`}
        >
          <span className="font-medium">
            {passedCount}/{totalCount} passed
          </span>
          <span className="text-muted tabular-nums">
            {failedCount > 0 && `${failedCount} failed`}
            {failedCount > 0 && brokenCount > 0 && " · "}
            {brokenCount > 0 && `${brokenCount} broken`}
            {failedCount === 0 && brokenCount === 0 && "all passed"}
          </span>
        </div>
      )}

      <div className="flex-1 overflow-y-auto bg-surface border border-border rounded-md px-3 py-3 space-y-1">
        {tests.length === 0 ? (
          <p className="text-muted text-xs">
            {finalStatus
              ? "No regression tests ran."
              : inRegression
              ? "Waiting for first test…"
              : "Tests will appear when the regression phase starts."}
          </p>
        ) : (
          tests.map((test) => {
            const el =
              test.status === "running"
                ? fmtMs(now - test.startTime)
                : test.durationMs != null
                ? fmtMs(test.durationMs)
                : "—";

            const dotColor =
              test.status === "running"
                ? "bg-accent animate-pulse"
                : test.status === "passed"
                ? "bg-passed"
                : test.status === "failed"
                ? "bg-failed"
                : test.status === "broken"
                ? "bg-broken"
                : test.status === "cancelled"
                ? "bg-cancelled"
                : "bg-muted";

            return (
              <div
                key={test.name}
                className="flex items-center gap-2 text-xs py-0.5"
              >
                <span
                  className={`w-2 h-2 rounded-full flex-shrink-0 ${dotColor}`}
                />
                <span
                  className={`flex-1 truncate font-mono ${
                    test.status === "running" ? "text-accent" : "text-fg"
                  }`}
                >
                  {test.name}
                </span>
                <span className="text-muted tabular-nums ml-auto">{el}</span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

// ── Per-run session storage ─────────────────────────────────────────────────

interface StoredLiveState {
  runId: string;
  tests: TestInfo[];
  phase: string;
  finalStatus: string | null;
  cancelling?: boolean;
  // Cached from the first `effectiveRun` seen so the "View results" /
  // "Dashboard" buttons remain visible after the backend removes the run
  // from its active-runs list (which would otherwise clear `effectiveRun`
  // and hide the buttons a split second after they appear).
  branch?: string;
  arch?: string;
}

function liveStateKey(runId: string): string {
  return `live-run-state-${runId}`;
}

function loadLiveState(runId: string | undefined): StoredLiveState | null {
  if (!runId) return null;
  try {
    const raw = sessionStorage.getItem(liveStateKey(runId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredLiveState;
    return parsed.runId === runId ? parsed : null;
  } catch {
    return null;
  }
}

function saveLiveState(state: StoredLiveState): void {
  try {
    sessionStorage.setItem(liveStateKey(state.runId), JSON.stringify(state));
  } catch {
    // sessionStorage might be full; non-critical.
  }
}

// ── Run switcher ────────────────────────────────────────────────────────────

function RunSwitcher({
  activeRuns,
  currentRunId,
}: {
  activeRuns: CurrentRunStatus[];
  currentRunId: string | undefined;
}) {
  const navigate = useNavigate();

  if (activeRuns.length <= 1) return null;

  return (
    <div className="flex items-center gap-2 mb-4 overflow-x-auto pb-1">
      {activeRuns.map((r) => {
        const isActive = r.run_id === currentRunId;
        return (
          <button
            key={r.run_id}
            onClick={() => navigate(`/live/${r.run_id}`, { replace: true })}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors ${
              isActive
                ? "bg-accent/15 text-accent border border-accent/30"
                : "bg-surface border border-border text-muted hover:text-fg hover:border-accent/30"
            }`}
          >
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                isActive ? "bg-accent animate-pulse" : "bg-muted"
              }`}
            />
            {r.branch}/{r.arch}
          </button>
        );
      })}
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export function LiveRunPage() {
  const navigate = useNavigate();
  const { runId: routeRunId } = useParams<{ runId?: string }>();

  // Always fetch queue state to know about all active runs.
  const { data: queueState } = useQuery({
    queryKey: ["queue-state"],
    queryFn: getQueueState,
    refetchInterval: 3000,
  });

  // Extract all active runs from queue state.
  const allActiveRuns = useMemo(
    () =>
      (queueState?.machines ?? []).flatMap((m) =>
        m.active_run ? [m.active_run] : []
      ),
    [queueState]
  );

  // Determine the effective run: use route param, or fall back to first active.
  const effectiveRun = useMemo(() => {
    if (routeRunId) {
      return allActiveRuns.find((r) => r.run_id === routeRunId) ?? null;
    }
    return allActiveRuns[0] ?? null;
  }, [routeRunId, allActiveRuns]);

  const runId = effectiveRun?.run_id ?? routeRunId;

  // Load persisted state for this specific run.
  const [initSnap] = useState(() => loadLiveState(runId));

  const [phase, setPhase] = useState(initSnap?.phase ?? "git");
  const [finalStatus, setFinalStatus] = useState<string | null>(
    initSnap?.finalStatus ?? null
  );
  const [cancelling, setCancelling] = useState(initSnap?.cancelling ?? false);
  const [tests, setTests] = useState<TestInfo[]>(initSnap?.tests ?? []);
  // Cached branch/arch from the first effectiveRun so post-run action buttons
  // stay visible after the backend drops the run from active-runs.
  const [cachedBranch, setCachedBranch] = useState<string | undefined>(
    initSnap?.branch
  );
  const [cachedArch, setCachedArch] = useState<string | undefined>(initSnap?.arch);

  const elapsed = useElapsed(effectiveRun?.started_at || undefined);
  const displayStatus = finalStatus ?? effectiveRun?.status ?? "running";

  // When runId changes (switching runs), reset local state and load the
  // persisted state for the new run.
  useEffect(() => {
    if (!runId) return;
    const snap = loadLiveState(runId);
    setTests(snap?.tests ?? []);
    setPhase(snap?.phase ?? "git");
    setFinalStatus(snap?.finalStatus ?? null);
    setCancelling(snap?.cancelling ?? false);
    setCachedBranch(snap?.branch);
    setCachedArch(snap?.arch);
  }, [runId]);

  // Cache branch/arch the moment we see the live run, so the post-run action
  // buttons can keep rendering after `effectiveRun` becomes null.
  useEffect(() => {
    if (effectiveRun?.branch) setCachedBranch(effectiveRun.branch);
    if (effectiveRun?.arch) setCachedArch(effectiveRun.arch);
  }, [effectiveRun?.branch, effectiveRun?.arch]);

  // Redirect to trigger page if nothing to show.
  useEffect(() => {
    if (!routeRunId && allActiveRuns.length === 0 && queueState) {
      navigate("/trigger");
    }
  }, [allActiveRuns.length, queueState, navigate, routeRunId]);

  // Auto-redirect to the first active run if visiting /live with no runId.
  useEffect(() => {
    if (!routeRunId && allActiveRuns.length > 0) {
      navigate(`/live/${allActiveRuns[0].run_id}`, { replace: true });
    }
  }, [routeRunId, allActiveRuns, navigate]);

  // Persist live-view state to per-run session storage on every change.
  useEffect(() => {
    if (!runId) return;
    saveLiveState({
      runId,
      tests,
      phase,
      finalStatus,
      cancelling,
      branch: cachedBranch,
      arch: cachedArch,
    });
  }, [tests, phase, finalStatus, cancelling, runId, cachedBranch, cachedArch]);

  // Parse regression test START/END lines from the log stream.
  const handleLogLine = useCallback(
    (line: string) => {
      const startMatch = line.match(/\[regression\] START (\S+)/);
      if (startMatch) {
        const name = startMatch[1];
        setTests((prev) => {
          if (prev.some((t) => t.name === name)) return prev;
          return [
            ...prev,
            { name, status: "running", startTime: Date.now(), durationMs: null },
          ];
        });
        return;
      }
      const endMatch = line.match(/\[regression\] END (\S+) state=(\S+)/);
      if (endMatch) {
        const name = endMatch[1];
        const state = endMatch[2] as TestStatus;
        // Backend now embeds duration_ms=... in the END line so late-arriving
        // subscribers can still show the correct elapsed time. Fall back to
        // the local Date.now() diff only if the field is missing (older runs).
        const durationMatch = line.match(/\bduration_ms=(\d+)\b/);
        const authoritativeMs = durationMatch
          ? parseInt(durationMatch[1], 10)
          : null;
        setTests((prev) => {
          const existing = prev.find((t) => t.name === name);
          if (!existing) {
            // Late subscriber: START scrolled off before we connected.
            // Synthesize a row so the user sees it as a completed entry.
            return [
              ...prev,
              {
                name,
                status: state,
                startTime: Date.now(),
                durationMs: authoritativeMs,
              },
            ];
          }
          return prev.map((t) =>
            t.name === name && t.status === "running"
              ? {
                  ...t,
                  status: state,
                  durationMs:
                    authoritativeMs !== null
                      ? authoritativeMs
                      : Date.now() - t.startTime,
                }
              : t
          );
        });
      }
    },
    []
  );

  async function handleCancel() {
    if (!runId) return;
    setCancelling(true);
    try {
      await cancelRunById(runId);
    } catch {
      setCancelling(false);
    }
  }

  if (!queueState) {
    return <div className="p-8 text-muted">Loading…</div>;
  }
  if (!runId) {
    return <div className="p-8 text-muted">No active run.</div>;
  }

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Run switcher tabs */}
      <RunSwitcher activeRuns={allActiveRuns} currentRunId={runId} />

      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-fg text-xl font-semibold">
            {effectiveRun?.branch ?? "…"} / {effectiveRun?.arch ?? "…"}
          </h1>
          <p className="text-muted text-sm">
            {runId} · phase: <span className="text-accent">{phase}</span> ·{" "}
            {elapsed}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge status={displayStatus} size="md" />
          {(displayStatus === "running" || cancelling) && !finalStatus && (
            <button
              onClick={handleCancel}
              disabled={cancelling}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-failed border border-failed/40 rounded-md hover:bg-failed/10 transition disabled:opacity-50"
            >
              <XCircle size={15} />
              {cancelling ? "Cancelling…" : "Cancel"}
            </button>
          )}
        </div>
      </div>

      {/* Two-column layout: log viewer + test tracker */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        <div className="lg:col-span-3">
          <LogViewer
            runId={runId}
            onPhaseChange={setPhase}
            onStatusChange={(s) => {
              setFinalStatus(s);
              setCancelling(false);
            }}
            onLogLine={handleLogLine}
          />
          {effectiveRun?.branch && (
            <a
              href={`/data/runs/${effectiveRun.branch}/${effectiveRun.arch}/${effectiveRun.run_id}/logs/pipeline.log`}
              target="_blank"
              rel="noopener"
              className="flex items-center gap-1.5 text-muted hover:text-fg text-xs mt-1 w-fit transition-colors"
            >
              <Download size={12} /> Download full log
            </a>
          )}
        </div>

        <div className="lg:col-span-2">
          <TestTrackerPanel
            tests={tests}
            phase={phase}
            finalStatus={finalStatus}
          />
        </div>
      </div>

      {/* Post-run actions */}
      {finalStatus && finalStatus !== "running" && runId && (effectiveRun?.branch ?? cachedBranch) && (effectiveRun?.arch ?? cachedArch) && (
        <div className="mt-4 flex gap-3">
          <button
            onClick={() =>
              navigate(
                `/results/${effectiveRun?.branch ?? cachedBranch}/${effectiveRun?.arch ?? cachedArch}/${runId}`
              )
            }
            className="px-4 py-2 text-sm bg-accent text-bg font-medium rounded-md hover:brightness-110 transition"
          >
            View results
          </button>
          <button
            onClick={() => navigate("/")}
            className="px-4 py-2 text-sm border border-border text-muted rounded-md hover:text-fg transition"
          >
            Dashboard
          </button>
        </div>
      )}
    </div>
  );
}
