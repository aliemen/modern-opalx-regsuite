import type { RunConfigSummary } from "../../api/runs";
import {
  SlurmResourceFields,
  type SlurmResourceForm,
} from "./SlurmResourceFields";
import { RuntimeFields } from "./RuntimeFields";

interface AdvancedRunFieldsProps {
  customCmakeText: string;
  hasCustomCmakeArgs: boolean;
  selectedRunConfig: RunConfigSummary | null;
  mpiRanks: number;
  opalxInfoLevel: number;
  slurmForm: SlurmResourceForm;
  slurmOverrideDirty: boolean;
  onMpiRanksChange: (value: number) => void;
  onOpalxInfoLevelChange: (value: number) => void;
  onCustomCmakeTextChange: (value: string) => void;
  onSlurmFormChange: (value: SlurmResourceForm) => void;
  onSlurmReset: () => void;
}

export function AdvancedRunFields({
  customCmakeText,
  hasCustomCmakeArgs,
  selectedRunConfig,
  mpiRanks,
  opalxInfoLevel,
  slurmForm,
  slurmOverrideDirty,
  onMpiRanksChange,
  onOpalxInfoLevelChange,
  onCustomCmakeTextChange,
  onSlurmFormChange,
  onSlurmReset,
}: AdvancedRunFieldsProps) {
  return (
    <div className="flex flex-col gap-3">
      <RuntimeFields
        selectedRunConfig={selectedRunConfig}
        mpiRanks={mpiRanks}
        opalxInfoLevel={opalxInfoLevel}
        showMpiRanks
        showOpalxInfoLevel={false}
        onMpiRanksChange={onMpiRanksChange}
        onOpalxInfoLevelChange={onOpalxInfoLevelChange}
      />
      <div>
        <label htmlFor="custom-cmake-args" className="block text-sm text-muted mb-1">
          Custom CMake args
        </label>
        <textarea
          id="custom-cmake-args"
          value={customCmakeText}
          onChange={(e) => onCustomCmakeTextChange(e.target.value)}
          rows={8}
          spellCheck={false}
          placeholder={[
            "-DIPPL_GIT_TAG=master",
            "-DHeffte_VERSION=git.v2.4.1",
            "-DKokkos_VERSION=git.4.7.01",
          ].join("\n")}
          className="w-full resize-y bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm font-mono focus:outline-none focus:border-accent"
        />
        <p className="text-muted text-xs mt-1">
          One CMake argument per line. Blank lines and lines starting with # are
          ignored. These args override matching run-config values.
        </p>
      </div>
      {hasCustomCmakeArgs && (
        <div className="rounded-md border border-accent/30 bg-accent/10 px-3 py-2 text-xs text-accent">
          This run will use a clean build because custom CMake args are set.
        </div>
      )}
      <SlurmResourceFields
        enabled={selectedRunConfig?.slurm_enabled ?? false}
        supported={selectedRunConfig?.slurm_overrides_supported ?? false}
        dirty={slurmOverrideDirty}
        form={slurmForm}
        onChange={onSlurmFormChange}
        onReset={onSlurmReset}
      />
    </div>
  );
}
