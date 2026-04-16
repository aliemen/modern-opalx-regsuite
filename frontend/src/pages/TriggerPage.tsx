import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Play, Info, ShieldAlert } from "lucide-react";
import {
  getArchConfigs,
  getOpalxBranches,
  getRegtestsBranches,
  triggerRun,
  type TriggerRequest,
} from "../api/runs";
import { listConnections, LOCAL_CONNECTION } from "../api/connections";

export function TriggerPage() {
  const navigate = useNavigate();

  const [opalxBranch, setOpalxBranch] = useState("master");
  const [regtestsBranch, setRegtestsBranch] = useState("master");
  const [arch, setArch] = useState("cpu-serial");
  const [connectionName, setConnectionName] = useState<string>(LOCAL_CONNECTION);
  const [skipUnit, setSkipUnit] = useState(false);
  const [skipRegression, setSkipRegression] = useState(false);
  const [cleanBuild, setCleanBuild] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queuedInfo, setQueuedInfo] = useState<{ runId: string; position: number } | null>(null);

  // Interactive gateway credentials (held in state only, never persisted).
  const [gatewayPassword, setGatewayPassword] = useState("");
  const [gatewayOtp, setGatewayOtp] = useState("");

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

  const { data: archConfigs, isLoading: loadingArchs } = useQuery({
    queryKey: ["arch-configs"],
    queryFn: getArchConfigs,
  });

  const { data: connections, isLoading: loadingConnections } = useQuery({
    queryKey: ["connections"],
    queryFn: listConnections,
  });

  // Detect if the selected connection uses an interactive gateway.
  const selectedConnection =
    connections?.find((c) => c.name === connectionName) ?? null;
  const needsInteractiveCredentials =
    selectedConnection !== null &&
    selectedConnection.gateway != null &&
    selectedConnection.gateway.auth_method === "interactive";

  async function handleStart() {
    setError(null);
    setQueuedInfo(null);

    if (needsInteractiveCredentials) {
      if (!gatewayPassword.trim()) {
        setError("Gateway password is required.");
        return;
      }
      if (!gatewayOtp.trim()) {
        setError("Microsoft Authenticator OTP is required.");
        return;
      }
    }

    try {
      const body: TriggerRequest = {
        branch: opalxBranch,
        arch,
        regtests_branch: regtestsBranch,
        skip_unit: skipUnit,
        skip_regression: skipRegression,
        clean_build: cleanBuild,
        connection_name: connectionName,
      };
      if (needsInteractiveCredentials) {
        body.gateway_password = gatewayPassword;
        body.gateway_otp = gatewayOtp;
      }
      const res = await triggerRun(body);
      // Clear credentials from memory immediately after sending.
      setGatewayPassword("");
      setGatewayOtp("");
      if (res.queued) {
        setQueuedInfo({ runId: res.run_id, position: res.position ?? 1 });
      } else {
        navigate(`/live/${res.run_id}`);
      }
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Failed to start run.";
      setError(msg);
      // Clear OTP on failure (it may have been consumed or expired),
      // but keep the password so the user can re-enter just a new OTP.
      setGatewayOtp("");
    }
  }

  return (
    <div className="p-6 max-w-xl mx-auto">
      <h1 className="text-fg text-2xl font-semibold mb-6">Start a Run</h1>

      <div className="bg-surface border border-border rounded-xl p-6 flex flex-col gap-5">
        {/* OPALX branch */}
        <div>
          <label className="block text-sm text-muted mb-1">OPALX branch</label>
          <div className="flex gap-2">
            <select
              value={opalxBranch}
              onChange={(e) => setOpalxBranch(e.target.value)}
              className="flex-1 bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
              disabled={loadingOpalx}
            >
              {(opalxBranches ?? ["master"]).map((b) => (
                <option key={b}>{b}</option>
              ))}
            </select>
            <button
              onClick={() => refetchOpalx()}
              disabled={fetchingOpalx}
              className="p-2 text-muted hover:text-fg border border-border rounded-md transition disabled:opacity-50"
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
              className="flex-1 bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
              disabled={loadingRegtests}
            >
              {(regtestsBranches ?? ["master"]).map((b) => (
                <option key={b}>{b}</option>
              ))}
            </select>
            <button
              onClick={() => refetchRegtests()}
              disabled={fetchingRegtests}
              className="p-2 text-muted hover:text-fg border border-border rounded-md transition disabled:opacity-50"
              title="Refresh branches"
            >
              <RefreshCw size={15} className={fetchingRegtests ? "animate-spin" : ""} />
            </button>
          </div>
        </div>

        {/* Architecture */}
        <div>
          <label className="block text-sm text-muted mb-1">Run config</label>
          <select
            value={arch}
            onChange={(e) => setArch(e.target.value)}
            className="w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
            disabled={loadingArchs}
          >
            {(archConfigs ?? ["cpu-serial"]).map((a) => (
              <option key={a}>{a}</option>
            ))}
          </select>
        </div>

        {/* Connection (or local) */}
        <div>
          <label className="block text-sm text-muted mb-1">Connection</label>
          <select
            value={connectionName}
            onChange={(e) => {
              setConnectionName(e.target.value);
              // Clear gateway credentials when switching connections.
              setGatewayPassword("");
              setGatewayOtp("");
            }}
            className="w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
            disabled={loadingConnections}
          >
            <option value={LOCAL_CONNECTION}>Local</option>
            {(connections ?? []).map((c) => (
              <option key={c.name} value={c.name}>
                {c.name}
                {c.description ? ` — ${c.description}` : ""}
              </option>
            ))}
          </select>
          <p className="text-muted text-xs mt-1">
            Manage connections in <span className="text-fg">Settings</span>.
          </p>
        </div>

        {/* Interactive gateway credentials */}
        {needsInteractiveCredentials && (
          <div className="border border-border rounded-md p-4 flex flex-col gap-3 bg-bg">
            <div className="flex items-start gap-2 text-sm text-muted">
              <ShieldAlert size={16} className="mt-0.5 shrink-0 text-accent" />
              <p className="text-xs">
                This connection uses an interactive SSH gateway
                ({selectedConnection!.gateway!.host}). Enter your password and
                Microsoft Authenticator OTP code below. Credentials are used for
                this run only and are never stored.
              </p>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-muted mb-1">
                  Gateway password
                </label>
                <input
                  type="password"
                  value={gatewayPassword}
                  onChange={(e) => setGatewayPassword(e.target.value)}
                  placeholder="PSI password"
                  className="w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
                  autoComplete="off"
                />
              </div>
              <div>
                <label className="block text-xs text-muted mb-1">
                  Authenticator OTP
                </label>
                <input
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  value={gatewayOtp}
                  onChange={(e) => setGatewayOtp(e.target.value)}
                  placeholder="6-digit code"
                  className="w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
                  autoComplete="off"
                />
              </div>
            </div>
            <p className="text-xs text-muted">
              Use the OTP code from Microsoft Authenticator (not the push
              notification). The code is time-limited — enter it just before
              clicking Start Run. If the target machine is busy, the run cannot
              be queued (the OTP would expire).
            </p>
          </div>
        )}

        {/* Options */}
        <div className="flex flex-wrap gap-x-6 gap-y-2">
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
          <label
            className="flex items-center gap-2 text-sm text-muted cursor-pointer"
            title="Delete the build directory before cmake + make. Forces a full reconfigure and recompile."
          >
            <input
              type="checkbox"
              checked={cleanBuild}
              onChange={(e) => setCleanBuild(e.target.checked)}
              className="accent-accent"
            />
            Clean build
          </label>
        </div>

        {error && <p className="text-failed text-sm">{error}</p>}

        {queuedInfo && (
          <div className="flex items-start gap-2 text-sm bg-accent/10 border border-accent/30 rounded-md px-4 py-3 text-accent">
            <Info size={15} className="mt-0.5 shrink-0" />
            <div>
              <p>
                Run queued at position #{queuedInfo.position}. It will start
                automatically when the machine becomes available.
              </p>
              <button
                onClick={() => navigate("/")}
                className="text-xs underline mt-1 hover:brightness-110"
              >
                View queue on dashboard
              </button>
            </div>
          </div>
        )}

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
