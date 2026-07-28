import { useRef } from "react";
import { Check, Plus } from "lucide-react";
import type { SlurmResources } from "../../api/runs";
import {
  SlurmResourceFields,
  type SlurmResourceForm,
} from "./SlurmResourceFields";
import { RuntimeFields } from "./RuntimeFields";

interface AdvancedRunFieldsProps {
  customCmakeText: string;
  hasCustomCmakeArgs: boolean;
  cmakeQuickSelections: string[];
  selectedRunConfig: {
    max_mpi_ranks?: number | null;
    slurm_enabled: boolean;
    slurm_overrides_supported: boolean;
    slurm_defaults?: SlurmResources | null;
  } | null;
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

function cmakeDefineKey(argument: string): string | null {
  const value = argument.trim();
  if (!value.startsWith("-D")) return null;
  const equalsIndex = value.indexOf("=");
  if (equalsIndex < 0) return null;
  return value.slice(2, equalsIndex).split(":", 1)[0] || null;
}

function hasCmakeQuickSelection(text: string, key: string): boolean {
  return text
    .split(/\r?\n/)
    .some((line) => cmakeDefineKey(line) === key);
}

export function AdvancedRunFields({
  customCmakeText,
  hasCustomCmakeArgs,
  cmakeQuickSelections,
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
  const customCmakeRef = useRef<HTMLTextAreaElement>(null);

  function addQuickSelection(key: string) {
    if (hasCmakeQuickSelection(customCmakeText, key)) return;
    const prefix = `-D${key}=`;
    const separator = customCmakeText && !customCmakeText.endsWith("\n") ? "\n" : "";
    const nextText = `${customCmakeText}${separator}${prefix}`;
    onCustomCmakeTextChange(nextText);
    requestAnimationFrame(() => {
      customCmakeRef.current?.focus();
      customCmakeRef.current?.setSelectionRange(nextText.length, nextText.length);
    });
  }

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
        {cmakeQuickSelections.length > 0 && (
          <div className="mb-3">
            <p className="mb-1.5 text-xs font-medium text-muted">Quick add</p>
            <div className="flex flex-wrap gap-2">
              {cmakeQuickSelections.map((key) => {
                const added = hasCmakeQuickSelection(customCmakeText, key);
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => addQuickSelection(key)}
                    disabled={added}
                    aria-label={
                      added
                        ? `${key} already added`
                        : `Add CMake argument ${key}`
                    }
                    className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-xs transition ${
                      added
                        ? "cursor-default border-accent/30 bg-accent/10 text-accent"
                        : "border-border bg-bg text-muted hover:border-accent/50 hover:text-fg"
                    }`}
                  >
                    {added ? <Check size={12} /> : <Plus size={12} />}
                    {key}
                  </button>
                );
              })}
            </div>
          </div>
        )}
        <label htmlFor="custom-cmake-args" className="block text-sm text-muted mb-1">
          Custom CMake args
        </label>
        <textarea
          ref={customCmakeRef}
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
