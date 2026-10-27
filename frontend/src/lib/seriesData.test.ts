import { describe, expect, it } from "vitest";
import { differenceRange, formatValue, mergeCurves, metricCurves } from "./seriesData";

describe("mergeCurves", () => {
  it("passes identical grids through", () => {
    const s = [0, 1, 2];
    const out = mergeCurves(s, [1, 2, 3], [0, 1, 2], [1, 2, 4]);
    expect(out).toEqual({ x: s, cur: [1, 2, 3], ref: [1, 2, 4] });
  });

  it("merges different grids into one ascending x with nulls", () => {
    const out = mergeCurves([0, 2, 4], [10, 12, 14], [0, 1, 4], [20, 21, 24]);
    expect(out.x).toEqual([0, 1, 2, 4]);
    expect(out.cur).toEqual([10, null, 12, 14]);
    expect(out.ref).toEqual([20, 21, null, 24]);
  });
});

describe("metricCurves", () => {
  it("prefers per-metric x over the container's and keeps the difference", () => {
    const container = {
      s: [0, 1],
      rs: [0, 1],
      m: {
        a: { cur: [1, 2], ref: [1, 3], d: { s: [0, 1], v: [0, -1] } },
        b: { cur: [5, 6], ref: [5, 6], s: [0, 0.5], rs: [0, 0.5] },
      },
    };
    expect(metricCurves(container, "a")).toEqual({
      x: [0, 1], cur: [1, 2], ref: [1, 3], diff: { x: [0, 1], v: [0, -1] },
    });
    expect(metricCurves(container, "b")?.x).toEqual([0, 0.5]);
    expect(metricCurves(container, "b")?.diff).toBeNull();
    expect(metricCurves(container, "missing")).toBeNull();
    expect(metricCurves(undefined, "a")).toBeNull();
  });
});

describe("differenceRange", () => {
  it("is symmetric and at least the tolerance", () => {
    expect(differenceRange([0, 1e-9, null], 1e-3)).toEqual([-1.1e-3, 1.1e-3]);
    expect(differenceRange([-2, 1], 0.5)).toEqual([-2.2, 2.2]);
    expect(differenceRange([0, 0], null)).toEqual([-1, 1]);
  });
});

describe("formatValue", () => {
  it("switches to exponential for small and large magnitudes", () => {
    expect(formatValue(0.25)).toBe("0.25");
    expect(formatValue(4.197e-9)).toBe("4.197e-9");
    expect(formatValue(123456789)).toBe("1.235e+8");
    expect(formatValue(null)).toBe("-");
  });
});
