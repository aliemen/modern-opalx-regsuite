import { lazy, Suspense, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, ExternalLink, FileText } from "lucide-react";
import type { RegressionMetric, RegressionSimulation, RunSeries } from "../../api/results";
import { StatusBadge } from "../../components/StatusBadge";
import { useBeamlineMesh } from "../../hooks/useBeamlineMesh";
import { metricCurves } from "../../lib/seriesData";
import { fmtDuration, fmtNum } from "./runDetailFormat";
import { PROBLEM_BORDER, StatusIcon, checkCounts } from "./simStatus";

const BeamlineViewer = lazy(() =>
  import("../../components/BeamlineViewer").then((m) => ({ default: m.BeamlineViewer }))
);
const SeriesPlot = lazy(() =>
  import("../../components/SeriesPlot").then((m) => ({ default: m.SeriesPlot }))
);

/** Where the run's series.json.gz comes from: the authenticated or the public route. */
export interface SeriesLoader {
  queryKey: readonly unknown[];
  load: () => Promise<RunSeries>;
}

const PLOT_PLACEHOLDER = "h-[300px] animate-pulse rounded bg-bg";
const ICON_BUTTON =
  "rounded border border-border p-1 text-muted transition-colors hover:text-fg disabled:cursor-not-allowed disabled:opacity-30";

interface SimDetailProps {
  sim: RegressionSimulation;
  runPath: string;
  series: SeriesLoader | null;
  onPrev?: () => void;
  onNext?: () => void;
}

/**
 * One regression test: its checks, the beamline and a plot per metric. From 1460px
 * (where two plot columns still fit beside the table) the plots take the left column
 * and the checks table and beamline sit on the right; narrower screens stack checks,
 * beamline, plots. Tests without plots (single-step
 * .stat files such as the Dist-* tests) show only their checks.
 */
