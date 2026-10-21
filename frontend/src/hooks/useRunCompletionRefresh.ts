import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { MachineStatus } from "../api/runs";
import { runKey } from "../lib/recentRuns";

/**
 * Refresh finished-run data as soon as a run leaves the active set, instead
 * of waiting for the next poll. Safe because the pipeline writes the runs
 * index before it releases the run slot, so the run is already listed by the
 * time it disappears from the queue state.
 */
export function useRunCompletionRefresh(machines: MachineStatus[] | undefined) {
  const qc = useQueryClient();
  const previous = useRef<Set<string> | null>(null);

  useEffect(() => {
    if (!machines) return;
    const active = new Set(
      machines.flatMap((m) => (m.active_run ? [runKey(m.active_run)] : []))
    );
    const prev = previous.current;
    previous.current = active;
    if (prev && [...prev].some((k) => !active.has(k))) {
      qc.invalidateQueries({ queryKey: ["all-runs"] });
      qc.invalidateQueries({ queryKey: ["branches"] });
      qc.invalidateQueries({ queryKey: ["dashboard-stats"] });
    }
  }, [machines, qc]);
}
