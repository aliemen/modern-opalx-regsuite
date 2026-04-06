import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Play } from "lucide-react";
import {
  getCurrentRun,
  getOpalxBranches,
  getRegtestsBranches,
  triggerRun,
} from "../api/runs";

export function TriggerPage() {
  const navigate = useNavigate();

  const [opalxBranch, setOpalxBranch] = useState("master");
  const [regtestsBranch, setRegtestsBranch] = useState("master");
  const [arch, setArch] = useState("cpu-serial");
  const [skipUnit, setSkipUnit] = useState(false);
  const [skipRegression, setSkipRegression] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const {
    data: opalxBranches,
    isLoading: loadingOpalx,
    refetch: refetchOpalx,
    isFetching: fetchingOpalx,
  } = useQuery({ queryKey: ["opalx-branches"], queryFn: getOpalxBranches });

  const {
    data: regtestsBranches,
    isLoading: loadingRegtests,
    refetch: refetchRegtests,
    isFetching: fetchingRegtests,
  } = useQuery({ queryKey: ["regtests-branches"], queryFn: getRegtestsBranches });

  const { data: activeRun } = useQuery({
    queryKey: ["current-run"],
    queryFn: getCurrentRun,
    refetchInterval: 5000,
  });

  const isRunning = activeRun?.status === "running";

  // If a run is already in progress, go straight to the live view.
  useEffect(() => {
    if (isRunning) navigate("/live", { replace: true });
  }, [isRunning, navigate]);

  async function handleStart() {
    setError(null);
    try {
      await triggerRun({
        branch: opalxBranch,
        arch,
        regtests_branch: regtestsBranch,
        skip_unit: skipUnit,
        skip_regression: skipRegression,
      });
      navigate("/live");
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Failed to start run.";
      setError(msg);
    }
  }

  return (
    <div className="p-6 max-w-xl mx-auto">
      <h1 className="text-white text-2xl font-semibold mb-6">Start a Run</h1>

      <div className="bg-surface border border-border rounded-xl p-6 flex flex-col gap-5">
        {/* OPALX branch */}
        <div>
          <label className="block text-sm text-muted mb-1">OPALX branch</label>
          <div className="flex gap-2">
            <select
              value={opalxBranch}
              onChange={(e) => setOpalxBranch(e.target.value)}
              className="flex-1 bg-bg border border-border rounded-md px-3 py-2 text-white text-sm focus:outline-none focus:border-accent"
              disabled={loadingOpalx}
            >
              {(opalxBranches ?? ["master"]).map((b) => (
                <option key={b}>{b}</option>
              ))}
            </select>
            <button
              onClick={() => refetchOpalx()}
              disabled={fetchingOpalx}
              className="p-2 text-muted hover:text-white border border-border rounded-md transition disabled:opacity-50"
              title="Refresh branches"
            >
              <RefreshCw size={15} className={fetchingOpalx ? "animate-spin" : ""} />
            </button>
          </div>
        </div>

        {/* Regression tests branch */}
        <div>
          <label className="block text-sm text-muted mb-1">Regression-tests branch</label>
          <div className="flex gap-2">
            <select
              value={regtestsBranch}
              onChange={(e) => setRegtestsBranch(e.target.value)}
              className="flex-1 bg-bg border border-border rounded-md px-3 py-2 text-white text-sm focus:outline-none focus:border-accent"
              disabled={loadingRegtests}
            >
              {(regtestsBranches ?? ["master"]).map((b) => (
                <option key={b}>{b}</option>
              ))}
            </select>
            <button
              onClick={() => refetchRegtests()}
              disabled={fetchingRegtests}
              className="p-2 text-muted hover:text-white border border-border rounded-md transition disabled:opacity-50"
              title="Refresh branches"
            >
              <RefreshCw size={15} className={fetchingRegtests ? "animate-spin" : ""} />
            </button>
          </div>
        </div>

        {/* Architecture */}
        <div>
          <label className="block text-sm text-muted mb-1">Architecture</label>
          <input
            type="text"
            value={arch}
            onChange={(e) => setArch(e.target.value)}
            className="w-full bg-bg border border-border rounded-md px-3 py-2 text-white text-sm focus:outline-none focus:border-accent"
          />
          <p className="text-muted text-xs mt-1">Must match an arch_configs entry or default.</p>
        </div>

        {/* Options */}
        <div className="flex gap-6">
          <label className="flex items-center gap-2 text-sm text-muted cursor-pointer">
            <input
              type="checkbox"
              checked={skipUnit}
              onChange={(e) => setSkipUnit(e.target.checked)}
              className="accent-accent"
            />
            Skip unit tests
          </label>
          <label className="flex items-center gap-2 text-sm text-muted cursor-pointer">
            <input
              type="checkbox"
              checked={skipRegression}
              onChange={(e) => setSkipRegression(e.target.checked)}
              className="accent-accent"
            />
            Skip regression tests
          </label>
        </div>

        {error && <p className="text-failed text-sm">{error}</p>}

        <button
          onClick={handleStart}
          className="flex items-center justify-center gap-2 bg-accent text-bg font-medium rounded-md py-2.5 text-sm hover:brightness-110 transition"
        >
          <Play size={15} />
          Start Run
        </button>
      </div>
    </div>
  );
}
