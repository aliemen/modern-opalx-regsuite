/* eslint-disable react-hooks/set-state-in-effect, react-refresh/only-export-components */
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Play, Info } from "lucide-react";
import {
  getOpalxBranches,
  getRegtestsBranches,
  triggerRun,
  type TriggerRequest,
} from "../api/runs";
import { getRunProfilesForTrigger } from "../api/executionProfiles";
import { InteractiveGatewayFields } from "./trigger/InteractiveGatewayFields";
import { RuntimeFields } from "./trigger/RuntimeFields";
import {
  formFromSlurmDefaults,
  slurmResourcesFromForm,
  validateSlurmForm,
  type SlurmResourceForm,
} from "./trigger/SlurmResourceFields";
import { AdvancedRunFields } from "./trigger/AdvancedRunFields";
import { TriggerTabs, type TriggerTab } from "./trigger/TriggerTabs";
import { hasSlurmQueryParams, slurmFormFromQuery } from "./trigger/slurmQuery";
import {
  parseCustomCmakeArgs,
  parseNonNegativeIntParam,
  parsePositiveIntParam,
} from "./trigger/parse";

const MAX_BRANCH_LABEL_CHARS = 56;

function truncateBranchLabel(branch: string): string {
  if (branch.length <= MAX_BRANCH_LABEL_CHARS) return branch;
  return `${branch.slice(0, MAX_BRANCH_LABEL_CHARS - 3)}...`;
}

function fallbackBranch(branches: string[] | undefined): string {
  if (!branches || branches.length === 0) return "master";
  return branches.includes("master") ? "master" : branches[0];
}

export { parseCustomCmakeArgs };

