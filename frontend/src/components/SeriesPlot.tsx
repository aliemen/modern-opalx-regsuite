import { useEffect, useRef, type ReactNode, type RefObject } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import { useThemeColors } from "../hooks/useThemeColors";
import { differenceRange, formatTick, formatValue, maxAbs, nearestValue, type MetricCurves } from "../lib/seriesData";

// amber-600: at least 3:1 against both theme backgrounds, unlike amber-500 on white.
const REFERENCE_COLOR = "rgb(217, 119, 6)";
const AXIS_FONT = "10px system-ui, -apple-system, sans-serif";
const Y_AXIS_PAD = 18; // tick length plus the gap between ticks and labels

let measureCtx: CanvasRenderingContext2D | null = null;
function labelWidth(labels: readonly string[] | null | undefined): number {
  measureCtx ??= document.createElement("canvas").getContext("2d");
  if (!measureCtx || !labels) return 0;
  measureCtx.font = AXIS_FONT;
  return Math.max(0, ...labels.map((l) => measureCtx!.measureText(l).width));
}

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
 *
 * uPlot's legend is replaced by a fixed two-line key below the panels: it shows the
 * last sample, or the sample under the cursor, without changing size on hover. The
 * dashed lines in the difference panel mark +-eps.
 */
export function SeriesPlot({ metric, unit, curves, eps, syncKey }: SeriesPlotProps) {
  const valueRef = useRef<HTMLDivElement>(null);
  const diffRef = useRef<HTMLDivElement>(null);
  const readout = {
    s: useRef<HTMLSpanElement>(null),
    cur: useRef<HTMLSpanElement>(null),
    ref: useRef<HTMLSpanElement>(null),
    diff: useRef<HTMLSpanElement>(null),
  };
  const colors = useThemeColors();

  useEffect(() => {
    const valueEl = valueRef.current;
    if (!valueEl) return;
    const width = Math.max(valueEl.clientWidth, 240);
    const last = curves.x.length - 1;
    const xRange: [number, number] = [curves.x[0] ?? 0, curves.x[last] ?? 1];
    const write = (el: HTMLSpanElement | null, v: number | null) => {
      if (el) el.textContent = formatValue(v);
    };
    const showValues = (idx: number | null | undefined) => {
      const i = idx ?? last;
      write(readout.s.current, curves.x[i] ?? null);
      write(readout.cur.current, nearestValue(curves.cur, i));
      write(readout.ref.current, nearestValue(curves.ref, i));
    };
    const showDiff = (idx: number | null | undefined) => {
      const v = curves.diff?.v ?? [];
      write(readout.diff.current, nearestValue(v, idx ?? v.length - 1));
    };
    showValues(null);
    showDiff(null);

    // Both panels take the widest y labels of either, so their plot areas line up.
    let yAxisWidth = 40;
    const ySize: uPlot.Axis.Size = (_u, values) => {
      yAxisWidth = Math.max(yAxisWidth, Math.ceil(labelWidth(values) + Y_AXIS_PAD));
      return yAxisWidth;
    };
    const axis = (overrides: Partial<uPlot.Axis> = {}): uPlot.Axis => ({
      size: ySize,
      font: AXIS_FONT,
      labelFont: AXIS_FONT,
      stroke: colors.muted,
      grid: { stroke: colors.border, width: 1 },
      ticks: { stroke: colors.border, width: 1 },
      values: (_u, splits) => splits.map((v) => formatTick(v)),
      ...overrides,
    });
    const base = (height: number): Pick<uPlot.Options, "width" | "height" | "cursor" | "legend"> => ({
      width,
      height,
      cursor: { sync: { key: syncKey } },
      legend: { show: false },
    });
    // The difference panel carries the shared s axis; the value panel above keeps only its grid.
    const hasDiff = !!curves.diff && !!diffRef.current;
    const xAxis = hasDiff
      ? axis({ size: 6, values: (_u, splits) => splits.map(() => "") })
      : axis({ size: 30, label: "s [m]", labelSize: 12 });

    const plots: uPlot[] = [
      new uPlot(
        {
          ...base(170),
          scales: { x: { time: false, range: () => xRange } },
          axes: [xAxis, axis()],
          series: [
            {},
            // Converted runs give current and reference different x, merged with nulls.
            { stroke: colors.accent, width: 1.5, spanGaps: true },
            { stroke: REFERENCE_COLOR, width: 1.5, dash: [6, 3], spanGaps: true },
          ],
          hooks: { setCursor: [(u) => showValues(u.cursor.idx)] },
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
            ...base(96),
            scales: { x: { time: false, range: () => xRange }, y: { range: () => range } },
            axes: [axis({ size: 30, label: "s [m]", labelSize: 12 }), axis()],
            series: [{}, { stroke: colors.fg, width: 1, spanGaps: true }],
            hooks: {
              setCursor: [(u) => showDiff(u.cursor.idx)],
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

    if (plots.length > 1) plots[0].redraw(false, true); // adopt a wider difference axis

    const observer = new ResizeObserver(() => {
      const w = Math.max(valueEl.clientWidth, 240);
      for (const p of plots) p.setSize({ width: w, height: p.height });
    });
    observer.observe(valueEl);
    return () => {
      observer.disconnect();
      for (const p of plots) p.destroy();
    };
    // readout refs are stable; listing them would only add noise
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [curves, eps, syncKey, colors]);

  const span = `${formatValue(curves.x[0])} to ${formatValue(curves.x[curves.x.length - 1])} m`;
  const summary =
    `${metric}${unit ? ` [${unit}]` : ""}: current and reference over s from ${span}.` +
    (curves.diff
      ? ` Largest difference ${formatValue(maxAbs(curves.diff.v))}` +
        (eps ? `, tolerance ${formatValue(eps)}.` : ".")
      : "");

  return (
    <div className="text-[11px] leading-4 text-muted">
      <div role="img" aria-label={summary}>
        <div ref={valueRef} />
        {curves.diff && <div ref={diffRef} />}
      </div>
      <div aria-hidden="true" className="mt-1 grid grid-cols-2 gap-x-3 tabular-nums whitespace-nowrap">
        <KeyCell swatch={<Swatch color={colors.accent} />} label="cur" title="current" valueRef={readout.cur} />
        <KeyCell swatch={<Swatch color={REFERENCE_COLOR} dashed />} label="ref" title="reference" valueRef={readout.ref} />
        <KeyCell label="s [m]" valueRef={readout.s} />
        {curves.diff && (
          <KeyCell swatch={<Swatch color={colors.fg} />} label="diff" title="current - reference" valueRef={readout.diff} />
        )}
      </div>
    </div>
  );
}

function KeyCell({
  swatch,
  label,
  title,
  valueRef,
}: {
  swatch?: ReactNode;
  label: string;
  title?: string;
  valueRef: RefObject<HTMLSpanElement | null>;
}) {
  return (
    <span className="flex min-w-0 items-center gap-1" title={title}>
      {swatch}
      <span className="truncate">{label}</span>
      <span ref={valueRef} className="ml-auto pl-1 font-mono text-fg" />
    </span>
  );
}

function Swatch({ color, dashed = false }: { color: string; dashed?: boolean }) {
  return (
    <svg width="14" height="4" className="shrink-0">
      <line x1="0" y1="2" x2="14" y2="2" stroke={color} strokeWidth="2" strokeDasharray={dashed ? "4 2" : undefined} />
    </svg>
  );
}
