import { lazy, Suspense, useState } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, ExternalLink } from "lucide-react";
import type { RegressionSimulation } from "../../api/results";
import { StatusBadge } from "../../components/StatusBadge";
import { fmtDuration, fmtNum } from "./runDetailFormat";

const BeamlineViewer = lazy(() =>
  import("../../components/BeamlineViewer").then((m) => ({ default: m.BeamlineViewer }))
);

export function SimCard({ sim, runPath }: { sim: RegressionSimulation; runPath: string }) {
  const [open, setOpen] = useState(false);
  const [cIdx, setCIdx] = useState(0);
  const [beamlineView, setBeamlineView] = useState<"3d" | "2d">(
    sim.beamline_3d_data ? "3d" : "2d"
  );

  const containers = sim.containers ?? [];
  const allMetrics = containers.flatMap((c) => c.metrics);
  const passedCount = allMetrics.filter((m) => m.state === "passed").length;
  const failedCount = allMetrics.filter((m) => m.state === "failed").length;
  const brokenCount = allMetrics.filter((m) => m.state === "broken").length;
  const crashedCount = allMetrics.filter((m) => m.state === "crashed").length;
  const totalCount = allMetrics.length;
  const isMulti = containers.length > 1 && containers.some((c) => c.id !== null);
  const safeIdx = Math.min(cIdx, Math.max(0, containers.length - 1));
  const active = containers[safeIdx];

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-4 py-3 bg-surface hover:bg-border/30 text-left transition-colors"
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <span className="text-fg font-medium text-sm flex-1">{sim.name}</span>
        <span className="text-xs tabular-nums flex items-center gap-1 mr-2">
          <span className="text-passed">{passedCount}</span>
          <span className="text-muted">/{totalCount}</span>
          {failedCount > 0 && (
            <span className="text-failed ml-1">{failedCount} failed</span>
          )}
          {crashedCount > 0 && (
            <span className="text-crashed ml-1">{crashedCount} crashed</span>
          )}
          {brokenCount > 0 && (
            <span className="text-broken ml-1">{brokenCount} broken</span>
          )}
        </span>
        {sim.duration_seconds != null && (
          <span className="text-muted text-xs mr-2 tabular-nums">
            {fmtDuration(sim.duration_seconds)}
          </span>
        )}
        {sim.state && <StatusBadge status={sim.state} />}
        {sim.log_file && (
          <a
            href={`/data/${runPath}/${sim.log_file}`}
            target="_blank"
            rel="noopener"
            onClick={(e) => e.stopPropagation()}
            className="text-muted hover:text-fg ml-2"
            title="View log"
          >
            <ExternalLink size={12} />
          </a>
        )}
      </button>

      {open && (
        <div className="border-t border-border px-4 py-4 space-y-4">
          {sim.crash_signal && (
            <details className="text-xs" open>
              <summary className="text-crashed cursor-pointer font-medium select-none">
                Crashed: {sim.crash_signal}
                {sim.exit_code != null && <span className="text-muted ml-2">(exit {sim.exit_code})</span>}
              </summary>
              {sim.crash_summary && (
                <pre className="mt-2 p-2 bg-surface rounded border border-crashed/30 text-muted overflow-x-auto whitespace-pre-wrap text-[11px] leading-relaxed">
                  {sim.crash_summary}
                </pre>
              )}
            </details>
          )}

          {(sim.beamline_3d_data || sim.beamline_plot) && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <p className="text-muted text-xs uppercase tracking-wide font-medium">Beamline</p>
                {sim.beamline_3d_data && sim.beamline_plot && (
                  <div className="inline-flex rounded border border-border overflow-hidden text-[11px]">
                    <button
                      type="button"
                      onClick={() => setBeamlineView("3d")}
                      className={`px-2 py-0.5 transition-colors ${
                        beamlineView === "3d"
                          ? "bg-border/60 text-fg"
                          : "text-muted hover:text-fg hover:bg-border/30"
                      }`}
                      aria-pressed={beamlineView === "3d"}
                    >
                      3D
                    </button>
                    <button
                      type="button"
                      onClick={() => setBeamlineView("2d")}
                      className={`px-2 py-0.5 border-l border-border transition-colors ${
                        beamlineView === "2d"
                          ? "bg-border/60 text-fg"
                          : "text-muted hover:text-fg hover:bg-border/30"
                      }`}
                      aria-pressed={beamlineView === "2d"}
                    >
                      2D
                    </button>
                  </div>
                )}
              </div>
              {sim.beamline_3d_data && (beamlineView === "3d" || !sim.beamline_plot) ? (
                <Suspense
                  fallback={
                    <div className="aspect-video animate-pulse bg-surface rounded border border-border" />
                  }
                >
                  <BeamlineViewer url={`/data/${runPath}/${sim.beamline_3d_data}`} />
                </Suspense>
              ) : sim.beamline_plot ? (
                <img
                  src={`/data/${runPath}/${sim.beamline_plot}`}
                  alt={`${sim.name} beamline diagram`}
                  className="w-full rounded border border-border"
                  loading="lazy"
                />
              ) : null}
            </div>
          )}

          {isMulti && active && (
            <div className="flex items-center gap-2 text-xs">
              <button
                onClick={() => setCIdx((i) => Math.max(0, i - 1))}
                disabled={safeIdx === 0}
                className="p-1 rounded border border-border text-muted hover:text-fg disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                title="Previous container"
                aria-label="Previous container"
              >
                <ChevronLeft size={14} />
              </button>
              <span className="text-fg font-mono">
                Container {active.id ?? "—"}
              </span>
              <span className="text-muted tabular-nums">
                ({safeIdx + 1} / {containers.length})
              </span>
              <button
                onClick={() =>
                  setCIdx((i) => Math.min(containers.length - 1, i + 1))
                }
                disabled={safeIdx === containers.length - 1}
                className="p-1 rounded border border-border text-muted hover:text-fg disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                title="Next container"
                aria-label="Next container"
              >
                <ChevronRight size={14} />
              </button>
              {active.state && (
                <span className="ml-1">
                  <StatusBadge status={active.state} />
                </span>
              )}
            </div>
          )}

          {active && (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-muted text-left">
                  <tr>
                    <th className="pb-2 font-medium">Metric</th>
                    <th className="pb-2 font-medium">Mode</th>
                    <th className="pb-2 font-medium">ε</th>
                    <th className="pb-2 font-medium">δ</th>
                    <th className="pb-2 font-medium">Reference</th>
                    <th className="pb-2 font-medium">Current</th>
                    <th className="pb-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {active.metrics.map((m) => (
                    <tr key={m.metric} className="border-t border-border/50">
                      <td className="py-1.5 font-mono text-fg">{m.metric}</td>
                      <td className="py-1.5 text-muted">{m.mode}</td>
                      <td className="py-1.5 text-muted font-mono">{fmtNum(m.eps)}</td>
                      <td className={`py-1.5 font-mono ${m.delta !== null && m.eps !== null && m.delta < m.eps ? "text-passed" : "text-failed"}`}>
                        {fmtNum(m.delta)}
                      </td>
                      <td className="py-1.5 font-mono text-muted">{fmtNum(m.reference_value)}</td>
                      <td className="py-1.5 font-mono text-muted">{fmtNum(m.current_value)}</td>
                      <td className="py-1.5">
                        <StatusBadge status={m.state} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {active && active.metrics.filter((m) => m.plot).length > 0 && (
            <div className="grid gap-3 sm:grid-cols-2">
              {active.metrics
                .filter((m) => m.plot)
                .map((m) => (
                  <div key={m.metric}>
                    <p className="text-muted text-xs mb-1">{m.metric}</p>
                    <img
                      src={`/data/${runPath}/${m.plot}`}
                      alt={`${sim.name} ${m.metric}`}
                      className="w-full rounded border border-border"
                      loading="lazy"
                    />
                  </div>
                ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
