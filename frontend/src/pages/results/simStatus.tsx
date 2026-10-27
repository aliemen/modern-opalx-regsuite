/* eslint-disable react-refresh/only-export-components */
import { CircleCheck, CircleHelp, CircleMinus, CircleX, TriangleAlert, Zap, type LucideIcon } from "lucide-react";
import type { RegressionSimulation } from "../../api/results";

const ICONS: Record<string, { Icon: LucideIcon; className: string }> = {
  passed: { Icon: CircleCheck, className: "text-passed" },
  failed: { Icon: CircleX, className: "text-failed" },
  broken: { Icon: TriangleAlert, className: "text-broken" },
  crashed: { Icon: Zap, className: "text-crashed" },
  skipped: { Icon: CircleMinus, className: "text-muted" },
};

/** Border colour for anything that did not pass. */
export const PROBLEM_BORDER: Record<string, string> = {
  failed: "border-failed/60",
  broken: "border-broken/60",
  crashed: "border-crashed/60",
};

/** Decorative status icon; its shape, not only its colour, tells the states apart. */
export function StatusIcon({ status, size = 14 }: { status: string | null; size?: number }) {
  const { Icon, className } = ICONS[status ?? ""] ?? { Icon: CircleHelp, className: "text-muted" };
  return <Icon size={size} className={`shrink-0 ${className}`} aria-hidden="true" />;
}

export function isProblem(state: string | null): boolean {
  return state !== "passed" && state !== "skipped";
}

export function checkCounts(sim: RegressionSimulation) {
  const metrics = (sim.containers ?? []).flatMap((c) => c.metrics);
  const count = (state: string) => metrics.filter((m) => m.state === state).length;
  return {
    total: metrics.length,
    passed: count("passed"),
    failed: count("failed"),
    broken: count("broken"),
    crashed: count("crashed"),
  };
}
