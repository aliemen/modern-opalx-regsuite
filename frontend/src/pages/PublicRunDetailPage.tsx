import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Globe2 } from "lucide-react";
import { getPublicRunDetail } from "../api/public";
import { StatusBadge } from "../components/StatusBadge";
import {
  CommitLink,
  OPALX_COMMIT_BASE,
  REGTESTS_COMMIT_BASE,
  SimCard,
  duration,
  fmtDate,
} from "./results/RunDetailPage";

/**
 * Read-only public run detail. Mounted OUTSIDE the auth fence so anonymous
 * visitors can see runs that developers have explicitly published. Re-uses
 * the visual layout of the private RunDetailPage (meta card + unit table +
 * SimCard list) without the archive / delete / publish action bar and
 * without the direct pipeline.log link.
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

  if (isLoading) return <div className="p-8 text-muted">Loading\u2026</div>;
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
  const runPath = `runs/${branch}/${arch}/${runId}`;

  return (
    <div className="min-h-screen bg-bg">
      <div className="p-6 max-w-5xl mx-auto space-y-6">
        <div className="flex items-center justify-between">
          <Link
            to="/login"
            className="flex items-center gap-1.5 text-muted hover:text-fg text-sm transition-colors"
          >
            <ArrowLeft size={14} /> Back to public runs
          </Link>
          <span className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border border-accent/40 text-accent bg-accent/10">
            <Globe2 size={12} />
            Public
          </span>
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
            <p className="text-fg">
              {meta.branch} / {meta.arch}
            </p>
          </div>
          <div className="space-y-1">
            <p className="text-muted text-xs">Duration</p>
            <p className="text-fg">
              {duration(meta.started_at, meta.finished_at)}
            </p>
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
            <p className="text-fg font-mono text-sm">
              {meta.triggered_by ?? "\u2014"}
            </p>
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
                <CommitLink
                  hash={meta.tests_repo_commit}
                  base={REGTESTS_COMMIT_BASE}
                />
              </p>
            </div>
          </div>
        </div>

        {/* Unit tests summary — public surface shows counts only, not per-test names. */}
        {meta.unit_tests_total > 0 && (
          <div className="bg-surface border border-border rounded-xl p-5">
            <h2 className="text-fg font-medium mb-1">Unit Tests</h2>
            <p className="text-muted text-sm">
              {meta.unit_tests_total - meta.unit_tests_failed}/
              {meta.unit_tests_total} passed
              {meta.unit_tests_failed > 0 && (
                <span className="text-failed ml-2">
                  {meta.unit_tests_failed} failed
                </span>
              )}
            </p>
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
                  <span className="text-failed ml-1">
                    · {meta.regression_failed} failed
                  </span>
                )}
                {meta.regression_broken > 0 && (
                  <span className="text-broken ml-1">
                    · {meta.regression_broken} broken
                  </span>
                )}
              </span>
            </h2>
            {regression.simulations.map((sim) => (
              <SimCard key={sim.name} sim={sim} runPath={runPath} />
            ))}
          </div>
        )}

      </div>
    </div>
  );
}
