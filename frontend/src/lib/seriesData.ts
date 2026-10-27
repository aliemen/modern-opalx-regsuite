import type { SeriesContainer } from "../api/results";

type Values = (number | null)[];

export interface MetricCurves {
  /** One ascending x array shared by current and reference (uPlot's default mode). */
  x: number[];
  cur: Values;
  ref: Values;
  diff: { x: number[]; v: Values } | null;
}

/**
 * Put current and reference on one ascending x array, with null where a curve has
 * no sample. Identical grids (new runs) pass through unchanged; converted runs have
 * separate x per curve and are merged.
 */
export function mergeCurves(s: number[], cur: Values, rs: number[], ref: Values): Omit<MetricCurves, "diff"> {
  if (s.length === rs.length && s.every((v, i) => v === rs[i])) {
    return { x: s, cur, ref };
  }
  const x: number[] = [];
  const outCur: Values = [];
  const outRef: Values = [];
  let i = 0;
  let j = 0;
  while (i < s.length || j < rs.length) {
    if (j >= rs.length || (i < s.length && s[i] < rs[j])) {
      x.push(s[i]);
      outCur.push(cur[i]);
      outRef.push(null);
      i++;
    } else if (i >= s.length || rs[j] < s[i]) {
      x.push(rs[j]);
      outCur.push(null);
      outRef.push(ref[j]);
      j++;
    } else {
      x.push(s[i]);
      outCur.push(cur[i]);
      outRef.push(ref[j]);
      i++;
      j++;
    }
  }
  return { x, cur: outCur, ref: outRef };
}

/** Curves of one metric, or null when the series file has none for it. */
export function metricCurves(container: SeriesContainer | undefined, metric: string): MetricCurves | null {
  const m = container?.m[metric];
  if (!m) return null;
  const s = m.s ?? container?.s;
  const rs = m.rs ?? container?.rs;
  if (!s || !rs) return null;
  return { ...mergeCurves(s, m.cur, rs, m.ref), diff: m.d ? { x: m.d.s, v: m.d.v } : null };
}

/** Largest absolute value, 0 for an empty or all-null array. */
export function maxAbs(v: Values): number {
  let max = 0;
  for (const value of v) {
    if (value != null && Math.abs(value) > max) max = Math.abs(value);
  }
  return max;
}

/** Symmetric y range for the difference panel, at least +-tolerance so a passing check looks flat. */
export function differenceRange(v: Values, eps: number | null): [number, number] {
  const half = Math.max(maxAbs(v), eps ?? 0) * 1.1 || 1;
  return [-half, half];
}

/**
 * The sample at idx, or the closest non-null one. Merged curves of converted runs
 * have a null wherever only the other curve has a sample.
 */
export function nearestValue(v: Values, idx: number): number | null {
  for (let d = 0; d < v.length; d++) {
    const before = v[idx - d];
    if (before != null) return before;
    const after = v[idx + d];
    if (after != null) return after;
  }
  return null;
}

/** Compact axis/legend number: plain for ordinary magnitudes, exponential otherwise. */
export function formatValue(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "-";
  if (v === 0) return "0";
  const a = Math.abs(v);
  return a >= 1e-3 && a < 1e5 ? String(Number(v.toPrecision(6))) : v.toExponential(3);
}

/** Short axis tick: like formatValue, but exponents without trailing zeros (3e-4, 2.5e-4). */
export function formatTick(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "";
  const a = Math.abs(v);
  if (v === 0 || (a >= 1e-3 && a < 1e5)) return formatValue(v);
  return Number(v.toPrecision(4)).toExponential();
}
