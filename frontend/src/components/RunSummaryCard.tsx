import { Clock, Cpu, FlaskConical, GitBranch, Globe2, TestTube2, User } from "lucide-react";
import { Link } from "react-router-dom";
import type { RunIndexEntry } from "../api/results";
import { StatusBadge } from "./StatusBadge";

function fmtDate(d: string | null) {
  if (!d) return "\u2014";
  return new Date(d).toLocaleString();
}

function duration(start: string, end: string | null) {
  if (!end) return "\u2014";
  const s = Math.floor(
    (new Date(end).getTime() - new Date(start).getTime()) / 1000
  );
  const m = Math.floor(s / 60);
  return `${m}m ${(s % 60).toString().padStart(2, "0")}s`;
}

interface RunSummaryCardProps {
  run: RunIndexEntry;
  to: string;
  copiedPublicLink?: boolean;
  onCopyPublicLink?: (run: RunIndexEntry) => void;
  userLink?: string;
}

export function RunSummaryCard({
  run,
  to,
  copiedPublicLink = false,
  onCopyPublicLink,
  userLink,
}: RunSummaryCardProps) {
  const connectionSuffix =
    run.connection_name && run.connection_name !== "local"
      ? ` / ${run.connection_name}`
      : "";

  return (
    <div className="bg-surface border border-border rounded-xl overflow-hidden">
      <Link to={to} className="block p-4">
        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="min-w-0 space-y-1">
            <p className="flex items-center gap-1.5 text-fg font-medium text-sm min-w-0">
              <GitBranch size={12} className="text-muted shrink-0" />
              <span className="truncate" title={run.branch}>
                {run.branch}
              </span>
            </p>
            <p className="flex items-center gap-1.5 text-muted text-xs min-w-0">
              <TestTube2 size={11} className="shrink-0" />
              <span className="truncate" title={run.regtest_branch ?? undefined}>
                regtests: {run.regtest_branch ?? "\u2014"}
              </span>
            </p>
          </div>
          <StatusBadge status={run.status} />
        </div>

        <div className="space-y-1.5 text-xs text-muted">
          <p className="flex items-center gap-1.5 min-w-0">
            <Cpu size={11} className="shrink-0" />
            <span className="truncate" title={`${run.arch}${connectionSuffix}`}>
              {run.arch}{connectionSuffix}
            </span>
          </p>
          <p className="flex items-center gap-1.5 min-w-0">
            <User size={11} className="shrink-0" />
            <span className="truncate" title={run.triggered_by ?? undefined}>
              {run.triggered_by ?? "\u2014"}
            </span>
          </p>
          <p className="flex items-center gap-1.5">
            <Clock size={11} className="shrink-0" />
            <span>{fmtDate(run.started_at)}</span>
            <span className="text-muted/70">·</span>
            <span>{duration(run.started_at, run.finished_at)}</span>
          </p>
          <p>
            Unit: {run.unit_tests_total - run.unit_tests_failed}/
            {run.unit_tests_total} passed
          </p>
          <p className="flex items-start gap-1.5">
            <FlaskConical size={11} className="mt-0.5 shrink-0" />
            <span>
              Regression: <span className="text-passed">{run.regression_passed}</span> /{" "}
              {run.regression_total}
              {run.regression_failed > 0 && (
                <span className="text-failed ml-1">
                  ({run.regression_failed} fail)
                </span>
              )}
              {run.regression_broken > 0 && (
                <span className="text-broken ml-1">
                  ({run.regression_broken} broken)
                </span>
              )}
            </span>
          </p>
        </div>
      </Link>

      {(userLink || (run.public && onCopyPublicLink)) && (
        <div className="border-t border-border px-4 py-2 flex flex-wrap items-center gap-3 text-xs">
          {userLink && run.triggered_by && (
            <Link to={userLink} className="text-accent hover:underline">
              Filter by {run.triggered_by}
            </Link>
          )}
          {run.public && onCopyPublicLink && (
            <button
              type="button"
              onClick={() => onCopyPublicLink(run)}
              className="ml-auto flex items-center gap-1 text-accent hover:brightness-125 transition-all"
              title={copiedPublicLink ? "Copied!" : "Copy public link"}
            >
              <Globe2 size={13} />
              {copiedPublicLink ? "Copied!" : "Copy public link"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