export function SimDetail({ sim, runPath, series, onPrev, onNext }: SimDetailProps) {
  const [cIdx, setCIdx] = useState(0);
  const plotRefs = useRef(new Map<string, HTMLElement>());

  const containers = sim.containers ?? [];
  const counts = checkCounts(sim);
  const isMulti = containers.length > 1 && containers.some((c) => c.id !== null);
  const safeIdx = Math.min(cIdx, Math.max(0, containers.length - 1));
  const active = containers[safeIdx];
  const plotted = active ? active.metrics.filter((m) => m.series || m.plot) : [];

  // One fetch per run, shared by every test through the query cache.
  const seriesQuery = useQuery({
    queryKey: series?.queryKey ?? ["run-series", "none"],
    queryFn: () => series!.load(),
    enabled: !!series && plotted.some((m) => m.series),
    staleTime: Infinity,
  });
  const seriesContainer = seriesQuery.data?.sims[sim.name]?.[active?.id ?? "_"];
  const syncKey = `${runPath}/${sim.name}/${active?.id ?? "_"}`;

  function jumpToPlot(metric: string) {
    const el = plotRefs.current.get(metric);
    if (!el) return;
    el.scrollIntoView({ block: "center" });
    el.focus({ preventScroll: true });
  }

  function renderPlot(m: RegressionMetric) {
    const curves = m.series ? metricCurves(seriesContainer, m.metric) : null;
    if (curves) {
      return (
        <Suspense fallback={<div className={PLOT_PLACEHOLDER} />}>
          <SeriesPlot metric={m.metric} unit={m.unit} curves={curves} eps={m.eps} syncKey={syncKey} />
        </Suspense>
      );
    }
    if (m.series && seriesQuery.isPending && !!series) return <div className={PLOT_PLACEHOLDER} />;
    if (m.plot) {
      return (
        <img
          src={`/data/${runPath}/${m.plot}`}
          alt={`${sim.name} ${m.metric}`}
          className="w-full rounded"
          loading="lazy"
        />
      );
    }
    return <p className="py-8 text-center text-xs text-muted">Plot data unavailable.</p>;
  }

  return (
    <article className="min-w-0 rounded-xl border border-border bg-surface">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border px-4 py-3">
        <StatusIcon status={sim.state} size={18} />
        <h3 className="min-w-0 break-all font-semibold text-fg">{sim.name}</h3>
        {sim.state && <StatusBadge status={sim.state} />}
        <span className="text-xs tabular-nums text-muted">
          {counts.passed}/{counts.total} checks passed
          {counts.failed > 0 && <span className="ml-1.5 text-failed">· {counts.failed} failed</span>}
          {counts.crashed > 0 && <span className="ml-1.5 text-crashed">· {counts.crashed} crashed</span>}
          {counts.broken > 0 && <span className="ml-1.5 text-broken">· {counts.broken} broken</span>}
          {sim.duration_seconds != null && <span className="ml-1.5">· {fmtDuration(sim.duration_seconds)}</span>}
        </span>
        <div className="ml-auto flex items-center gap-1.5">
          {sim.log_file && (
            <a
              href={`/data/${runPath}/${sim.log_file}`}
              target="_blank"
              rel="noopener"
              className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-xs text-muted transition-colors hover:text-fg"
            >
              <FileText size={12} aria-hidden="true" /> Log
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
          )}
          <span className="hidden items-center gap-1.5 lg:flex">
            <button type="button" onClick={onPrev} disabled={!onPrev} className={ICON_BUTTON} aria-label="Previous test">
              <ChevronLeft size={14} />
            </button>
            <button type="button" onClick={onNext} disabled={!onNext} className={ICON_BUTTON} aria-label="Next test">
              <ChevronRight size={14} />
            </button>
          </span>
        </div>
      </header>

      <div className="space-y-4 p-4">
        {sim.description && <p className="text-sm text-muted">{sim.description}</p>}

        {sim.crash_signal && (
          <details className="text-xs" open>
            <summary className="cursor-pointer select-none font-medium text-crashed">
              Crashed: {sim.crash_signal}
              {sim.exit_code != null && <span className="ml-2 text-muted">(exit {sim.exit_code})</span>}
            </summary>
            {sim.crash_summary && (
              <pre className="mt-2 overflow-x-auto whitespace-pre-wrap rounded border border-crashed/30 bg-bg p-2 text-[11px] leading-relaxed text-muted">
                {sim.crash_summary}
              </pre>
            )}
          </details>
        )}

        {isMulti && (
          <div role="group" aria-label="Container" className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="mr-1 text-muted">Container</span>
            {containers.map((c, i) => (
              <button
                key={c.id ?? i}
                type="button"
                onClick={() => setCIdx(i)}
                aria-pressed={i === safeIdx}
                className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 font-mono transition-colors ${
                  i === safeIdx
                    ? "border-accent/60 bg-accent/10 text-fg"
                    : "border-border text-muted hover:text-fg"
                }`}
              >
                <StatusIcon status={c.state} size={12} />
                {c.id ?? "-"}
                <span className="sr-only">({c.state})</span>
              </button>
            ))}
          </div>
        )}

        {active && (
          <div
            className={
              plotted.length > 0
                ? "grid gap-4 [grid-template-areas:'checks'_'beamline'_'plots'] min-[1460px]:grid-cols-[minmax(0,1fr)_30rem] min-[1460px]:grid-rows-[auto_1fr] min-[1460px]:[grid-template-areas:'plots_checks'_'plots_beamline']"
                : "max-w-5xl"
            }
          >
            <div className="min-w-0 max-w-5xl [grid-area:checks] min-[1460px]:max-w-none">
              <ChecksTable
                metrics={active.metrics}
                caption={`Checks of ${sim.name}${isMulti ? `, container ${active.id}` : ""}`}
                onJump={(m) => (m.series || m.plot ? () => jumpToPlot(m.metric) : undefined)}
              />
            </div>
            {plotted.length > 0 && (
              <>
                <div className="min-w-0 [grid-area:beamline]">
                  <BeamlinePanel sim={sim} runPath={runPath} />
                </div>
                <div className="grid min-w-0 content-start gap-3 [grid-area:plots] [grid-template-columns:repeat(auto-fill,minmax(min(100%,18rem),1fr))]">
                  {plotted.map((m) => (
                    <figure
                      key={m.metric}
                      ref={(el) => {
                        if (el) plotRefs.current.set(m.metric, el);
                        else plotRefs.current.delete(m.metric);
                      }}
                      tabIndex={-1}
                      className={`m-0 min-w-0 rounded-lg border p-2 focus:outline-none focus:ring-2 focus:ring-accent ${
                        PROBLEM_BORDER[m.state] ?? "border-border"
                      }`}
                    >
                      <figcaption className="mb-1 flex min-w-0 items-center gap-1.5 text-xs">
                        <StatusIcon status={m.state} size={12} />
                        <span className="truncate font-mono text-fg">{m.metric}</span>
                        {m.unit && <span className="text-muted">[{m.unit}]</span>}
                        {m.state !== "passed" && (
                          <span className="ml-auto">
                            <StatusBadge status={m.state} />
                          </span>
                        )}
                      </figcaption>
                      {renderPlot(m)}
                    </figure>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </article>
  );
}

function ChecksTable({
  metrics,
  caption,
  onJump,
}: {
  metrics: RegressionMetric[];
  caption: string;
  onJump: (m: RegressionMetric) => (() => void) | undefined;
}) {
  const num = "px-2 py-1 text-right font-mono tabular-nums";
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-xs">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-bg/60 text-muted">
          <tr>
            <th scope="col" className="px-2 py-1.5 text-left font-medium">Metric</th>
            <th scope="col" className="px-2 py-1.5 text-left font-medium">Mode</th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">
              <abbr title="tolerance" className="no-underline">ε</abbr>
            </th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">
              <abbr title="deviation" className="no-underline">δ</abbr>
            </th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">Reference</th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">Current</th>
          </tr>
        </thead>
        <tbody>
          {metrics.map((m) => {
            const jump = onJump(m);
            const within = m.delta !== null && m.eps !== null && m.delta < m.eps;
            return (
              <tr key={m.metric} className={`border-t border-border/60 ${m.state !== "passed" ? "bg-failed/10" : ""}`}>
                <th scope="row" className="px-2 py-1 text-left font-mono font-normal text-fg">
                  <span className="flex items-center gap-1.5" title={m.state}>
                    <StatusIcon status={m.state} size={12} />
                    {jump ? (
                      <button
                        type="button"
                        onClick={jump}
                        className="text-left text-accent underline-offset-2 hover:underline"
                        title="Show the plot"
                      >
                        {m.metric}
                      </button>
                    ) : (
                      m.metric
                    )}
                    <span className="sr-only">, {m.state}</span>
                  </span>
                </th>
                <td className="px-2 py-1 text-muted">{m.mode}</td>
                <td className={`${num} text-muted`}>{fmtNum(m.eps, 3)}</td>
                <td className={`${num} ${within ? "text-passed" : "text-failed"}`}>{fmtNum(m.delta, 3)}</td>
                <td className={`${num} text-muted`}>{fmtNum(m.reference_value, 3)}</td>
                <td className={`${num} ${m.state === "passed" ? "text-muted" : "text-fg"}`}>{fmtNum(m.current_value, 3)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The 3D mesh when it has something to draw, else the 2D diagram; nothing when the
 * test has neither. The 3D/2D switch appears only when both are usable.
 */
function BeamlinePanel({ sim, runPath }: { sim: RegressionSimulation; runPath: string }) {
  const [preferred, setPreferred] = useState<"3d" | "2d">("3d");
  const mesh = useBeamlineMesh(sim.beamline_3d_data ? `/data/${runPath}/${sim.beamline_3d_data}` : null);
  const svgUrl = sim.beamline_plot ? `/data/${runPath}/${sim.beamline_plot}` : null;
  const has3d = !!mesh.data;

  if (sim.beamline_3d_data && mesh.isPending) {
    return <div className="aspect-video max-h-80 w-full animate-pulse rounded border border-border bg-bg" />;
  }
  if (!has3d && !svgUrl) return null;
  const view = has3d && (preferred === "3d" || !svgUrl) ? "3d" : "2d";

  return (
    <section aria-label="Beamline">
      <div className="mb-2 flex items-center gap-2">
        <h4 className="text-xs font-medium uppercase tracking-wide text-muted">Beamline</h4>
        {has3d && svgUrl && (
          <div role="group" aria-label="Beamline view" className="inline-flex overflow-hidden rounded border border-border text-[11px]">
            {(["3d", "2d"] as const).map((v, i) => (
              <button
                key={v}
                type="button"
                onClick={() => setPreferred(v)}
                aria-pressed={view === v}
                className={`px-2 py-0.5 transition-colors ${i > 0 ? "border-l border-border" : ""} ${
                  view === v ? "bg-border/60 text-fg" : "text-muted hover:bg-border/30 hover:text-fg"
                }`}
              >
                {v.toUpperCase()}
              </button>
            ))}
          </div>
        )}
        {view === "2d" && svgUrl && (
          <a
            href={svgUrl}
            target="_blank"
            rel="noopener"
            className="ml-auto inline-flex items-center gap-1 text-[11px] text-muted hover:text-fg"
          >
            <ExternalLink size={11} aria-hidden="true" /> Full size
            <span className="sr-only"> (opens in a new tab)</span>
          </a>
        )}
      </div>
      {view === "3d" && mesh.data ? (
        <Suspense fallback={<div className="aspect-video max-h-80 w-full animate-pulse rounded border border-border bg-bg" />}>
          <BeamlineViewer mesh={mesh.data} />
        </Suspense>
      ) : svgUrl ? (
        <img
          src={svgUrl}
          alt={`${sim.name} beamline diagram`}
          className="max-h-80 w-full rounded border border-border object-contain"
          loading="lazy"
        />
      ) : null}
    </section>
  );
}
