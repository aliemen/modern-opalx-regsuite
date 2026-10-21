import { describe, expect, it } from "vitest";
import type { RunIndexEntry } from "../api/results";
import type { MachineStatus } from "../api/runs";
import { mergeRecentRuns } from "./recentRuns";

function finished(run_id: string, extra: Partial<RunIndexEntry> = {}): RunIndexEntry {
  return {
    run_id,
    branch: "master",
    arch: "cpu-serial",
    started_at: "2026-10-20T10:00:00Z",
    finished_at: "2026-10-20T10:30:00Z",
    status: "passed",
    triggered_by: "alice",
    regtest_branch: "master",
    connection_name: null,
    unit_tests_total: 1,
    unit_tests_failed: 0,
    regression_total: 1,
    regression_passed: 1,
    regression_failed: 0,
    regression_broken: 0,
    archived: false,
    public: false,
    run_options: {} as RunIndexEntry["run_options"],
    rerun_of: null,
    ...extra,
  };
}

const machines: MachineStatus[] = [
  {
    machine_id: "local",
    active_run: {
      run_id: "r-old",
      branch: "master",
      arch: "cpu-serial",
      status: "running",
      phase: "build",
      started_at: "2026-10-21T09:00:00Z",
      machine_id: "local",
      triggered_by: "alice",
    },
    queue: [
      { queue_id: "q2", run_id: "q-b", branch: "fix/x", arch: "cpu-serial", queued_at: "2026-10-21T09:20:00Z", triggered_by: "bob" },
    ],
  },
  {
    machine_id: "daint.cscs.ch",
    active_run: {
      run_id: "r-new",
      branch: "fix/x",
      arch: "cuda-daint",
      status: "running",
      phase: "unit",
      started_at: "2026-10-21T09:10:00Z",
      machine_id: "daint.cscs.ch",
      triggered_by: "bob",
      machine_name: "Daint",
    },
    queue: [
      { queue_id: "q1", run_id: "q-a", branch: "master", arch: "cuda-daint", queued_at: "2026-10-21T09:15:00Z", triggered_by: "alice" },
      { queue_id: "q3", run_id: "q-c", branch: "master", arch: "cuda-daint", queued_at: "2026-10-21T09:25:00Z", triggered_by: "alice" },
    ],
  },
];

describe("mergeRecentRuns", () => {
  it("orders running, then queued, then finished", () => {
    const rows = mergeRecentRuns(machines, [finished("f1")], null);
    expect(rows.map((r) => `${r.kind}:${r.key.split("::")[2]}`)).toEqual([
      "running:r-new",
      "running:r-old",
      "queued:q-a",
      "queued:q-b",
      "queued:q-c",
      "finished:f1",
    ]);
    const qc = rows.find((r) => r.kind === "queued" && r.item.run_id === "q-c");
    expect(qc && qc.kind === "queued" && qc.position).toBe(2);
    const daint = rows.find((r) => r.kind === "running" && r.run.run_id === "r-new");
    expect(daint && daint.kind === "running" && daint.machineLabel).toBe("Daint");
  });

  it("drops a finished run that is still listed as running", () => {
    const rows = mergeRecentRuns(machines, [finished("r-old"), finished("r-old", { arch: "cuda-daint" })], null);
    const keys = rows.map((r) => r.key);
    expect(keys.filter((k) => k === "master::cpu-serial::r-old")).toHaveLength(1);
    // Same run_id in another cell is a different run and stays.
    expect(keys).toContain("master::cuda-daint::r-old");
  });

  it("limits live rows to the given user", () => {
    const rows = mergeRecentRuns(machines, [], "alice");
    expect(rows.map((r) => r.key.split("::")[2])).toEqual(["r-old", "q-a", "q-c"]);
  });
});
