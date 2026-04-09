import { Link } from "react-router-dom";
import { Clock, Cpu, FlaskConical } from "lucide-react";
import type { RunIndexEntry } from "../api/results";
import { StatusBadge } from "./StatusBadge";

function fmtDate(d: string | null) {
  if (!d) return "\u2014";
  return new Date(d).toLocaleString();
}

interface LatestCardProps {
  branch: string;
  arch: string;
  run: RunIndexEntry | undefined;
  /** Show a selection checkbox in the top-left corner. */
  showCheckbox?: boolean;
  /** Whether the checkbox is checked. */
  selected?: boolean;
  /** Called when the checkbox is toggled. */
  onToggleSelect?: () => void;
}

/**
 * Card showing the latest run for a single branch+arch combination.
 *
 * The whole card is a link into the run detail (or run list, if no run
 * exists). When `showCheckbox` is true, a checkbox is rendered in the top-
 * left; clicks on the checkbox don't navigate (they only toggle selection).
 */
export function LatestCard({
  branch,
  arch,
  run,
  showCheckbox = false,
  selected = false,
  onToggleSelect,
}: LatestCardProps) {
  const href = run
    ? `/results/${branch}/${arch}/${run.run_id}`
    : `/results/${branch}/${arch}`;

  return (
    <div
      className={`relative bg-surface border rounded-xl transition-colors ${
        selected
          ? "border-accent/70 ring-1 ring-accent/30"
          : "border-border hover:border-accent/40"
      }`}
    >
      {showCheckbox && (
        <label
          className="absolute top-3 left-3 z-10 flex items-center cursor-pointer"
          onClick={(e) => e.stopPropagation()}
        >
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggleSelect}
            className="w-4 h-4 rounded border-border accent-accent cursor-pointer"
          />
        </label>
      )}
      <Link to={href} className={`block p-5 ${showCheckbox ? "pl-10" : ""}`}>
        <div className="flex items-start justify-between mb-3">
          <p className="text-muted text-xs flex items-center gap-1">
            <Cpu size={11} />
            {arch}
          </p>
          {run ? (
            <StatusBadge status={run.status} />
          ) : (
            <StatusBadge status="unknown" />
          )}
        </div>
        {run ? (
          <div className="text-xs text-muted space-y-1">
            <p className="flex items-center gap-1">
              <Clock size={11} />
              {fmtDate(run.started_at)}
            </p>
            <p className="flex items-center gap-1">
              <FlaskConical size={11} />
              Regression: {run.regression_passed}/{run.regression_total} passed
              {run.regression_failed > 0 && (
                <span className="text-failed">
                  , {run.regression_failed} failed
                </span>
              )}
              {run.regression_broken > 0 && (
                <span className="text-broken">
                  , {run.regression_broken} broken
                </span>
              )}
            </p>
            <p>
              Unit: {run.unit_tests_total - run.unit_tests_failed}/
              {run.unit_tests_total} passed
            </p>
          </div>
        ) : (
          <p className="text-xs text-muted">No runs yet.</p>
        )}
      </Link>
    </div>
  );
}
