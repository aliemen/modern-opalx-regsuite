import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Layers, Monitor, Server, X } from "lucide-react";
import {
  getQueueState,
  cancelQueuedRun,
  type MachineStatus,
} from "../api/runs";

function elapsed(startedAt: string): string {
  const diff = Date.now() - new Date(startedAt).getTime();
  const s = Math.floor(diff / 1000);
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  if (h > 0) return `${h}h ${(m % 60).toString().padStart(2, "0")}m`;
  if (m > 0) return `${m}m ${(s % 60).toString().padStart(2, "0")}s`;
  return `${s}s`;
}

function PhaseBadge({ phase }: { phase: string }) {
  return (
    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-accent/15 text-accent font-medium">
      {phase}
    </span>
  );
}

function MachineSection({ machine }: { machine: MachineStatus }) {
  const queryClient = useQueryClient();
  const isLocal = machine.machine_id === "local";

  const cancelMutation = useMutation({
    mutationFn: cancelQueuedRun,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["queue-state"] }),
  });

  // Auto-refresh elapsed time.
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!machine.active_run) return;
    const interval = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(interval);
  }, [machine.active_run]);

  return (
    <div className="space-y-1.5">
      {/* Machine header */}
      <div className="flex items-center gap-2 text-xs text-muted">
        {isLocal ? <Monitor size={12} /> : <Server size={12} />}
        <span className="font-medium text-fg">
          {isLocal ? "Local" : machine.machine_id}
        </span>
      </div>

      {/* Active run */}
      {machine.active_run && (
        <Link
          to={`/live/${machine.active_run.run_id}`}
          className="flex items-center gap-2 pl-5 py-1 text-xs hover:bg-border/30 rounded transition-colors min-w-0"
        >
          <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
          <span className="text-fg truncate min-w-0" title={`${machine.active_run.branch}/${machine.active_run.arch}`}>
            {machine.active_run.branch}/{machine.active_run.arch}
          </span>
          <PhaseBadge phase={machine.active_run.phase} />
          <span className="text-muted ml-auto tabular-nums">
            {elapsed(machine.active_run.started_at)}
          </span>
        </Link>
      )}

      {/* Queued runs */}
      {machine.queue.map((qr, i) => (
        <div
          key={qr.queue_id}
          className="flex items-center gap-2 pl-5 py-1 text-xs min-w-0"
        >
          <span className="text-muted w-3 text-right tabular-nums">
            {i + 1}.
          </span>
          <span className="text-fg truncate min-w-0" title={`${qr.branch}/${qr.arch}`}>
            {qr.branch}/{qr.arch}
          </span>
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-border text-muted font-medium">
            queued
          </span>
          <button
            onClick={() => cancelMutation.mutate(qr.queue_id)}
            disabled={cancelMutation.isPending}
            className="ml-auto text-muted hover:text-failed transition-colors p-0.5"
            title="Remove from queue"
          >
            <X size={12} />
          </button>
        </div>
      ))}
    </div>
  );
}

export function QueuePanel() {
  const { data } = useQuery({
    queryKey: ["queue-state"],
    queryFn: getQueueState,
    refetchInterval: 3000,
  });

  const machines = data?.machines ?? [];
  const hasActivity = machines.length > 0;

  return (
    <div className="bg-surface border border-border rounded-xl p-5">
      <h2 className="text-fg font-medium text-sm flex items-center gap-2 mb-3">
        <Layers size={15} />
        Running Jobs & Queue
      </h2>

      {!hasActivity ? (
        <p className="text-muted text-xs py-3 text-center">
          No active or queued runs.
        </p>
      ) : (
        <div className="space-y-3">
          {machines.map((m) => (
            <MachineSection key={m.machine_id} machine={m} />
          ))}
        </div>
      )}
    </div>
  );
}
