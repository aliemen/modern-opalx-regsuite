import { useEffect, useRef } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import { useThemeColors } from "../hooks/useThemeColors";
import { differenceRange, formatValue, type MetricCurves } from "../lib/seriesData";

const REFERENCE_COLOR = "rgb(245, 158, 11)"; // amber-500, readable on both themes

interface SeriesPlotProps {
  metric: string;
  unit?: string | null;
  curves: MetricCurves;
  /** Tolerance of the check; the difference panel spans at least +-eps. */
  eps: number | null;
  /** Panels with the same key share the hover cursor. */
  syncKey: string;
}

/**
 * Current vs reference of one metric (top) and their difference (bottom), drawn by
 * uPlot from series.json.gz. Pass/fail was computed on the server from all rows.
 */
export function SeriesPlot({ metric, unit, curves, eps, syncKey }: SeriesPlotProps) {
  const valueRef = useRef<HTMLDivElement>(null);
  const diffRef = useRef<HTMLDivElement>(null);
  const colors = useThemeColors();

  useEffect(() => {
    const valueEl = valueRef.current;
    if (!valueEl) return;
    const width = Math.max(valueEl.clientWidth, 280);
    const xRange: [number, number] = [curves.x[0] ?? 0, curves.x[curves.x.length - 1] ?? 1];
    const fmt = (_u: uPlot, v: number | null) => formatValue(v);
    const axis = (label?: string): uPlot.Axis => ({
      label,
      labelSize: 16,
      size: 64,
      stroke: colors.muted,
      grid: { stroke: colors.border, width: 1 },
      ticks: { stroke: colors.border, width: 1 },
      values: (_u, splits) => splits.map((v) => formatValue(v)),
    });
    const base = (height: number): Pick<uPlot.Options, "width" | "height" | "cursor" | "scales"> => ({
      width,
      height,
      cursor: { sync: { key: syncKey } },
      scales: { x: { time: false, range: () => xRange } },
    });

    const plots: uPlot[] = [
      new uPlot(
        {
          ...base(200),
          axes: [{ ...axis(), size: 32 }, axis(unit ? `${metric} [${unit}]` : metric)],
          series: [
            { label: "s [m]", value: fmt },
            // Converted runs give current and reference different x, merged with nulls.
            { label: "current", stroke: colors.accent, width: 1.5, spanGaps: true, value: fmt },
            { label: "reference", stroke: REFERENCE_COLOR, width: 1.5, dash: [6, 3], spanGaps: true, value: fmt },
          ],
        },
        [curves.x, curves.cur, curves.ref] as uPlot.AlignedData,
        valueEl
      ),
    ];

    if (curves.diff && diffRef.current) {
      const range = differenceRange(curves.diff.v, eps);
      plots.push(
        new uPlot(
          {
            ...base(110),
            scales: { x: { time: false, range: () => xRange }, y: { range: () => range } },
            axes: [{ ...axis("s [m]"), size: 40 }, axis("difference")],
            series: [
              { label: "s [m]", value: fmt },
              { label: "current - reference", stroke: colors.fg, width: 1, spanGaps: true, value: fmt },
            ],
            hooks: {
              draw: [
                (u) => {
                  if (!eps) return;
                  const ctx = u.ctx;
                  ctx.save();
                  ctx.strokeStyle = colors.muted;
                  ctx.setLineDash([4, 4]);
                  for (const y of [eps, -eps]) {
                    const py = u.valToPos(y, "y", true);
                    ctx.beginPath();
                    ctx.moveTo(u.bbox.left, py);
                    ctx.lineTo(u.bbox.left + u.bbox.width, py);
                    ctx.stroke();
                  }
                  ctx.restore();
                },
              ],
            },
          },
          [curves.diff.x, curves.diff.v] as uPlot.AlignedData,
          diffRef.current
        )
      );
    }

    const observer = new ResizeObserver(() => {
      const w = Math.max(valueEl.clientWidth, 280);
      for (const p of plots) p.setSize({ width: w, height: p.height });
    });
    observer.observe(valueEl);
    return () => {
      observer.disconnect();
      for (const p of plots) p.destroy();
    };
  }, [curves, metric, unit, eps, syncKey, colors]);

  return (
    <div className="text-xs text-muted">
      <div ref={valueRef} />
      {curves.diff && <div ref={diffRef} />}
    </div>
  );
}
