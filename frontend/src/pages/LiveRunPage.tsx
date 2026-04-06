import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { XCircle } from "lucide-react";
import { cancelRun, getCurrentRun } from "../api/runs";
import { LogViewer } from "../components/LogViewer";
import { StatusBadge } from "../components/StatusBadge";

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

export function LiveRunPage() {
  const navigate = useNavigate();
  const [phase, setPhase] = useState("git");
  const [finalStatus, setFinalStatus] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);

  const { data: run, isLoading } = useQuery({
    queryKey: ["current-run"],
    queryFn: getCurrentRun,
    refetchInterval: finalStatus ? 2000 : false,
  });

  const elapsed = useElapsed(run?.started_at);

  // When finalStatus arrives and the polling confirms it's done, stop polling.
  const displayStatus = finalStatus ?? run?.status ?? "running";

  useEffect(() => {
    if (!isLoading && !run) {
      navigate("/trigger");
    }
  }, [run, isLoading, navigate]);

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
    <div className="p-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-white text-xl font-semibold">
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

      {/* Log viewer */}
      <LogViewer
        onPhaseChange={setPhase}
        onStatusChange={(s) => {
          setFinalStatus(s);
          setCancelling(false);
        }}
      />

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
            className="px-4 py-2 text-sm border border-border text-muted rounded-md hover:text-white transition"
          >
            Dashboard
          </button>
        </div>
      )}
    </div>
  );
}
