/* eslint-disable react-refresh/only-export-components */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Archive, FileText, Globe2, Lock, RotateCcw, ShieldAlert, ShieldCheck, Trash2 } from "lucide-react";
import { archiveRun, deleteRun, getRunDetail, getRunSeries, restoreRun, setRunVisibility } from "../../api/results";
import { getRunIntegrity } from "../../api/integrity";
import { StatusBadge } from "../../components/StatusBadge";
import { resultsPath } from "../../lib/paths";
import { Breadcrumb } from "../../components/Breadcrumb";
import { RegressionTestsBrowser, TEST_PARAM } from "./RegressionTestsBrowser";
import { Fact, FactGrid } from "./RunFacts";
import { UnitTestsPanel } from "./UnitTestsPanel";
import { SkipConfigInfo } from "./SkippedTests";
import { duration, fmtDate } from "./runDetailFormat";
import { SlurmResourceSummary, addSlurmRerunParams } from "./SlurmResourceSummary";

export { duration, fmtDate };

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

  const { data: integrity } = useQuery({
    queryKey: ["run-integrity", branch, arch, runId],
    queryFn: () => getRunIntegrity(branch!, arch!, runId!),
    enabled: !!branch && !!arch && !!runId,
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteRun(branch!, arch!, runId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runs", branch, arch] });
      queryClient.invalidateQueries({ queryKey: ["branches"] });
      queryClient.invalidateQueries({ queryKey: ["all-runs"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-stats"] });
      queryClient.invalidateQueries({ queryKey: ["archive-summary"] });
      navigate(resultsPath(branch!, arch!));
    },
  });

  const [archiveNotice, setArchiveNotice] = useState<string | null>(null);
  const archiveMutation = useMutation({
    mutationFn: (archived: boolean) => archiveRun(branch!, arch!, runId!, archived),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["run-detail", branch, arch, runId] });
      queryClient.invalidateQueries({ queryKey: ["all-runs"] });
      queryClient.invalidateQueries({ queryKey: ["runs", branch, arch] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-stats"] });
      queryClient.invalidateQueries({ queryKey: ["branches"] });
      queryClient.invalidateQueries({ queryKey: ["archive-summary"] });
      if (result.failed_move.length > 0) {
        setArchiveNotice("Could not move this run between storage roots.");
      } else if (result.skipped_active.length > 0) {
        setArchiveNotice("This run is currently active and was skipped.");
      } else if (result.not_found.length > 0) {
        setArchiveNotice("This run is missing from the index.");
      } else {
        setArchiveNotice(null);
      }
      if (
        result.failed_move.length > 0 ||
        result.skipped_active.length > 0 ||
        result.not_found.length > 0
      ) {
        setTimeout(() => setArchiveNotice(null), 5000);
      }
    },
  });

  const [restoreNotice, setRestoreNotice] = useState<string | null>(null);
  const restoreMutation = useMutation({
    mutationFn: () => restoreRun(branch!, arch!, runId!),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["run-detail", branch, arch, runId] });
      queryClient.invalidateQueries({ queryKey: ["all-runs"] });
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-stats"] });
      queryClient.invalidateQueries({ queryKey: ["branches"] });
      queryClient.invalidateQueries({ queryKey: ["archive-summary"] });
      if (result.failed_move.length > 0) {
        setRestoreNotice("Could not move this run from archive storage.");
        setTimeout(() => setRestoreNotice(null), 5000);
      } else {
        setRestoreNotice(null);
      }
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

  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmArchive, setConfirmArchive] = useState(false);

  if (isLoading) return <div className="p-8 text-muted">Loading…</div>;
  if (error || !data)
    return <div className="p-8 text-failed">Failed to load run data.</div>;

  const { meta, unit, regression } = data;
  const unitSkipped = meta.unit_tests_skipped ?? 0;
  const regressionSkipped = meta.regression_skipped ?? 0;
  const runPath = `runs/${branch}/${arch}/${runId}`;
  const listParams = new URLSearchParams(searchParams);
  listParams.delete(TEST_PARAM);
  const qs = listParams.toString();
  const listHref = `${resultsPath(branch!, arch!)}${qs ? `?${qs}` : ""}`;
  const regtestLabel = meta.regtest_branch ?? "\u2014";
  const isColdStored = meta.archived && data.archived_on_cold_storage;
  const executionSnapshot = meta.execution_snapshot ?? null;
  const buildLabel = executionSnapshot?.build?.name ?? meta.arch;
  const rerunParams = new URLSearchParams({
    branch: meta.branch,
    regtests_branch: meta.regtest_branch ?? "master",
    arch: meta.arch,
    connection_name:
      meta.connection_name && meta.connection_name !== "local"
        ? meta.connection_name
        : "local",
    skip_unit: String(meta.run_options?.skip_unit ?? false),
    skip_regression: String(meta.run_options?.skip_regression ?? false),
    clean_build: String(meta.run_options?.clean_build ?? false),
    mpi_ranks: String(meta.run_options?.mpi_ranks ?? 1),
    opalx_info_level: String(meta.run_options?.opalx_info_level ?? 2),
    rerun_branch: meta.branch,
    rerun_arch: meta.arch,
    rerun_id: meta.run_id,
  });
  if (meta.run_options?.series_max_points != null) {
    rerunParams.set("series_max_points", String(meta.run_options.series_max_points));
  }
  const slurmResources = meta.run_options?.slurm_resources ?? null;
  if (executionSnapshot) {
    if (executionSnapshot.build?.id) {
      rerunParams.set("build_preset_id", executionSnapshot.build.id);
    }
    if (executionSnapshot.machine?.id) {
      rerunParams.set("machine_preset_id", executionSnapshot.machine.id);
    }
    rerunParams.set("env_preset_id", executionSnapshot.environment?.id ?? "");
    rerunParams.set("slurm_preset_id", executionSnapshot.slurm?.id ?? "");
  }
  addSlurmRerunParams(rerunParams, slurmResources);
  if (meta.run_options?.skip_config?.id) {
    rerunParams.set("skip_config_id", meta.run_options.skip_config.id);
  }

  const actionClass =
    "inline-flex items-center gap-1.5 rounded border border-border px-2.5 py-1 text-sm text-muted transition-colors hover:text-accent disabled:opacity-50";

  return (
    <div className="mx-auto w-full max-w-[120rem] space-y-5 p-4 sm:p-6">
      <Breadcrumb
        crumbs={[
          {
            label: `${branch} \u00b7 ${buildLabel}`,
            to: listHref,
            title:
              buildLabel === arch
                ? `All runs on ${branch} / build preset ${buildLabel}`
                : `All runs on ${branch} / build preset ${buildLabel} (${arch})`,
          },
          {
            label: `regtests=${regtestLabel}`,
            title: `Regression-tests branch for this run`,
          },
          { label: runId ?? "", title: "Run ID" },
        ]}
      />
      <header className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <div className="min-w-0 space-y-1.5">
          <h1 className="text-xl font-semibold text-fg">
            <span className="text-muted font-normal">Run </span>
            <span className="font-mono">{meta.run_id}</span>
          </h1>
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={meta.status} size="md" />
            {integrity && (
              <span
                className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border ${
                  integrity.status === "ok"
                    ? "border-passed/40 text-passed bg-passed/10"
                    : integrity.status === "warning"
                      ? "border-broken/40 text-broken bg-broken/10"
                      : "border-failed/40 text-failed bg-failed/10"
                }`}
                title={
                  integrity.issues.length === 0
                    ? "Artifacts verified"
                    : integrity.issues.map((i) => `${i.code}: ${i.path ?? i.message}`).join("; ")
                }
              >
                {integrity.status === "ok" ? (
                  <ShieldCheck size={10} aria-hidden="true" />
                ) : (
                  <ShieldAlert size={10} aria-hidden="true" />
                )}
                {integrity.status === "ok" ? "Artifacts OK" : `Artifacts ${integrity.status}`}
              </span>
            )}
            {meta.public ? (
              <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border border-accent/40 text-accent bg-accent/10">
                <Globe2 size={10} aria-hidden="true" />
                Public
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border border-border text-muted">
                <Lock size={10} aria-hidden="true" />
                Private
              </span>
            )}
          </div>
        </div>
        <div className="ml-auto">
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
          <div className="flex flex-wrap items-center gap-2">
            <Link
              to={`/trigger?${rerunParams.toString()}`}
              className={actionClass}
              title="Start a new run with this run's settings"
            >
              <RotateCcw size={14} aria-hidden="true" /> Run again
            </Link>
            <button
              onClick={() => publishMutation.mutate(!meta.public)}
              disabled={publishMutation.isPending}
              className={actionClass}
              title={meta.public ? "Make this run private" : "Publish this run"}
            >
              {meta.public ? <Lock size={14} aria-hidden="true" /> : <Globe2 size={14} aria-hidden="true" />}
              {publishMutation.isPending
                ? "Saving\u2026"
                : meta.public
                ? "Unpublish"
                : "Publish"}
            </button>
            {!isColdStored && (
              <button
                onClick={() => setConfirmArchive(true)}
                className={actionClass}
                title={meta.archived ? "Unarchive run" : "Archive run"}
              >
                <Archive size={14} aria-hidden="true" /> {meta.archived ? "Unarchive run" : "Archive run"}
              </button>
            )}
            <button
              onClick={() => setConfirmDelete(true)}
              className={`${actionClass} hover:!text-failed`}
              title="Delete run"
            >
              <Trash2 size={14} aria-hidden="true" /> Delete run
            </button>
          </div>
        )}
        </div>
      </header>

      {publishNotice && (
        <div role="status" className="bg-accent/10 border border-accent/40 text-accent text-sm rounded-lg px-4 py-2">
          {publishNotice}
        </div>
      )}

      {archiveNotice && (
        <div role="status" className="bg-failed/10 border border-failed/40 text-failed text-sm rounded-lg px-4 py-2">
          {archiveNotice}
        </div>
      )}

      {isColdStored && (
        <div className="bg-surface border border-accent/40 rounded-xl p-5 flex flex-col sm:flex-row sm:items-center gap-4">
          <div className="flex items-start gap-3 flex-1">
            <Archive size={18} className="text-accent mt-0.5 shrink-0" />
            <div>
              <h2 className="text-fg font-medium">Cold storage</h2>
              <p className="text-muted text-sm mt-1">
                This run lives on archive storage. De-archive to view its plots, logs, and per-test details.
              </p>
              {(restoreNotice || restoreMutation.isError) && (
                <p className="text-failed text-sm mt-2">
                  {restoreNotice ?? "Could not restore this run."}
                </p>
              )}
            </div>
          </div>
          <button
            onClick={() => restoreMutation.mutate()}
            disabled={restoreMutation.isPending}
            className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded border border-accent/40 bg-accent/10 text-accent text-sm hover:bg-accent/20 transition-colors disabled:opacity-50"
          >
            <Archive size={14} />
            {restoreMutation.isPending ? "Restoring…" : "De-archive to view"}
          </button>
        </div>
      )}

      <section aria-label="Run details" className="bg-surface border border-border rounded-xl p-4 sm:p-5">
        <FactGrid>
          <Fact label="OPALX Branch">{meta.branch}</Fact>
          <Fact label="Tests Branch">
            <span className="font-mono">{meta.regtest_branch ?? "—"}</span>
          </Fact>
          <Fact label="Build / Executed On">
            <span className="font-mono">
              {executionSnapshot?.build?.name ?? meta.arch} /{" "}
              {executionSnapshot?.machine?.name ??
                (meta.connection_name && meta.connection_name !== "local"
                  ? meta.connection_name
                  : "local")}
            </span>
          </Fact>
          <Fact label="Duration">{duration(meta.started_at, meta.finished_at)}</Fact>
          <Fact label="Started">{fmtDate(meta.started_at)}</Fact>
          <Fact label="Triggered By">
            {meta.triggered_by ? (
              <Link
                to={`/activity?user=${encodeURIComponent(meta.triggered_by)}`}
                className="text-accent hover:underline font-mono"
                title={`Show all runs triggered by ${meta.triggered_by}`}
              >
                {meta.triggered_by}
              </Link>
            ) : (
              <span className="font-mono">—</span>
            )}
          </Fact>
          <Fact label="Commits">
            <span className="block text-xs">
              <span className="text-muted">opalx: </span>
              <CommitLink hash={meta.opalx_commit} base={OPALX_COMMIT_BASE} />
            </span>
            <span className="block text-xs">
              <span className="text-muted">tests: </span>
              <CommitLink hash={meta.tests_repo_commit} base={REGTESTS_COMMIT_BASE} />
            </span>
          </Fact>
          <Fact label="Regression Runtime">
            {meta.run_options?.mpi_ranks ?? 1} rank
            {(meta.run_options?.mpi_ranks ?? 1) === 1 ? "" : "s"} / info{" "}
            {meta.run_options?.opalx_info_level ?? 2}
            {meta.run_options?.series_max_points != null && (
              <>
                {" "}/ {meta.run_options.series_max_points === 0
                  ? "all plot points"
                  : `${meta.run_options.series_max_points} plot points`}
              </>
            )}
          </Fact>
          <SlurmResourceSummary resources={slurmResources} />
          {executionSnapshot && (
            <Fact label="Execution Presets">
              {executionSnapshot.build?.name ?? meta.arch}
              {executionSnapshot.machine ? ` / ${executionSnapshot.machine.name}` : ""}
              {executionSnapshot.environment
                ? ` / ${executionSnapshot.environment.name}`
                : ""}
              {executionSnapshot.slurm ? ` / ${executionSnapshot.slurm.name}` : ""}
            </Fact>
          )}
          {!isColdStored && (
            <Fact label="Pipeline Log">
              <a
                href={`/data/${runPath}/logs/pipeline.log`}
                target="_blank"
                rel="noopener"
                className="inline-flex items-center gap-1 text-accent hover:underline"
              >
                <FileText size={12} aria-hidden="true" /> pipeline.log
                <span className="sr-only"> (opens in a new tab)</span>
              </a>
            </Fact>
          )}
          {meta.run_options?.skip_config && (
            <SkipConfigInfo snapshot={meta.run_options.skip_config} />
          )}
          {(meta.run_options?.custom_cmake_args?.length ?? 0) > 0 && (
            <Fact label="Custom CMake Args" wide>
              <pre className="mt-1 rounded-md border border-border bg-bg px-3 py-2 text-xs text-fg overflow-x-auto">
                {meta.run_options.custom_cmake_args.join("\n")}
              </pre>
            </Fact>
          )}
        </FactGrid>
      </section>

      {/* Unit tests */}
      {!isColdStored && unit.tests.length > 0 && (
        <UnitTestsPanel
          tests={unit.tests}
          summary={
            <>
              {meta.unit_tests_total - meta.unit_tests_failed}/{meta.unit_tests_total} passed
              {meta.unit_tests_failed > 0 && (
                <span className="text-failed ml-2">{meta.unit_tests_failed} failed</span>
              )}
              {unitSkipped > 0 && (
                <span className="text-muted ml-2">· {unitSkipped} skipped</span>
              )}
            </>
          }
        />
      )}

      {/* Regression tests */}
      {!isColdStored && regression.simulations.length > 0 && (
        <section aria-labelledby="regression-heading" className="space-y-3">
          <h2 id="regression-heading" className="text-fg font-medium">
            Regression Tests
            <span className="text-muted font-normal text-sm ml-2">
              {meta.regression_passed}/{meta.regression_total} passed
              {meta.regression_failed > 0 && (
                <span className="text-failed ml-1">· {meta.regression_failed} failed</span>
              )}
              {meta.regression_broken > 0 && (
                <span className="text-broken ml-1">· {meta.regression_broken} broken</span>
              )}
              {regressionSkipped > 0 && (
                <span className="text-muted ml-1">· {regressionSkipped} skipped</span>
              )}
            </span>
          </h2>
          <RegressionTestsBrowser
            simulations={regression.simulations}
            runPath={runPath}
            series={{
              queryKey: ["run-series", branch, arch, runId],
              load: () => getRunSeries(branch!, arch!, runId!),
            }}
          />
        </section>
      )}
    </div>
  );
}
