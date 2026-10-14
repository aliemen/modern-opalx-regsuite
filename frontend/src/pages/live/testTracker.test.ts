import { describe, expect, it } from "vitest";
import { applyTrackerLine, type TestInfo } from "./testTracker";

describe("applyTrackerLine", () => {
  it("adds skipped rows without a timer and ignores unrelated lines", () => {
    let tests: TestInfo[] = [];
    tests = applyTrackerLine(tests, "[regression] SKIP DBA-COF-Gauss", 1000);
    expect(tests).toEqual([
      { name: "DBA-COF-Gauss", status: "skipped", startTime: 1000, durationMs: null },
    ]);
    const same = applyTrackerLine(tests, "[unit] Skipping by config: TestA", 2000);
    expect(same).toBe(tests);
  });

  it("keeps START/END behavior including authoritative durations", () => {
    let tests: TestInfo[] = [];
    tests = applyTrackerLine(tests, "[regression] START FodoCell", 1000);
    tests = applyTrackerLine(
      tests,
      "[regression] END FodoCell state=passed duration_ms=4200 metrics=3",
      9000,
    );
    expect(tests[0]).toMatchObject({ name: "FodoCell", status: "passed", durationMs: 4200 });
  });
});
