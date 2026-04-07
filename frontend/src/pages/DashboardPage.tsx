import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Radio } from "lucide-react";
import { getBranches } from "../api/results";
import { getCurrentRun } from "../api/runs";
import { BranchSection } from "../components/BranchSection";
import { TrendsPanel } from "../components/TrendsPanel";

export function DashboardPage() {
  const { data: branches, isLoading } = useQuery({
    queryKey: ["branches"],
    queryFn: getBranches,
    refetchInterval: 60_000,
  });

  const { data: activeRun } = useQuery({
    queryKey: ["current-run"],
    queryFn: getCurrentRun,
    refetchInterval: 5000,
  });

  if (isLoading) {
    return <div className="p-8 text-muted">Loading\u2026</div>;
  }

  const entries = Object.entries(branches ?? {});

  // master always first, then alphabetical
  entries.sort(([a], [b]) => {
    if (a === "master") return -1;
    if (b === "master") return 1;
    return a.localeCompare(b);
  });

  const masterArchs = branches?.["master"] ?? [];

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {activeRun && activeRun.status === "running" ? (
        <Link
          to="/live"
          className="flex items-center gap-3 bg-accent/10 border border-accent/30 rounded-xl px-5 py-3 mb-6 text-accent text-sm hover:bg-accent/20 transition-colors"
        >
          <span className="w-2 h-2 rounded-full bg-accent animate-ping inline-block" />
          Run in progress — {activeRun.branch} / {activeRun.arch} — phase:{" "}
          {activeRun.phase}
          <span className="ml-auto text-xs underline">View live output →</span>
        </Link>
      ) : (
        <Link
          to="/live"
          className="flex items-center gap-2 text-muted hover:text-fg text-sm mb-6 w-fit transition-colors"
        >
          <Radio size={13} /> Latest run log
        </Link>
      )}

      <h1 className="text-fg text-2xl font-semibold mb-6">Dashboard</h1>

      {entries.length === 0 ? (
        <div className="text-muted text-sm">
          No results yet.{" "}
          <Link to="/trigger" className="text-accent hover:underline">
            Start a run
          </Link>{" "}
          to get started.
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
          {/* Left: branch accordion */}
          <div className="lg:col-span-3 space-y-3">
            {entries.map(([branch, archs], i) => (
              <BranchSection
                key={branch}
                branch={branch}
                archs={archs}
                defaultOpen={i === 0}
              />
            ))}
          </div>

          {/* Right: trends chart */}
          {masterArchs.length > 0 && (
            <div className="lg:col-span-2">
              <TrendsPanel archs={masterArchs} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
