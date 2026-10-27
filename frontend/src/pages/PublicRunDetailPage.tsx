import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Globe2 } from "lucide-react";
import { getPublicRunDetail, getPublicRunSeries } from "../api/public";
import { StatusBadge } from "../components/StatusBadge";
import {
  CommitLink,
  OPALX_COMMIT_BASE,
  REGTESTS_COMMIT_BASE,
  duration,
  fmtDate,
} from "./results/RunDetailPage";
import { RegressionTestsBrowser } from "./results/RegressionTestsBrowser";
import { Fact, FactGrid } from "./results/RunFacts";
import { SkipConfigInfo } from "./results/SkippedTests";

/**
 * Read-only public run detail. Mounted OUTSIDE the auth fence so anonymous
 * visitors can see runs that developers have explicitly published. Re-uses
 * the visual layout of the private RunDetailPage (run facts + unit summary +
 * regression test browser) without the archive / delete / publish action bar
 * and without the direct pipeline.log link.
 */
export function PublicRunDetailPage() {
  const { branch, arch, runId } = useParams<{
    branch: string;
    arch: string;
    runId: string;
  }>();

  const { data, isLoading, error } = useQuery({
    queryKey: ["public-run-detail", branch, arch, runId],
    queryFn: () => getPublicRunDetail(branch!, arch!, runId!),
    enabled: !!branch && !!arch && !!runId,
  });

  if (isLoading) return <div className="p-8 text-muted">Loading…</div>;
  if (error || !data) {
    return (
      <div className="min-h-screen bg-bg p-8">
        <div className="max-w-2xl mx-auto">
          <Link
            to="/login"
            className="flex items-center gap-1.5 text-muted hover:text-fg text-sm transition-colors mb-6"
          >
            <ArrowLeft size={14} /> Back to public runs
          </Link>
          <div className="bg-surface border border-border rounded-xl p-8 text-center">
            <h2 className="text-fg text-lg font-semibold mb-2">
              Run not available
            </h2>
            <p className="text-muted text-sm">
              This run is not published, has been unpublished, or does not
              exist.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const { meta, regression } = data;
  const unitSkipped = meta.unit_tests_skipped ?? 0;
  const regressionSkipped = meta.regression_skipped ?? 0;
  const runPath = `runs/${branch}/${arch}/${runId}`;

  return (
    <div className="min-h-screen bg-bg">
      <div className="mx-auto w-full max-w-[120rem] space-y-5 p-4 sm:p-6">
        <div className="flex items-center justify-between">
          <Link
            to="/login"
            className="flex items-center gap-1.5 text-muted hover:text-fg text-sm transition-colors"
          >
            <ArrowLeft size={14} aria-hidden="true" /> Back to public runs
          </Link>
          <span className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border border-accent/40 text-accent bg-accent/10">
            <Globe2 size={12} aria-hidden="true" />
            Public
          </span>
        </div>

        <header className="space-y-1.5">
          <h1 className="text-xl font-semibold text-fg">
            <span className="text-muted font-normal">Run </span>
            <span className="font-mono">{meta.run_id}</span>
          </h1>
          <StatusBadge status={meta.status} size="md" />
        </header>

        <section aria-label="Run details" className="bg-surface border border-border rounded-xl p-4 sm:p-5">
          <FactGrid>
            <Fact label="OPALX Branch">{meta.branch}</Fact>
            <Fact label="Tests Branch">
              <span className="font-mono">{meta.regtest_branch ?? "—"}</span>
            </Fact>
            <Fact label="Build / Executed On">
              <span className="font-mono">
                {meta.execution_snapshot?.build?.name ?? meta.arch} /{" "}
                {meta.execution_snapshot?.machine?.name ??
                  (meta.connection_name && meta.connection_name !== "local"
                    ? meta.connection_name
                    : "local")}
              </span>
            </Fact>
            <Fact label="Duration">{duration(meta.started_at, meta.finished_at)}</Fact>
            <Fact label="Started">{fmtDate(meta.started_at)}</Fact>
            <Fact label="Triggered By">
              <span className="font-mono">{meta.triggered_by ?? "\u2014"}</span>
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
            {meta.run_options?.skip_config && (
              <SkipConfigInfo snapshot={meta.run_options.skip_config} />
            )}
          </FactGrid>
        </section>

        {/* Unit tests summary — public surface shows counts only, not per-test names. */}
        {(meta.unit_tests_total > 0 || unitSkipped > 0) && (
          <section className="bg-surface border border-border rounded-xl px-5 py-3 flex flex-wrap items-baseline gap-x-3">
            <h2 className="text-fg font-medium">Unit Tests</h2>
            <p className="text-muted text-sm">
              {meta.unit_tests_total - meta.unit_tests_failed}/
              {meta.unit_tests_total} passed
              {meta.unit_tests_failed > 0 && (
                <span className="text-failed ml-2">
                  {meta.unit_tests_failed} failed
                </span>
              )}
              {unitSkipped > 0 && (
                <span className="text-muted ml-2">· {unitSkipped} skipped</span>
              )}
            </p>
          </section>
        )}

        {/* Regression tests */}
        {regression.simulations.length > 0 && (
          <section aria-labelledby="regression-heading" className="space-y-3">
            <h2 id="regression-heading" className="text-fg font-medium">
              Regression Tests
              <span className="text-muted font-normal text-sm ml-2">
                {meta.regression_passed}/{meta.regression_total} passed
                {meta.regression_failed > 0 && (
                  <span className="text-failed ml-1">
                    · {meta.regression_failed} failed
                  </span>
                )}
                {meta.regression_broken > 0 && (
                  <span className="text-broken ml-1">
                    · {meta.regression_broken} broken
                  </span>
                )}
                {regressionSkipped > 0 && (
                  <span className="text-muted ml-1">
                    · {regressionSkipped} skipped
                  </span>
                )}
              </span>
            </h2>
            <RegressionTestsBrowser
              simulations={regression.simulations}
              runPath={runPath}
              series={{
                queryKey: ["public-run-series", branch, arch, runId],
                load: () => getPublicRunSeries(branch!, arch!, runId!),
              }}
            />
          </section>
        )}
      </div>
    </div>
  );
}
