import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Download, XCircle } from "lucide-react";
import { cancelRun, getCurrentRun } from "../api/runs";
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
  startTime: number;       // Date.now() when START was seen
  durationMs: number | null; // set when END is seen
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

  // Tick every second while any test is actively running.
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

  return (
    <div className="flex flex-col h-[60vh]">
      <div className="flex items-center justify-between mb-2">
        <p className="text-xs font-medium text-muted uppercase tracking-wider">
          {inRegression ? "Regression Tests" : `Phase: ${phase || "…"}`}
        </p>
        {tests.length > 0 && (
          <p className="text-xs text-muted tabular-nums">
            <span className="text-passed">{passedCount}✓</span>
            {failedCount > 0 && <span className="text-failed ml-1.5">{failedCount}✗</span>}
            {brokenCount > 0 && <span className="text-broken ml-1.5">{brokenCount}?</span>}
            {runningCount > 0 && <span className="text-accent ml-1.5">{runningCount} running</span>}
          </p>
        )}
      </div>

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
            const elapsed =
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
              <div key={test.name} className="flex items-center gap-2 text-xs py-0.5">
                <span className={`w-2 h-2 rounded-full flex-shrink-0 ${dotColor}`} />
                <span
                  className={`flex-1 truncate font-mono ${
                    test.status === "running" ? "text-accent" : "text-fg"
                  }`}
                >
                  {test.name}
                </span>
                <span className="text-muted tabular-nums ml-auto">{elapsed}</span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export function LiveRunPage() {
  const navigate = useNavigate();
  const [phase, setPhase] = useState("git");
  const [finalStatus, setFinalStatus] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [tests, setTests] = useState<TestInfo[]>([]);
  const restoredRef = useRef(false);

  const { data: run, isLoading } = useQuery({
    queryKey: ["current-run"],
    queryFn: getCurrentRun,
    refetchInterval: finalStatus ? 2000 : false,
  });

  const elapsed = useElapsed(run?.started_at);
  const displayStatus = finalStatus ?? run?.status ?? "running";

  useEffect(() => {
    if (!isLoading && !run) {
      navigate("/trigger");
    }
  }, [run, isLoading, navigate]);

  // Restore test list from sessionStorage once run_id is known (survives navigation).
  useEffect(() => {
    if (!run?.run_id || restoredRef.current) return;
    restoredRef.current = true;
    try {
      const saved = sessionStorage.getItem("live-tests");
      if (saved) {
        const parsed = JSON.parse(saved);
        if (parsed.runId === run.run_id && Array.isArray(parsed.tests)) {
          setTests(parsed.tests);
        }
      }
    } catch { /* ignore */ }
  }, [run?.run_id]);

  // Persist test list to sessionStorage whenever it changes.
  useEffect(() => {
    if (!run?.run_id) return;
    sessionStorage.setItem("live-tests", JSON.stringify({ runId: run.run_id, tests }));
  }, [tests, run?.run_id]);

  // Parse regression test START/END lines from the log stream.
  const handleLogLine = useCallback((line: string) => {
    const startMatch = line.match(/\[regression\] START (\S+)/);
    if (startMatch) {
      const name = startMatch[1];
      setTests((prev) => {
        // Avoid duplicates on SSE reconnect.
        if (prev.some((t) => t.name === name)) return prev;
        return [...prev, { name, status: "running", startTime: Date.now(), durationMs: null }];
      });
      return;
    }
    const endMatch = line.match(/\[regression\] END (\S+) state=(\S+)/);
    if (endMatch) {
      const name = endMatch[1];
      const state = endMatch[2] as TestStatus;
      setTests((prev) =>
        prev.map((t) =>
          t.name === name
            ? { ...t, status: state, durationMs: Date.now() - t.startTime }
            : t
        )
      );
    }
  }, []);

  async function handleCancel() {
    setCancelling(true);
    try {
      await cancelRun();
    } catch {
      setCancelling(false);
    }
  }

  if (isLoading || !run) {
    return <div className="p-8 text-muted">Loading…</div>;
  }

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-fg text-xl font-semibold">
            {run.branch} / {run.arch}
          </h1>
          <p className="text-muted text-sm">
            {run.run_id} · phase: <span className="text-accent">{phase}</span> · {elapsed}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge status={displayStatus} size="md" />
          {displayStatus === "running" && (
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
        {/* Log viewer — 3/5 width */}
        <div className="lg:col-span-3">
          <LogViewer
            onPhaseChange={setPhase}
            onStatusChange={(s) => {
              setFinalStatus(s);
              setCancelling(false);
            }}
            onLogLine={handleLogLine}
          />
          <a
            href={`/data/runs/${run.branch}/${run.arch}/${run.run_id}/logs/pipeline.log`}
            target="_blank"
            rel="noopener"
            className="flex items-center gap-1.5 text-muted hover:text-fg text-xs mt-1 w-fit transition-colors"
          >
            <Download size={12} /> Download full log
          </a>
        </div>

        {/* Test tracker — 2/5 width */}
        <div className="lg:col-span-2">
          <TestTrackerPanel tests={tests} phase={phase} finalStatus={finalStatus} />
        </div>
      </div>

      {/* Post-run actions */}
      {finalStatus && finalStatus !== "running" && (
        <div className="mt-4 flex gap-3">
          <button
            onClick={() =>
              navigate(`/results/${run.branch}/${run.arch}/${run.run_id}`)
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
