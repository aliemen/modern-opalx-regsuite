import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, ChevronDown, ChevronRight, ExternalLink, Trash2 } from "lucide-react";
import { deleteRun, getRunDetail, type RegressionSimulation } from "../../api/results";
import { StatusBadge } from "../../components/StatusBadge";

function fmtNum(n: number | null | undefined, digits = 4) {
  if (n === null || n === undefined) return "—";
  return n.toExponential(digits);
}

function fmtDate(d: string | null) {
  if (!d) return "—";
  return new Date(d).toLocaleString();
}

function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

function duration(start: string, end: string | null) {
  if (!end) return "—";
  const s = Math.floor((new Date(end).getTime() - new Date(start).getTime()) / 1000);
  const m = Math.floor(s / 60);
  return `${m}m ${(s % 60).toString().padStart(2, "0")}s`;
}

function SimCard({ sim, runPath }: { sim: RegressionSimulation; runPath: string }) {
  const [open, setOpen] = useState(false); // default closed for better overview

  const passedCount = sim.metrics.filter((m) => m.state === "passed").length;
  const failedCount = sim.metrics.filter((m) => m.state === "failed").length;
  const brokenCount = sim.metrics.filter((m) => m.state === "broken").length;
  const totalCount = sim.metrics.length;

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
          {/* Metrics table */}
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
                {sim.metrics.map((m) => (
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

          {/* Plots */}
          {sim.metrics.filter((m) => m.plot).length > 0 && (
            <div className="grid gap-3 sm:grid-cols-2">
              {sim.metrics
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

const OPALX_COMMIT_BASE = "https://github.com/OPALX-project/OPALX/commit";
const REGTESTS_COMMIT_BASE = "https://github.com/OPALX-project/regression-tests-x/commit";

function CommitLink({ hash, base }: { hash: string | null; base: string }) {
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

  const [showUnitDetails, setShowUnitDetails] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  if (isLoading) return <div className="p-8 text-muted">Loading…</div>;
  if (error || !data)
    return <div className="p-8 text-failed">Failed to load run data.</div>;

  const { meta, unit, regression } = data;
  const runPath = `runs/${branch}/${arch}/${runId}`;

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <Link
          to={`/results/${branch}/${arch}`}
          className="flex items-center gap-1.5 text-muted hover:text-fg text-sm transition-colors"
        >
          <ArrowLeft size={14} /> {branch} / {arch}
        </Link>

        {confirmDelete ? (
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
          <button
            onClick={() => setConfirmDelete(true)}
            className="flex items-center gap-1.5 text-muted hover:text-failed text-sm transition-colors"
            title="Delete run"
          >
            <Trash2 size={14} /> Delete run
          </button>
        )}
      </div>

      {/* Meta card */}
      <div className="bg-surface border border-border rounded-xl p-5 grid sm:grid-cols-2 gap-4 text-sm">
        <div className="space-y-1">
          <p className="text-muted text-xs">Run ID</p>
          <p className="font-mono text-fg">{meta.run_id}</p>
        </div>
        <div className="space-y-1">
          <p className="text-muted text-xs">Status</p>
          <StatusBadge status={meta.status} size="md" />
        </div>
        <div className="space-y-1">
          <p className="text-muted text-xs">Branch / Arch</p>
          <p className="text-fg">{meta.branch} / {meta.arch}</p>
        </div>
        <div className="space-y-1">
          <p className="text-muted text-xs">Duration</p>
          <p className="text-fg">{duration(meta.started_at, meta.finished_at)}</p>
        </div>
        <div className="space-y-1">
          <p className="text-muted text-xs">Executed On</p>
          <p className="text-fg font-mono text-sm">
            {meta.connection_name && meta.connection_name !== "local"
              ? meta.connection_name
              : "Local"}
          </p>
        </div>
        <div className="space-y-1">
          <p className="text-muted text-xs">Triggered By</p>
          <p className="text-fg font-mono text-sm">{meta.triggered_by ?? "—"}</p>
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
