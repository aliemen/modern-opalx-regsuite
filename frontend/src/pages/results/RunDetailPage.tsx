import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Archive, ChevronDown, ChevronLeft, ChevronRight, ExternalLink, Globe2, Lock, Trash2 } from "lucide-react";
import { archiveRun, deleteRun, getRunDetail, setRunVisibility, type RegressionSimulation } from "../../api/results";
import { StatusBadge } from "../../components/StatusBadge";
import { Breadcrumb } from "../../components/Breadcrumb";

export function fmtNum(n: number | null | undefined, digits = 4) {
  if (n === null || n === undefined) return "—";
  return n.toExponential(digits);
}

export function fmtDate(d: string | null) {
  if (!d) return "—";
  return new Date(d).toLocaleString();
}

export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

export function duration(start: string, end: string | null) {
  if (!end) return "—";
  const s = Math.floor((new Date(end).getTime() - new Date(start).getTime()) / 1000);
  const m = Math.floor(s / 60);
  return `${m}m ${(s % 60).toString().padStart(2, "0")}s`;
}

export function SimCard({ sim, runPath }: { sim: RegressionSimulation; runPath: string }) {
  const [open, setOpen] = useState(false); // default closed for better overview
  const [cIdx, setCIdx] = useState(0);

  const containers = sim.containers ?? [];
  const allMetrics = containers.flatMap((c) => c.metrics);

  const passedCount  = allMetrics.filter((m) => m.state === "passed").length;
  const failedCount  = allMetrics.filter((m) => m.state === "failed").length;
  const brokenCount  = allMetrics.filter((m) => m.state === "broken").length;
  const crashedCount = allMetrics.filter((m) => m.state === "crashed").length;
  const totalCount   = allMetrics.length;

  // Only treat as multi-beam when there is more than one container AND at
  // least one has a non-null id. Single-beam runs after migration have
  // exactly one container with id=null; those must render exactly like
  // they did before this refactor.
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

        {/* Pass/fail counts */}
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

        {/* Duration */}
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
          {/* Crash info */}
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

          {/* Beamline diagram — shared across containers */}
          {sim.beamline_plot && (
            <div>
              <p className="text-muted text-xs mb-2 uppercase tracking-wide font-medium">Beamline</p>
              <img
                src={`/data/${runPath}/${sim.beamline_plot}`}
                alt={`${sim.name} beamline diagram`}
                className="w-full rounded border border-border"
                loading="lazy"
              />
            </div>
          )}

          {/* Container pager — only for multi-beam runs */}
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

          {/* Metrics table — from the active container (single-beam runs have exactly one) */}
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

          {/* Metric plots — from the active container */}
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

export const OPALX_COMMIT_BASE = "https://github.com/OPALX-project/OPALX/commit";
export const REGTESTS_COMMIT_BASE = "https://github.com/OPALX-project/regression-tests-x/commit";

export function CommitLink({ hash, base }: { hash: string | null; base: string }) {
  if (!hash) return <span className="text-muted">—</span>;
  const short = hash.slice(0, 10);
  return (
    <a
      href={`${base}/${hash}`}
      target="_blank"
      rel="noopener noreferrer"
      className="font-mono text-accent hover:underline"
    >
      {short}
    </a>
  );
}

export function RunDetailPage() {
  const { branch, arch, runId } = useParams<{
    branch: string;
    arch: string;
    runId: string;
  }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["run-detail", branch, arch, runId],
    queryFn: () => getRunDetail(branch!, arch!, runId!),
    enabled: !!branch && !!arch && !!runId,
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteRun(branch!, arch!, runId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runs", branch, arch] });
      queryClient.invalidateQueries({ queryKey: ["branches"] });
      navigate(`/results/${branch}/${arch}`);
    },
  });

  const archiveMutation = useMutation({
    mutationFn: (archived: boolean) => archiveRun(branch!, arch!, runId!, archived),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["run-detail", branch, arch, runId] });
      queryClient.invalidateQueries({ queryKey: ["runs", branch, arch] });
      queryClient.invalidateQueries({ queryKey: ["branches"] });
    },
  });

  const [publishNotice, setPublishNotice] = useState<string | null>(null);
  const publishMutation = useMutation({
    mutationFn: (isPublic: boolean) =>
      setRunVisibility(branch!, arch!, runId!, isPublic),
    onSuccess: (_entry, isPublic) => {
      queryClient.invalidateQueries({ queryKey: ["run-detail", branch, arch, runId] });
      queryClient.invalidateQueries({ queryKey: ["runs", branch, arch] });
      queryClient.invalidateQueries({ queryKey: ["public", "all-runs"] });
      queryClient.invalidateQueries({ queryKey: ["public", "activity"] });
      if (isPublic) {
        const publicUrl = `${window.location.origin}/public/runs/${encodeURIComponent(branch!)}/${encodeURIComponent(arch!)}/${encodeURIComponent(runId!)}`;
        try {
          navigator.clipboard.writeText(publicUrl);
          setPublishNotice("Published \u2014 public link copied to clipboard.");
        } catch {
          setPublishNotice(`Published \u2014 public link: ${publicUrl}`);
        }
      } else {
        setPublishNotice("Unpublished. This run is no longer visible on the public page.");
      }
      setTimeout(() => setPublishNotice(null), 5000);
    },
  });

  const [showUnitDetails, setShowUnitDetails] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmArchive, setConfirmArchive] = useState(false);

  if (isLoading) return <div className="p-8 text-muted">Loading…</div>;
  if (error || !data)
    return <div className="p-8 text-failed">Failed to load run data.</div>;

  const { meta, unit, regression } = data;
  const runPath = `runs/${branch}/${arch}/${runId}`;
  const qs = searchParams.toString();
  const listHref = `/results/${branch}/${arch}${qs ? `?${qs}` : ""}`;
  const regtestLabel = meta.regtest_branch ?? "\u2014";

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <Breadcrumb
        crumbs={[
          {
            label: `${branch} \u00b7 ${arch}`,
            to: listHref,
            title: `All runs on ${branch} / ${arch}`,
          },
          {
            label: `regtests=${regtestLabel}`,
            title: `Regression-tests branch for this run`,
          },
          { label: runId ?? "", title: "Run ID" },
        ]}
      />
      <div className="flex items-center justify-end">
        {confirmArchive ? (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted">{meta.archived ? "Unarchive" : "Archive"} this run?</span>
            <button
              onClick={() => { archiveMutation.mutate(!meta.archived); setConfirmArchive(false); }}
              disabled={archiveMutation.isPending}
              className="px-3 py-1 rounded bg-accent/20 border border-accent/40 text-accent hover:bg-accent/30 transition disabled:opacity-50"
            >
              {archiveMutation.isPending ? "Saving…" : "Confirm"}
            </button>
            <button
              onClick={() => setConfirmArchive(false)}
              className="px-3 py-1 rounded border border-border text-muted hover:text-fg transition"
            >
              Cancel
            </button>
          </div>
        ) : confirmDelete ? (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted">Delete this run?</span>
            <button
              onClick={() => deleteMutation.mutate()}
              disabled={deleteMutation.isPending}
              className="px-3 py-1 rounded bg-failed/20 border border-failed/40 text-failed hover:bg-failed/30 transition disabled:opacity-50"
            >
              {deleteMutation.isPending ? "Deleting…" : "Confirm"}
            </button>
            <button
              onClick={() => setConfirmDelete(false)}
              className="px-3 py-1 rounded border border-border text-muted hover:text-fg transition"
            >
              Cancel
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <button
              onClick={() => publishMutation.mutate(!meta.public)}
              disabled={publishMutation.isPending}
              className="flex items-center gap-1.5 text-muted hover:text-accent text-sm transition-colors disabled:opacity-50"
              title={meta.public ? "Make this run private" : "Publish this run"}
            >
              {meta.public ? <Lock size={14} /> : <Globe2 size={14} />}
              {publishMutation.isPending
                ? "Saving\u2026"
                : meta.public
                ? "Unpublish"
                : "Publish"}
            </button>
            <button
              onClick={() => setConfirmArchive(true)}
              className="flex items-center gap-1.5 text-muted hover:text-accent text-sm transition-colors"
              title={meta.archived ? "Unarchive run" : "Archive run"}
            >
              <Archive size={14} /> {meta.archived ? "Unarchive run" : "Archive run"}
            </button>
            <button
              onClick={() => setConfirmDelete(true)}
              className="flex items-center gap-1.5 text-muted hover:text-failed text-sm transition-colors"
              title="Delete run"
            >
              <Trash2 size={14} /> Delete run
            </button>
          </div>
        )}
      </div>

      {publishNotice && (
        <div className="bg-accent/10 border border-accent/40 text-accent text-sm rounded-lg px-4 py-2">
          {publishNotice}
        </div>
      )}

      {/* Meta card */}
      <div className="bg-surface border border-border rounded-xl p-5 grid sm:grid-cols-2 gap-4 text-sm">
        <div className="space-y-1">
          <p className="text-muted text-xs">Run ID</p>
          <p className="font-mono text-fg">{meta.run_id}</p>
        </div>
        <div className="space-y-1">
          <p className="text-muted text-xs">Status</p>
          <div className="flex items-center gap-2">
            <StatusBadge status={meta.status} size="md" />
            {meta.public ? (
              <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border border-accent/40 text-accent bg-accent/10">
                <Globe2 size={10} />
                Public
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border border-border text-muted">
                <Lock size={10} />
                Private
              </span>
            )}
          </div>
        </div>
        <div className="space-y-1">
          <p className="text-muted text-xs">OPALX Branch</p>
          <p className="text-fg">{meta.branch}</p>
        </div>
        <div className="space-y-1">
          <p className="text-muted text-xs">Tests Branch</p>
          <p className="text-fg font-mono text-sm">{meta.regtest_branch ?? "—"}</p>
        </div>
        <div className="space-y-1">
          <p className="text-muted text-xs">Duration</p>
          <p className="text-fg">{duration(meta.started_at, meta.finished_at)}</p>
        </div>
        <div className="space-y-1">
          <p className="text-muted text-xs">Arch / Executed On</p>
          <p className="text-fg font-mono text-sm">
            {meta.arch} / {meta.connection_name && meta.connection_name !== "local"
              ? meta.connection_name
              : "local"}
          </p>
        </div>
        <div className="space-y-1">
          <p className="text-muted text-xs">Triggered By</p>
          {meta.triggered_by ? (
            <Link
              to={`/activity?user=${encodeURIComponent(meta.triggered_by)}`}
              className="text-accent hover:underline font-mono text-sm"
              title={`Show all runs triggered by ${meta.triggered_by}`}
            >
              {meta.triggered_by}
            </Link>
          ) : (
            <p className="text-fg font-mono text-sm">—</p>
          )}
        </div>
        <div className="space-y-1">
          <p className="text-muted text-xs">Started</p>
          <p className="text-fg">{fmtDate(meta.started_at)}</p>
        </div>
        <div className="space-y-1">
          <p className="text-muted text-xs">Commits</p>
          <div className="text-xs space-y-0.5">
            <p>
              <span className="text-muted">opalx: </span>
              <CommitLink hash={meta.opalx_commit} base={OPALX_COMMIT_BASE} />
            </p>
            <p>
              <span className="text-muted">tests: </span>
              <CommitLink hash={meta.tests_repo_commit} base={REGTESTS_COMMIT_BASE} />
            </p>
          </div>
        </div>
        <div className="sm:col-span-2">
          <a
            href={`/data/${runPath}/logs/pipeline.log`}
            target="_blank"
            rel="noopener"
            className="flex items-center gap-1 text-accent text-xs hover:underline"
          >
            <ExternalLink size={11} /> pipeline.log
          </a>
        </div>
      </div>

      {/* Unit tests */}
      {unit.tests.length > 0 && (
        <div className="bg-surface border border-border rounded-xl overflow-hidden">
          <button
            onClick={() => setShowUnitDetails(!showUnitDetails)}
            className="w-full flex items-center gap-3 px-5 py-4 hover:bg-border/30 transition-colors text-left"
          >
            {showUnitDetails ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <span className="text-fg font-medium">Unit Tests</span>
            <span className="text-muted text-sm ml-auto">
              {meta.unit_tests_total - meta.unit_tests_failed}/{meta.unit_tests_total} passed
              {meta.unit_tests_failed > 0 && (
                <span className="text-failed ml-2">{meta.unit_tests_failed} failed</span>
              )}
            </span>
          </button>
          {showUnitDetails && (
            <div className="border-t border-border p-4 overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-muted">
                  <tr>
                    <th className="text-left pb-2">Test</th>
                    <th className="text-left pb-2">Status</th>
                    <th className="text-left pb-2">Duration</th>
                  </tr>
                </thead>
                <tbody>
                  {unit.tests.map((t) => (
                    <tr key={t.name} className="border-t border-border/40">
                      <td className="py-1.5 font-mono text-fg">{t.name}</td>
                      <td className="py-1.5">
                        <StatusBadge status={t.status} />
                      </td>
                      <td className="py-1.5 text-muted">
                        {t.duration_seconds != null ? `${t.duration_seconds.toFixed(2)}s` : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Regression tests */}
      {regression.simulations.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-fg font-medium">
            Regression Tests
            <span className="text-muted font-normal text-sm ml-2">
              {meta.regression_passed}/{meta.regression_total} passed
              {meta.regression_failed > 0 && (
                <span className="text-failed ml-1">· {meta.regression_failed} failed</span>
              )}
              {meta.regression_broken > 0 && (
                <span className="text-broken ml-1">· {meta.regression_broken} broken</span>
              )}
            </span>
          </h2>
          {regression.simulations.map((sim) => (
            <SimCard key={sim.name} sim={sim} runPath={runPath} />
          ))}
        </div>
      )}
    </div>
  );
}