export function TriggerPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const [opalxBranch, setOpalxBranch] = useState(
    searchParams.get("branch") ?? "master"
  );
  const [regtestsBranch, setRegtestsBranch] = useState(
    searchParams.get("regtests_branch") ?? "master"
  );
  const [profileId, setProfileId] = useState(searchParams.get("profile_id") ?? "");
  const [skipUnit, setSkipUnit] = useState(searchParams.get("skip_unit") === "true");
  const [skipRegression, setSkipRegression] = useState(
    searchParams.get("skip_regression") === "true"
  );
  const [cleanBuild, setCleanBuild] = useState(
    searchParams.get("clean_build") === "true"
  );
  const [mpiRanks, setMpiRanks] = useState(() =>
    parsePositiveIntParam(searchParams.get("mpi_ranks"), 1)
  );
  const [opalxInfoLevel, setOpalxInfoLevel] = useState(() =>
    parseNonNegativeIntParam(searchParams.get("opalx_info_level"), 2)
  );
  const [slurmOverrideDirty, setSlurmOverrideDirty] = useState(() =>
    hasSlurmQueryParams(searchParams)
  );
  const [slurmForm, setSlurmForm] = useState<SlurmResourceForm>(() =>
    slurmFormFromQuery(searchParams)
  );
  const [activeTab, setActiveTab] = useState<TriggerTab>("basic");
  const [customCmakeText, setCustomCmakeText] = useState("");
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

  const { data: runProfiles, isLoading: loadingProfiles } = useQuery({
    queryKey: ["run-profiles-trigger"],
    queryFn: getRunProfilesForTrigger,
  });

  useEffect(() => {
    if (!opalxBranches || opalxBranches.includes(opalxBranch)) return;
    setOpalxBranch(fallbackBranch(opalxBranches));
  }, [opalxBranches, opalxBranch]);

  useEffect(() => {
    if (!regtestsBranches || regtestsBranches.includes(regtestsBranch)) return;
    setRegtestsBranch(fallbackBranch(regtestsBranches));
  }, [regtestsBranches, regtestsBranch]);

  const selectedRunConfig =
    runProfiles?.find((profile) => profile.id === profileId) ?? null;
  const profileMissing =
    profileId !== "" && !loadingProfiles && selectedRunConfig === null;
  const customCmakeArgs = parseCustomCmakeArgs(customCmakeText);
  const hasCustomCmakeArgs = customCmakeArgs.length > 0;
  const effectiveCleanBuild = cleanBuild || hasCustomCmakeArgs;
  const needsInteractiveCredentials =
    selectedRunConfig !== null && selectedRunConfig.interactive_gateway;

  useEffect(() => {
    if (!runProfiles || runProfiles.length === 0 || profileId) return;
    const requestedArch = searchParams.get("arch");
    const requestedConnection = searchParams.get("connection_name");
    const requestedBuildPreset = searchParams.get("build_preset_id");
    const requestedMachinePreset = searchParams.get("machine_preset_id");
    const hasEnvPresetParam = searchParams.has("env_preset_id");
    const requestedEnvPreset = searchParams.get("env_preset_id") || null;
    const hasSlurmPresetParam = searchParams.has("slurm_preset_id");
    const requestedSlurmPreset = searchParams.get("slurm_preset_id") || null;
    const preferred =
      runProfiles.find((profile) => profile.id === searchParams.get("profile_id")) ??
      runProfiles.find((profile) => {
        if (!requestedBuildPreset && !requestedMachinePreset) return false;
        if (requestedBuildPreset && profile.build_preset_id !== requestedBuildPreset) {
          return false;
        }
        if (
          requestedMachinePreset &&
          profile.machine_preset_id !== requestedMachinePreset
        ) {
          return false;
        }
        if (hasEnvPresetParam && (profile.env_preset_id ?? null) !== requestedEnvPreset) {
          return false;
        }
        if (
          hasSlurmPresetParam &&
          (profile.slurm_preset_id ?? null) !== requestedSlurmPreset
        ) {
          return false;
        }
        return true;
      }) ??
      runProfiles.find((profile) => {
        if (!requestedArch) return false;
        if (profile.arch !== requestedArch) return false;
        if (!requestedConnection || requestedConnection === "local") {
          return profile.machine_kind === "local";
        }
        return profile.machine_preset_id === requestedConnection;
      }) ??
      runProfiles.find((profile) => profile.valid) ??
      runProfiles[0];
    setProfileId(preferred.id);
  }, [runProfiles, profileId, searchParams]);

  useEffect(() => {
    if (!selectedRunConfig) return;
    if (!searchParams.has("mpi_ranks")) {
      setMpiRanks(selectedRunConfig.default_mpi_ranks);
    }
    if (!searchParams.has("opalx_info_level")) {
      setOpalxInfoLevel(selectedRunConfig.default_opalx_info_level);
    }
  }, [selectedRunConfig, searchParams]);

  useEffect(() => {
    if (!selectedRunConfig || slurmOverrideDirty) return;
    setSlurmForm(
      formFromSlurmDefaults(selectedRunConfig.slurm_defaults, mpiRanks)
    );
  }, [selectedRunConfig, slurmOverrideDirty, mpiRanks]);

  function updateProfile(nextProfileId: string) {
    setProfileId(nextProfileId);
    const nextConfig = runProfiles?.find((profile) => profile.id === nextProfileId);
    if (nextConfig) {
      setMpiRanks(nextConfig.default_mpi_ranks);
      setOpalxInfoLevel(nextConfig.default_opalx_info_level);
      setSlurmOverrideDirty(false);
      setSlurmForm(
        formFromSlurmDefaults(nextConfig.slurm_defaults, nextConfig.default_mpi_ranks)
      );
    }
  }

  function updateSlurmForm(nextForm: SlurmResourceForm) {
    setSlurmOverrideDirty(true);
    setSlurmForm(nextForm);
  }

  function resetSlurmForm() {
    setSlurmOverrideDirty(false);
    setSlurmForm(formFromSlurmDefaults(selectedRunConfig?.slurm_defaults, mpiRanks));
  }

  async function handleStart() {
    setError(null);
    setQueuedInfo(null);

    if (!selectedRunConfig) {
      setError("Choose a run profile before starting the run.");
      return;
    }
    if (profileMissing || !selectedRunConfig.valid) {
      setError(
        selectedRunConfig?.validation_errors.join("; ") ||
          "This run profile is not available. Choose another profile.",
      );
      return;
    }

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
    if (!Number.isInteger(mpiRanks) || mpiRanks < 1) {
      setError("MPI ranks must be at least 1.");
      return;
    }
    if (
      selectedRunConfig?.max_mpi_ranks != null &&
      mpiRanks > selectedRunConfig.max_mpi_ranks
    ) {
      setError(`MPI ranks cannot exceed ${selectedRunConfig.max_mpi_ranks} for ${selectedRunConfig.name}.`);
      return;
    }
    if (!Number.isInteger(opalxInfoLevel) || opalxInfoLevel < 0) {
      setError("OPALX info level must be 0 or greater.");
      return;
    }
    if (slurmOverrideDirty) {
      if (!selectedRunConfig?.slurm_overrides_supported) {
        setError("This run config does not support manual Slurm overrides.");
        return;
      }
      const slurmError = validateSlurmForm(slurmForm, mpiRanks);
      if (slurmError) {
        setError(slurmError);
        return;
      }
    }

    try {
      const body: TriggerRequest = {
        branch: opalxBranch,
        arch: selectedRunConfig.arch,
        profile_id: selectedRunConfig.id,
        regtests_branch: regtestsBranch,
        skip_unit: skipUnit,
        skip_regression: skipRegression,
        clean_build: effectiveCleanBuild,
        custom_cmake_args: customCmakeArgs,
        mpi_ranks: mpiRanks,
        opalx_info_level: opalxInfoLevel,
      };
      if (slurmOverrideDirty) {
        body.slurm_resources = slurmResourcesFromForm(slurmForm);
      }
      const rerunBranch = searchParams.get("rerun_branch");
      const rerunArch = searchParams.get("rerun_arch");
      const rerunId = searchParams.get("rerun_id");
      if (rerunBranch && rerunArch && rerunId) {
        body.rerun_of = {
          branch: rerunBranch,
          arch: rerunArch,
          run_id: rerunId,
        };
      }
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
    <div className="p-4 sm:p-6 max-w-xl mx-auto">
      <h1 className="text-fg text-2xl font-semibold mb-6">Start a Run</h1>

      <div className="bg-surface border border-border rounded-xl p-4 flex flex-col gap-5 sm:p-6">
        <TriggerTabs activeTab={activeTab} onChange={setActiveTab} />

        {activeTab === "basic" ? (
          <>
        {/* OPALX branch */}
        <div>
          <label className="block text-sm text-muted mb-1">OPALX branch</label>
          <div className="flex gap-2">
            <select
              value={opalxBranch}
              onChange={(e) => setOpalxBranch(e.target.value)}
              title={opalxBranch}
              className="flex-1 min-w-0 bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
              disabled={loadingOpalx}
            >
              {(opalxBranches ?? ["master"]).map((b) => (
                <option key={b} value={b} title={b}>
                  {truncateBranchLabel(b)}
                </option>
              ))}
            </select>
            <button
              onClick={() => refetchOpalx()}
              disabled={fetchingOpalx}
              className="shrink-0 p-2 text-muted hover:text-fg border border-border rounded-md transition disabled:opacity-50"
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
              title={regtestsBranch}
              className="flex-1 min-w-0 bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
              disabled={loadingRegtests}
            >
              {(regtestsBranches ?? ["master"]).map((b) => (
                <option key={b} value={b} title={b}>
                  {truncateBranchLabel(b)}
                </option>
              ))}
            </select>
            <button
              onClick={() => refetchRegtests()}
              disabled={fetchingRegtests}
              className="shrink-0 p-2 text-muted hover:text-fg border border-border rounded-md transition disabled:opacity-50"
              title="Refresh branches"
            >
              <RefreshCw size={15} className={fetchingRegtests ? "animate-spin" : ""} />
            </button>
          </div>
        </div>

        {/* Run profile */}
        <div>
          <label className="block text-sm text-muted mb-1">Run profile</label>
          <select
            value={profileId}
            onChange={(e) => {
              updateProfile(e.target.value);
              setGatewayPassword("");
              setGatewayOtp("");
            }}
            className="w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
            disabled={loadingProfiles}
          >
            {profileMissing && (
              <option value={profileId}>{profileId} (unavailable)</option>
            )}
            {(runProfiles ?? []).map((profile) => (
              <option key={profile.id} value={profile.id} disabled={!profile.valid}>
                {profile.name}
                {profile.description ? ` - ${profile.description}` : ""}
                {!profile.valid ? " (invalid)" : ""}
              </option>
            ))}
          </select>
          {selectedRunConfig && (
            <p className="text-muted text-xs mt-1">
              {selectedRunConfig.build_preset_name} /{" "}
              {selectedRunConfig.machine_preset_name}
              {selectedRunConfig.env_preset_name
                ? ` / ${selectedRunConfig.env_preset_name}`
                : ""}
              {selectedRunConfig.slurm_preset_name
                ? ` / ${selectedRunConfig.slurm_preset_name}`
                : ""}
            </p>
          )}
          {selectedRunConfig && !selectedRunConfig.valid && (
            <p className="text-failed text-xs mt-1">
              {selectedRunConfig.validation_errors.join("; ")}
            </p>
          )}
        </div>

        <RuntimeFields
          selectedRunConfig={selectedRunConfig}
          mpiRanks={mpiRanks}
          opalxInfoLevel={opalxInfoLevel}
          showMpiRanks={false}
          showOpalxInfoLevel
          onMpiRanksChange={setMpiRanks}
          onOpalxInfoLevelChange={setOpalxInfoLevel}
        />

        {/* Interactive gateway credentials */}
        {needsInteractiveCredentials && (
          <InteractiveGatewayFields
            connection={{
              name: selectedRunConfig!.name,
              host: selectedRunConfig!.machine_preset_name,
              user: "",
              port: 22,
              key_name: "",
              gateway: {
                host: selectedRunConfig!.machine_preset_name,
                user: "",
                port: 22,
                key_name: null,
                auth_method: "interactive",
              },
              work_dir: "",
              cleanup_after_run: false,
              keepalive_interval: 30,
              env: { style: "none" },
            }}
            gatewayPassword={gatewayPassword}
            gatewayOtp={gatewayOtp}
            onGatewayPasswordChange={setGatewayPassword}
            onGatewayOtpChange={setGatewayOtp}
          />
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
              checked={effectiveCleanBuild}
              onChange={(e) => setCleanBuild(e.target.checked)}
              disabled={hasCustomCmakeArgs}
              className="accent-accent"
            />
            Clean build
          </label>
          {hasCustomCmakeArgs && (
            <span className="text-xs text-accent">
              Required by custom CMake args.
            </span>
          )}
        </div>
          </>
        ) : (
          <AdvancedRunFields
            customCmakeText={customCmakeText}
            hasCustomCmakeArgs={hasCustomCmakeArgs}
            selectedRunConfig={selectedRunConfig}
            mpiRanks={mpiRanks}
            opalxInfoLevel={opalxInfoLevel}
            slurmForm={slurmForm}
            slurmOverrideDirty={slurmOverrideDirty}
            onMpiRanksChange={setMpiRanks}
            onOpalxInfoLevelChange={setOpalxInfoLevel}
            onCustomCmakeTextChange={setCustomCmakeText}
            onSlurmFormChange={updateSlurmForm}
            onSlurmReset={resetSlurmForm}
          />
        )}

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
          disabled={!selectedRunConfig || profileMissing || selectedRunConfig.valid === false}
          className="flex items-center justify-center gap-2 bg-accent text-bg font-medium rounded-md py-2.5 text-sm hover:brightness-110 transition disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Play size={15} />
          Start Run
        </button>
      </div>
    </div>
  );
}
