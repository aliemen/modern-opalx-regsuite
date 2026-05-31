import { useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Boxes,
  Clipboard,
  Cpu,
  Database,
  Edit3,
  Layers3,
  Plus,
  RotateCcw,
  Save,
  Server,
  TerminalSquare,
  Trash2,
  X,
} from "lucide-react";
import {
  getExecutionSettings,
  resetExecutionSettingsFromConfig,
  saveExecutionSettings,
  type BuildPreset,
  type EnvPreset,
  type ExecutionSettings,
  type MachinePreset,
  type SlurmPreset,
} from "../../api/executionProfiles";
import {
  arrayToLines,
  deriveCmakeValue,
  emptyToNull,
  generatedLabel,
  inputCls,
  intFromString,
  linesToArray,
  selectCls,
  textareaCls,
  validateId,
} from "./publicSettingsHelpers";

type SavePreset<T> = (preset: T) => Promise<void>;
type DeletePreset = (id: string) => Promise<void>;

const DEFAULT_LMOD_INIT = "/usr/share/lmod/lmod/init/bash";

function extractError(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response
    ?.data?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) {
    return String((detail as { message: unknown }).message);
  }
  return fallback;
}

function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function pillClass(tone: "accent" | "muted" | "warn" = "muted"): string {
  if (tone === "accent") return "border-accent/40 bg-accent/10 text-accent";
  if (tone === "warn") return "border-yellow-500/40 bg-yellow-500/10 text-yellow-300";
  return "border-border bg-bg text-muted";
}

function Pill({
  children,
  tone = "muted",
}: {
  children: ReactNode;
  tone?: "accent" | "muted" | "warn";
}) {
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs ${pillClass(tone)}`}>
      {children}
    </span>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="block text-xs text-muted mb-1">{label}</span>
      {children}
    </label>
  );
}

function SectionHeader({
  icon,
  title,
  count,
  children,
}: {
  icon: ReactNode;
  title: string;
  count: number;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h3 className="text-fg text-base font-medium flex items-center gap-2">
          {icon}
          {title}
        </h3>
        <p className="text-muted text-xs mt-1">{count} preset{count === 1 ? "" : "s"}</p>
      </div>
      {children}
    </div>
  );
}

function actionButtonCls(kind: "primary" | "secondary" | "danger" = "secondary") {
  if (kind === "primary") {
    return "inline-flex items-center justify-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-bg hover:brightness-110 transition disabled:opacity-50";
  }
  if (kind === "danger") {
    return "inline-flex items-center justify-center gap-1.5 rounded-md border border-failed/40 px-3 py-1.5 text-sm text-failed hover:bg-failed/10 transition disabled:opacity-50";
  }
  return "inline-flex items-center justify-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm text-muted hover:text-fg transition disabled:opacity-50";
}

export function ExecutionSettingsSection() {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["execution-settings"],
    queryFn: getExecutionSettings,
  });

  const invalidateExecution = () => {
    queryClient.invalidateQueries({ queryKey: ["execution-settings"] });
    queryClient.invalidateQueries({ queryKey: ["run-profile-summaries"] });
    queryClient.invalidateQueries({ queryKey: ["run-profiles"] });
    queryClient.invalidateQueries({ queryKey: ["run-profiles-trigger"] });
  };

  const saveMut = useMutation({
    mutationFn: saveExecutionSettings,
    onSuccess: (saved) => {
      setError(null);
      queryClient.setQueryData(["execution-settings"], saved);
      invalidateExecution();
    },
    onError: (e: unknown) => {
      setError(extractError(e, "Failed to save public settings."));
    },
  });

  const resetMut = useMutation({
    mutationFn: resetExecutionSettingsFromConfig,
    onSuccess: (saved) => {
      setError(null);
      queryClient.setQueryData(["execution-settings"], saved);
      invalidateExecution();
    },
    onError: (e: unknown) => {
      setError(extractError(e, "Failed to reset public settings."));
    },
  });

  async function persist(next: ExecutionSettings) {
    setError(null);
    try {
      await saveMut.mutateAsync(next);
    } catch (e) {
      setError(extractError(e, "Failed to save public settings."));
      throw e;
    }
  }

  if (isLoading || !data) {
    return (
      <div className="bg-surface border border-border rounded-xl p-4 sm:p-6">
        <Header onReset={() => undefined} resetPending={false} />
        <p className="text-muted text-sm">Loading public settings...</p>
      </div>
    );
  }

  const saveBuild: SavePreset<BuildPreset> = async (preset) => {
    const exists = data.build_presets.some((item) => item.id === preset.id);
    await persist({
      ...data,
      build_presets: exists
        ? data.build_presets.map((item) => (item.id === preset.id ? preset : item))
        : [...data.build_presets, preset],
    });
  };

  const saveMachine: SavePreset<MachinePreset> = async (preset) => {
    const exists = data.machine_presets.some((item) => item.id === preset.id);
    await persist({
      ...data,
      machine_presets: exists
        ? data.machine_presets.map((item) => (item.id === preset.id ? preset : item))
        : [...data.machine_presets, preset],
    });
  };

  const saveEnv: SavePreset<EnvPreset> = async (preset) => {
    const exists = data.env_presets.some((item) => item.id === preset.id);
    await persist({
      ...data,
      env_presets: exists
        ? data.env_presets.map((item) => (item.id === preset.id ? preset : item))
        : [...data.env_presets, preset],
    });
  };

  const saveSlurm: SavePreset<SlurmPreset> = async (preset) => {
    const exists = data.slurm_presets.some((item) => item.id === preset.id);
    await persist({
      ...data,
      slurm_presets: exists
        ? data.slurm_presets.map((item) => (item.id === preset.id ? preset : item))
        : [...data.slurm_presets, preset],
    });
  };

  const deleteBuild: DeletePreset = async (id) => {
    await persist({
      ...data,
      build_presets: data.build_presets.filter((item) => item.id !== id),
    });
  };
  const deleteMachine: DeletePreset = async (id) => {
    await persist({
      ...data,
      machine_presets: data.machine_presets.filter((item) => item.id !== id),
    });
  };
  const deleteEnv: DeletePreset = async (id) => {
    await persist({
      ...data,
      env_presets: data.env_presets.filter((item) => item.id !== id),
    });
  };
  const deleteSlurm: DeletePreset = async (id) => {
    await persist({
      ...data,
      slurm_presets: data.slurm_presets.filter((item) => item.id !== id),
    });
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="bg-surface border border-border rounded-xl p-4 sm:p-6">
        <Header
          onReset={() => resetMut.mutate()}
          resetPending={resetMut.isPending}
        />
        {error && (
          <div className="rounded-md border border-failed/40 bg-failed/10 px-3 py-2 text-sm text-failed">
            {error}
          </div>
        )}
      </div>

      <BuildPresetsCard
        presets={data.build_presets}
        saving={saveMut.isPending}
        onSave={saveBuild}
        onDelete={deleteBuild}
      />
      <MachinePresetsCard
        machinePresets={data.machine_presets}
        slurmPresets={data.slurm_presets}
        saving={saveMut.isPending}
        onSaveMachine={saveMachine}
        onDeleteMachine={deleteMachine}
        onSaveSlurm={saveSlurm}
        onDeleteSlurm={deleteSlurm}
      />
      <EnvironmentPresetsCard
        presets={data.env_presets}
        saving={saveMut.isPending}
        onSave={saveEnv}
        onDelete={deleteEnv}
      />
      <JsonExport settings={data} />
    </div>
  );
}

function Header({
  onReset,
  resetPending,
}: {
  onReset: () => void;
  resetPending: boolean;
}) {
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div>
        <h2 className="text-fg text-lg font-medium flex items-center gap-2">
          <Database size={18} />
          Public Settings
        </h2>
        <p className="text-muted text-sm mt-2 max-w-3xl">
          Shared build, machine, environment, and Slurm presets available to all
          dashboard users.
        </p>
      </div>
      <button
        type="button"
        onClick={onReset}
        disabled={resetPending}
        className={actionButtonCls("secondary")}
      >
        <RotateCcw size={14} />
        Reset from config
      </button>
    </div>
  );
}

interface BuildForm {
  id: string;
  name: string;
  description: string;
  cmakeText: string;
  buildJobs: string;
  mpiRanks: string;
  maxMpiRanks: string;
  opalxInfoLevel: string;
  generated: boolean;
}

const EMPTY_BUILD_FORM: BuildForm = {
  id: "",
  name: "",
  description: "",
  cmakeText: "",
  buildJobs: "8",
  mpiRanks: "1",
  maxMpiRanks: "",
  opalxInfoLevel: "",
  generated: false,
};

function buildToForm(preset: BuildPreset): BuildForm {
  return {
    id: preset.id,
    name: preset.name,
    description: preset.description ?? "",
    cmakeText: arrayToLines(preset.cmake_args),
    buildJobs: String(preset.build_jobs),
    mpiRanks: String(preset.mpi_ranks),
    maxMpiRanks: preset.max_mpi_ranks == null ? "" : String(preset.max_mpi_ranks),
    opalxInfoLevel:
      preset.opalx_info_level == null ? "" : String(preset.opalx_info_level),
    generated: preset.generated,
  };
}

function parseBuildForm(form: BuildForm): { preset?: BuildPreset; error?: string } {
  const idError = validateId(form.id);
  if (idError) return { error: idError };
  if (!form.name.trim()) return { error: "Name is required." };
  const buildJobs = intFromString(form.buildJobs, "Build jobs", 1);
  if (buildJobs.error) return { error: buildJobs.error };
  const mpiRanks = intFromString(form.mpiRanks, "Default MPI ranks", 1);
  if (mpiRanks.error) return { error: mpiRanks.error };
  const maxRanks = intFromString(form.maxMpiRanks, "Max MPI ranks", 1, true);
  if (maxRanks.error) return { error: maxRanks.error };
  if (maxRanks.value != null && mpiRanks.value != null && maxRanks.value < mpiRanks.value) {
    return { error: "Max MPI ranks must be greater than or equal to default MPI ranks." };
  }
  const info = intFromString(form.opalxInfoLevel, "OPALX info level", 0, true);
  if (info.error) return { error: info.error };
  return {
    preset: {
      id: form.id.trim(),
      name: form.name.trim(),
      description: emptyToNull(form.description),
      cmake_args: linesToArray(form.cmakeText),
      build_jobs: buildJobs.value ?? 1,
      mpi_ranks: mpiRanks.value ?? 1,
      max_mpi_ranks: maxRanks.value,
      opalx_info_level: info.value,
      generated: form.generated,
    },
  };
}

function BuildPresetsCard({
  presets,
  saving,
  onSave,
  onDelete,
}: {
  presets: BuildPreset[];
  saving: boolean;
  onSave: SavePreset<BuildPreset>;
  onDelete: DeletePreset;
}) {
  const [form, setForm] = useState<BuildForm | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!form) return;
    const parsed = parseBuildForm(form);
    if (parsed.error || !parsed.preset) {
      setError(parsed.error ?? "Invalid build preset.");
      return;
    }
    setError(null);
    await onSave(parsed.preset);
    setForm(null);
    setEditingId(null);
  }

  async function remove(preset: BuildPreset) {
    if (
      window.confirm(
        `Delete build preset "${preset.name}"? Profiles that reference it will become invalid.`,
      )
    ) {
      await onDelete(preset.id);
    }
  }

  return (
    <div className="bg-surface border border-border rounded-xl p-4 sm:p-6 space-y-4">
      <SectionHeader icon={<Cpu size={18} />} title="Build Presets" count={presets.length}>
        {!form && (
          <button
            type="button"
            onClick={() => {
              setForm(EMPTY_BUILD_FORM);
              setEditingId(null);
              setError(null);
            }}
            className={actionButtonCls("primary")}
          >
            <Plus size={14} />
            Add build
          </button>
        )}
      </SectionHeader>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {presets.map((preset) => {
          const buildType = deriveCmakeValue(preset.cmake_args, "BUILD_TYPE");
          const platforms = deriveCmakeValue(preset.cmake_args, "PLATFORMS");
          const arch = deriveCmakeValue(preset.cmake_args, "ARCH");
          return (
            <div key={preset.id} className="rounded-lg border border-border bg-bg p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h4 className="truncate text-sm font-medium text-fg">{preset.name}</h4>
                  <p className="mt-0.5 font-mono text-xs text-muted">{preset.id}</p>
                </div>
                <div className="flex shrink-0 gap-1">
                  <button
                    type="button"
                    aria-label={`Edit build ${preset.name}`}
                    onClick={() => {
                      setForm(buildToForm(preset));
                      setEditingId(preset.id);
                      setError(null);
                    }}
                    className="rounded-md p-1.5 text-muted hover:text-fg"
                  >
                    <Edit3 size={14} />
                  </button>
                  <button
                    type="button"
                    aria-label={`Delete build ${preset.name}`}
                    onClick={() => void remove(preset)}
                    className="rounded-md p-1.5 text-muted hover:text-failed"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
              {preset.description && (
                <p className="mt-2 text-xs text-muted">{preset.description}</p>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                <Pill tone={preset.generated ? "muted" : "accent"}>
                  {generatedLabel(preset.generated)}
                </Pill>
                {buildType && <Pill>{buildType}</Pill>}
                {platforms && <Pill>{platforms}</Pill>}
                {arch && <Pill>{arch}</Pill>}
                <Pill>{preset.build_jobs} jobs</Pill>
                <Pill>{preset.mpi_ranks} ranks</Pill>
                {preset.max_mpi_ranks != null && <Pill>max {preset.max_mpi_ranks}</Pill>}
                {preset.opalx_info_level != null && (
                  <Pill>info {preset.opalx_info_level}</Pill>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {form && (
        <BuildPresetForm
          form={form}
          editing={editingId !== null}
          error={error}
          saving={saving}
          onChange={setForm}
          onCancel={() => {
            setForm(null);
            setEditingId(null);
            setError(null);
          }}
          onSubmit={() => void submit()}
        />
      )}
    </div>
  );
}

function BuildPresetForm({
  form,
  editing,
  error,
  saving,
  onChange,
  onCancel,
  onSubmit,
}: {
  form: BuildForm;
  editing: boolean;
  error: string | null;
  saving: boolean;
  onChange: (form: BuildForm) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  return (
    <div className="rounded-lg border border-border bg-bg p-4">
      <div className="mb-4 flex items-center justify-between">
        <h4 className="text-sm font-medium text-fg">
          {editing ? `Edit ${form.name}` : "New build preset"}
        </h4>
        <button type="button" onClick={onCancel} className="text-muted hover:text-fg">
          <X size={16} />
        </button>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="ID">
          <input
            value={form.id}
            disabled={editing}
            onChange={(e) => onChange({ ...form, id: e.target.value })}
            className={inputCls}
          />
        </Field>
        <Field label="Name">
          <input
            value={form.name}
            onChange={(e) => onChange({ ...form, name: e.target.value })}
            className={inputCls}
          />
        </Field>
        <div className="sm:col-span-2">
          <Field label="Description">
            <input
              value={form.description}
              onChange={(e) => onChange({ ...form, description: e.target.value })}
              className={inputCls}
            />
          </Field>
        </div>
        <Field label="Build jobs">
          <input
            type="number"
            min={1}
            value={form.buildJobs}
            onChange={(e) => onChange({ ...form, buildJobs: e.target.value })}
            className={inputCls}
          />
        </Field>
        <Field label="Default MPI ranks">
          <input
            type="number"
            min={1}
            value={form.mpiRanks}
            onChange={(e) => onChange({ ...form, mpiRanks: e.target.value })}
            className={inputCls}
          />
        </Field>
        <Field label="Max MPI ranks">
          <input
            type="number"
            min={1}
            value={form.maxMpiRanks}
            onChange={(e) => onChange({ ...form, maxMpiRanks: e.target.value })}
            className={inputCls}
          />
        </Field>
        <Field label="OPALX info level">
          <input
            type="number"
            min={0}
            value={form.opalxInfoLevel}
            onChange={(e) => onChange({ ...form, opalxInfoLevel: e.target.value })}
            className={inputCls}
          />
        </Field>
        <div className="sm:col-span-2">
          <Field label="CMake args">
            <textarea
              rows={8}
              value={form.cmakeText}
              onChange={(e) => onChange({ ...form, cmakeText: e.target.value })}
              className={textareaCls}
              spellCheck={false}
            />
          </Field>
        </div>
      </div>
      {error && <p className="mt-3 text-sm text-failed">{error}</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" onClick={onSubmit} disabled={saving} className={actionButtonCls("primary")}>
          <Save size={14} />
          Save build
        </button>
        <button type="button" onClick={onCancel} className={actionButtonCls("secondary")}>
          Cancel
        </button>
      </div>
    </div>
  );
}

interface MachineForm {
  id: string;
  name: string;
  description: string;
  kind: "local" | "ssh";
  host: string;
  port: string;
  queueKey: string;
  gatewayEnabled: boolean;
  gatewayHost: string;
  gatewayPort: string;
  gatewayAuthMethod: "key" | "interactive";
  generated: boolean;
}

const EMPTY_MACHINE_FORM: MachineForm = {
  id: "",
  name: "",
  description: "",
  kind: "ssh",
  host: "",
  port: "22",
  queueKey: "",
  gatewayEnabled: false,
  gatewayHost: "",
  gatewayPort: "22",
  gatewayAuthMethod: "key",
  generated: false,
};

function machineToForm(preset: MachinePreset): MachineForm {
  return {
    id: preset.id,
    name: preset.name,
    description: preset.description ?? "",
    kind: preset.kind,
    host: preset.host ?? "",
    port: String(preset.port ?? 22),
    queueKey: preset.queue_key ?? "",
    gatewayEnabled: preset.gateway != null,
    gatewayHost: preset.gateway?.host ?? "",
    gatewayPort: String(preset.gateway?.port ?? 22),
    gatewayAuthMethod: preset.gateway?.auth_method ?? "key",
    generated: preset.generated,
  };
}

function parseMachineForm(form: MachineForm): { preset?: MachinePreset; error?: string } {
  const idError = validateId(form.id);
  if (idError) return { error: idError };
  if (!form.name.trim()) return { error: "Name is required." };
  const port = intFromString(form.port, "SSH port", 1);
  if (port.error) return { error: port.error };
  if ((port.value ?? 0) > 65535) return { error: "SSH port must be <= 65535." };
  if (form.kind === "ssh" && !form.host.trim()) {
    return { error: "SSH machines require a host." };
  }
  const gatewayPort = intFromString(form.gatewayPort, "Gateway port", 1);
  if (form.gatewayEnabled && gatewayPort.error) return { error: gatewayPort.error };
  if (form.gatewayEnabled && (gatewayPort.value ?? 0) > 65535) {
    return { error: "Gateway port must be <= 65535." };
  }
  if (form.gatewayEnabled && !form.gatewayHost.trim()) {
    return { error: "Gateway host is required when gateway is enabled." };
  }
  return {
    preset: {
      id: form.id.trim(),
      name: form.name.trim(),
      description: emptyToNull(form.description),
      kind: form.kind,
      host: form.kind === "ssh" ? form.host.trim() : null,
      port: port.value ?? 22,
      queue_key: emptyToNull(form.queueKey),
      gateway:
        form.kind === "ssh" && form.gatewayEnabled
          ? {
              host: form.gatewayHost.trim(),
              port: gatewayPort.value ?? 22,
              auth_method: form.gatewayAuthMethod,
            }
          : null,
      generated: form.generated,
    },
  };
}

interface SlurmForm {
  id: string;
  name: string;
  description: string;
  mode: "typed" | "raw";
  partition: string;
  nodes: string;
  tasksPerNode: string;
  cpusPerTask: string;
  gpus: string;
  gpusPerTask: string;
  account: string;
  cluster: string;
  time: string;
  extraArgsText: string;
  slurmArgsText: string;
  commandTimeout: string;
  sallocTimeout: string;
  generated: boolean;
}

const EMPTY_SLURM_FORM: SlurmForm = {
  id: "",
  name: "",
  description: "",
  mode: "typed",
  partition: "",
  nodes: "",
  tasksPerNode: "",
  cpusPerTask: "",
  gpus: "",
  gpusPerTask: "",
  account: "",
  cluster: "",
  time: "",
  extraArgsText: "",
  slurmArgsText: "",
  commandTimeout: "0",
  sallocTimeout: "0",
  generated: false,
};

function slurmToForm(preset: SlurmPreset): SlurmForm {
  const slurm = preset.slurm;
  return {
    id: preset.id,
    name: preset.name,
    description: preset.description ?? "",
    mode: slurm ? "typed" : "raw",
    partition: slurm?.partition ?? "",
    nodes: slurm?.nodes == null ? "" : String(slurm.nodes),
    tasksPerNode:
      slurm?.tasks_per_node == null ? "" : String(slurm.tasks_per_node),
    cpusPerTask:
      slurm?.cpus_per_task == null ? "" : String(slurm.cpus_per_task),
    gpus: slurm?.gpus == null ? "" : String(slurm.gpus),
    gpusPerTask:
      slurm?.gpus_per_task == null ? "" : String(slurm.gpus_per_task),
    account: slurm?.account ?? "",
    cluster: slurm?.cluster ?? "",
    time: slurm?.time ?? "",
    extraArgsText: arrayToLines(slurm?.extra_args),
    slurmArgsText: arrayToLines(preset.slurm_args),
    commandTimeout: String(preset.command_timeout),
    sallocTimeout: String(preset.salloc_timeout),
    generated: preset.generated,
  };
}

function optionalIntField(formValue: string, label: string) {
  return intFromString(formValue, label, 1, true);
}

function parseSlurmForm(form: SlurmForm): { preset?: SlurmPreset; error?: string } {
  const idError = validateId(form.id);
  if (idError) return { error: idError };
  if (!form.name.trim()) return { error: "Name is required." };
  const commandTimeout = intFromString(form.commandTimeout, "Command timeout", 0);
  if (commandTimeout.error) return { error: commandTimeout.error };
  const sallocTimeout = intFromString(form.sallocTimeout, "salloc timeout", 0);
  if (sallocTimeout.error) return { error: sallocTimeout.error };

  if (form.mode === "raw") {
    const slurmArgs = linesToArray(form.slurmArgsText);
    if (!slurmArgs.length) return { error: "Raw Slurm args require at least one argument." };
    return {
      preset: {
        id: form.id.trim(),
        name: form.name.trim(),
        description: emptyToNull(form.description),
        slurm: null,
        slurm_args: slurmArgs,
        command_timeout: commandTimeout.value ?? 0,
        salloc_timeout: sallocTimeout.value ?? 0,
        generated: form.generated,
      },
    };
  }

  const nodes = optionalIntField(form.nodes, "Nodes");
  const tasks = optionalIntField(form.tasksPerNode, "Tasks per node");
  const cpus = optionalIntField(form.cpusPerTask, "CPUs per task");
  const gpus = optionalIntField(form.gpus, "GPUs");
  const gpusPerTask = optionalIntField(form.gpusPerTask, "GPUs per task");
  for (const parsed of [nodes, tasks, cpus, gpus, gpusPerTask]) {
    if (parsed.error) return { error: parsed.error };
  }

  return {
    preset: {
      id: form.id.trim(),
      name: form.name.trim(),
      description: emptyToNull(form.description),
      slurm: {
        partition: emptyToNull(form.partition),
        nodes: nodes.value,
        tasks_per_node: tasks.value,
        cpus_per_task: cpus.value,
        gpus: gpus.value,
        gpus_per_task: gpusPerTask.value,
        account: emptyToNull(form.account),
        cluster: emptyToNull(form.cluster),
        time: emptyToNull(form.time),
        extra_args: linesToArray(form.extraArgsText),
      },
      slurm_args: [],
      command_timeout: commandTimeout.value ?? 0,
      salloc_timeout: sallocTimeout.value ?? 0,
      generated: form.generated,
    },
  };
}

function MachinePresetsCard({
  machinePresets,
  slurmPresets,
  saving,
  onSaveMachine,
  onDeleteMachine,
  onSaveSlurm,
  onDeleteSlurm,
}: {
  machinePresets: MachinePreset[];
  slurmPresets: SlurmPreset[];
  saving: boolean;
  onSaveMachine: SavePreset<MachinePreset>;
  onDeleteMachine: DeletePreset;
  onSaveSlurm: SavePreset<SlurmPreset>;
  onDeleteSlurm: DeletePreset;
}) {
  const [machineForm, setMachineForm] = useState<MachineForm | null>(null);
  const [machineEditingId, setMachineEditingId] = useState<string | null>(null);
  const [machineError, setMachineError] = useState<string | null>(null);
  const [slurmForm, setSlurmForm] = useState<SlurmForm | null>(null);
  const [slurmEditingId, setSlurmEditingId] = useState<string | null>(null);
  const [slurmError, setSlurmError] = useState<string | null>(null);

  async function submitMachine() {
    if (!machineForm) return;
    const parsed = parseMachineForm(machineForm);
    if (parsed.error || !parsed.preset) {
      setMachineError(parsed.error ?? "Invalid machine preset.");
      return;
    }
    setMachineError(null);
    await onSaveMachine(parsed.preset);
    setMachineForm(null);
    setMachineEditingId(null);
  }

  async function submitSlurm() {
    if (!slurmForm) return;
    const parsed = parseSlurmForm(slurmForm);
    if (parsed.error || !parsed.preset) {
      setSlurmError(parsed.error ?? "Invalid Slurm preset.");
      return;
    }
    setSlurmError(null);
    await onSaveSlurm(parsed.preset);
    setSlurmForm(null);
    setSlurmEditingId(null);
  }

  async function removeMachine(preset: MachinePreset) {
    if (
      window.confirm(
        `Delete machine preset "${preset.name}"? Profiles that reference it will become invalid.`,
      )
    ) {
      await onDeleteMachine(preset.id);
    }
  }

  async function removeSlurm(preset: SlurmPreset) {
    if (
      window.confirm(
        `Delete Slurm preset "${preset.name}"? Profiles that reference it will become invalid.`,
      )
    ) {
      await onDeleteSlurm(preset.id);
    }
  }

  return (
    <div className="bg-surface border border-border rounded-xl p-4 sm:p-6 space-y-6">
      <SectionHeader
        icon={<Server size={18} />}
        title="Machine Presets"
        count={machinePresets.length}
      >
        {!machineForm && (
          <button
            type="button"
            onClick={() => {
              setMachineForm(EMPTY_MACHINE_FORM);
              setMachineEditingId(null);
              setMachineError(null);
            }}
            className={actionButtonCls("primary")}
          >
            <Plus size={14} />
            Add machine
          </button>
        )}
      </SectionHeader>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {machinePresets.map((preset) => (
          <div key={preset.id} className="rounded-lg border border-border bg-bg p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h4 className="truncate text-sm font-medium text-fg">{preset.name}</h4>
                <p className="mt-0.5 font-mono text-xs text-muted">{preset.id}</p>
              </div>
              <div className="flex shrink-0 gap-1">
                <button
                  type="button"
                  aria-label={`Edit machine ${preset.name}`}
                  onClick={() => {
                    setMachineForm(machineToForm(preset));
                    setMachineEditingId(preset.id);
                    setMachineError(null);
                  }}
                  className="rounded-md p-1.5 text-muted hover:text-fg"
                >
                  <Edit3 size={14} />
                </button>
                <button
                  type="button"
                  aria-label={`Delete machine ${preset.name}`}
                  onClick={() => void removeMachine(preset)}
                  className="rounded-md p-1.5 text-muted hover:text-failed"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
            {preset.description && <p className="mt-2 text-xs text-muted">{preset.description}</p>}
            <div className="mt-3 flex flex-wrap gap-2">
              <Pill tone={preset.kind === "ssh" ? "accent" : "muted"}>{preset.kind}</Pill>
              <Pill tone={preset.generated ? "muted" : "accent"}>
                {generatedLabel(preset.generated)}
              </Pill>
              {preset.host && <Pill>{preset.host}:{preset.port}</Pill>}
              {preset.queue_key && <Pill>queue {preset.queue_key}</Pill>}
              {preset.gateway && (
                <Pill tone={preset.gateway.auth_method === "interactive" ? "warn" : "muted"}>
                  gateway {preset.gateway.host} ({preset.gateway.auth_method})
                </Pill>
              )}
            </div>
          </div>
        ))}
      </div>

      {machineForm && (
        <MachinePresetForm
          form={machineForm}
          editing={machineEditingId !== null}
          error={machineError}
          saving={saving}
          onChange={setMachineForm}
          onCancel={() => {
            setMachineForm(null);
            setMachineEditingId(null);
            setMachineError(null);
          }}
          onSubmit={() => void submitMachine()}
        />
      )}

      <div className="border-t border-border pt-6">
        <SectionHeader
          icon={<TerminalSquare size={18} />}
          title="Slurm Presets"
          count={slurmPresets.length}
        >
          {!slurmForm && (
            <button
              type="button"
              onClick={() => {
                setSlurmForm(EMPTY_SLURM_FORM);
                setSlurmEditingId(null);
                setSlurmError(null);
              }}
              className={actionButtonCls("primary")}
            >
              <Plus size={14} />
              Add Slurm
            </button>
          )}
        </SectionHeader>
        <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-2">
          {slurmPresets.map((preset) => (
            <div key={preset.id} className="rounded-lg border border-border bg-bg p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h4 className="truncate text-sm font-medium text-fg">{preset.name}</h4>
                  <p className="mt-0.5 font-mono text-xs text-muted">{preset.id}</p>
                </div>
                <div className="flex shrink-0 gap-1">
                  <button
                    type="button"
                    aria-label={`Edit Slurm ${preset.name}`}
                    onClick={() => {
                      setSlurmForm(slurmToForm(preset));
                      setSlurmEditingId(preset.id);
                      setSlurmError(null);
                    }}
                    className="rounded-md p-1.5 text-muted hover:text-fg"
                  >
                    <Edit3 size={14} />
                  </button>
                  <button
                    type="button"
                    aria-label={`Delete Slurm ${preset.name}`}
                    onClick={() => void removeSlurm(preset)}
                    className="rounded-md p-1.5 text-muted hover:text-failed"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
              {preset.description && <p className="mt-2 text-xs text-muted">{preset.description}</p>}
              <div className="mt-3 flex flex-wrap gap-2">
                <Pill tone={preset.slurm ? "accent" : "warn"}>
                  {preset.slurm ? "typed" : "raw args"}
                </Pill>
                <Pill tone={preset.generated ? "muted" : "accent"}>
                  {generatedLabel(preset.generated)}
                </Pill>
                {preset.slurm?.partition && <Pill>{preset.slurm.partition}</Pill>}
                {preset.slurm?.cluster && <Pill>cluster {preset.slurm.cluster}</Pill>}
                {preset.slurm?.time && <Pill>{preset.slurm.time}</Pill>}
                {preset.slurm?.cpus_per_task != null && (
                  <Pill>{preset.slurm.cpus_per_task} cpus/task</Pill>
                )}
                {preset.slurm_args.length > 0 && <Pill>{preset.slurm_args.length} args</Pill>}
              </div>
            </div>
          ))}
        </div>
        {slurmForm && (
          <SlurmPresetForm
            form={slurmForm}
            editing={slurmEditingId !== null}
            error={slurmError}
            saving={saving}
            onChange={setSlurmForm}
            onCancel={() => {
              setSlurmForm(null);
              setSlurmEditingId(null);
              setSlurmError(null);
            }}
            onSubmit={() => void submitSlurm()}
          />
        )}
      </div>
    </div>
  );
}

function MachinePresetForm({
  form,
  editing,
  error,
  saving,
  onChange,
  onCancel,
  onSubmit,
}: {
  form: MachineForm;
  editing: boolean;
  error: string | null;
  saving: boolean;
  onChange: (form: MachineForm) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  return (
    <div className="rounded-lg border border-border bg-bg p-4">
      <div className="mb-4 flex items-center justify-between">
        <h4 className="text-sm font-medium text-fg">
          {editing ? `Edit ${form.name}` : "New machine preset"}
        </h4>
        <button type="button" onClick={onCancel} className="text-muted hover:text-fg">
          <X size={16} />
        </button>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="ID">
          <input
            value={form.id}
            disabled={editing}
            onChange={(e) => onChange({ ...form, id: e.target.value })}
            className={inputCls}
          />
        </Field>
        <Field label="Name">
          <input
            value={form.name}
            onChange={(e) => onChange({ ...form, name: e.target.value })}
            className={inputCls}
          />
        </Field>
        <Field label="Kind">
          <select
            value={form.kind}
            onChange={(e) =>
              onChange({ ...form, kind: e.target.value as "local" | "ssh" })
            }
            className={selectCls}
          >
            <option value="local">Local</option>
            <option value="ssh">SSH</option>
          </select>
        </Field>
        <Field label="Queue key">
          <input
            value={form.queueKey}
            onChange={(e) => onChange({ ...form, queueKey: e.target.value })}
            className={inputCls}
          />
        </Field>
        <div className="sm:col-span-2">
          <Field label="Description">
            <input
              value={form.description}
              onChange={(e) => onChange({ ...form, description: e.target.value })}
              className={inputCls}
            />
          </Field>
        </div>
        {form.kind === "ssh" && (
          <>
            <Field label="Host">
              <input
                value={form.host}
                onChange={(e) => onChange({ ...form, host: e.target.value })}
                className={inputCls}
              />
            </Field>
            <Field label="Port">
              <input
                type="number"
                min={1}
                max={65535}
                value={form.port}
                onChange={(e) => onChange({ ...form, port: e.target.value })}
                className={inputCls}
              />
            </Field>
            <label className="flex items-center gap-2 text-sm text-fg sm:col-span-2">
              <input
                type="checkbox"
                checked={form.gatewayEnabled}
                onChange={(e) =>
                  onChange({ ...form, gatewayEnabled: e.target.checked })
                }
                className="h-4 w-4 accent-accent"
              />
              Use SSH gateway
            </label>
            {form.gatewayEnabled && (
              <>
                <Field label="Gateway host">
                  <input
                    value={form.gatewayHost}
                    onChange={(e) => onChange({ ...form, gatewayHost: e.target.value })}
                    className={inputCls}
                  />
                </Field>
                <Field label="Gateway port">
                  <input
                    type="number"
                    min={1}
                    max={65535}
                    value={form.gatewayPort}
                    onChange={(e) => onChange({ ...form, gatewayPort: e.target.value })}
                    className={inputCls}
                  />
                </Field>
                <Field label="Gateway auth">
                  <select
                    value={form.gatewayAuthMethod}
                    onChange={(e) =>
                      onChange({
                        ...form,
                        gatewayAuthMethod: e.target.value as "key" | "interactive",
                      })
                    }
                    className={selectCls}
                  >
                    <option value="key">SSH key</option>
                    <option value="interactive">Password + 2FA</option>
                  </select>
                </Field>
              </>
            )}
          </>
        )}
      </div>
      {error && <p className="mt-3 text-sm text-failed">{error}</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" onClick={onSubmit} disabled={saving} className={actionButtonCls("primary")}>
          <Save size={14} />
          Save machine
        </button>
        <button type="button" onClick={onCancel} className={actionButtonCls("secondary")}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function SlurmPresetForm({
  form,
  editing,
  error,
  saving,
  onChange,
  onCancel,
  onSubmit,
}: {
  form: SlurmForm;
  editing: boolean;
  error: string | null;
  saving: boolean;
  onChange: (form: SlurmForm) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  return (
    <div className="mt-4 rounded-lg border border-border bg-bg p-4">
      <div className="mb-4 flex items-center justify-between">
        <h4 className="text-sm font-medium text-fg">
          {editing ? `Edit ${form.name}` : "New Slurm preset"}
        </h4>
        <button type="button" onClick={onCancel} className="text-muted hover:text-fg">
          <X size={16} />
        </button>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="ID">
          <input
            value={form.id}
            disabled={editing}
            onChange={(e) => onChange({ ...form, id: e.target.value })}
            className={inputCls}
          />
        </Field>
        <Field label="Name">
          <input
            value={form.name}
            onChange={(e) => onChange({ ...form, name: e.target.value })}
            className={inputCls}
          />
        </Field>
        <Field label="Mode">
          <select
            value={form.mode}
            onChange={(e) =>
              onChange({ ...form, mode: e.target.value as "typed" | "raw" })
            }
            className={selectCls}
          >
            <option value="typed">Typed resources</option>
            <option value="raw">Raw Slurm args</option>
          </select>
        </Field>
        <Field label="Command timeout">
          <input
            type="number"
            min={0}
            value={form.commandTimeout}
            onChange={(e) => onChange({ ...form, commandTimeout: e.target.value })}
            className={inputCls}
          />
        </Field>
        <Field label="salloc timeout">
          <input
            type="number"
            min={0}
            value={form.sallocTimeout}
            onChange={(e) => onChange({ ...form, sallocTimeout: e.target.value })}
            className={inputCls}
          />
        </Field>
        <div className="sm:col-span-2">
          <Field label="Description">
            <input
              value={form.description}
              onChange={(e) => onChange({ ...form, description: e.target.value })}
              className={inputCls}
            />
          </Field>
        </div>
      </div>
      {form.mode === "raw" ? (
        <div className="mt-3">
          <div className="rounded-md border border-yellow-500/30 bg-yellow-500/10 px-3 py-2 text-xs text-yellow-200">
            Raw Slurm args remain compatible, but manual Slurm overrides are not available for profiles using them.
          </div>
          <div className="mt-3">
            <Field label="Raw Slurm args">
              <textarea
                rows={7}
                value={form.slurmArgsText}
                onChange={(e) => onChange({ ...form, slurmArgsText: e.target.value })}
                className={textareaCls}
                spellCheck={false}
              />
            </Field>
          </div>
        </div>
      ) : (
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Partition">
            <input
              value={form.partition}
              onChange={(e) => onChange({ ...form, partition: e.target.value })}
              className={inputCls}
            />
          </Field>
          <Field label="Account">
            <input
              value={form.account}
              onChange={(e) => onChange({ ...form, account: e.target.value })}
              className={inputCls}
            />
          </Field>
          <Field label="Cluster">
            <input
              value={form.cluster}
              onChange={(e) => onChange({ ...form, cluster: e.target.value })}
              className={inputCls}
            />
          </Field>
          <Field label="Time">
            <input
              value={form.time}
              onChange={(e) => onChange({ ...form, time: e.target.value })}
              className={inputCls}
            />
          </Field>
          <Field label="Nodes">
            <input
              type="number"
              min={1}
              value={form.nodes}
              onChange={(e) => onChange({ ...form, nodes: e.target.value })}
              className={inputCls}
            />
          </Field>
          <Field label="Tasks per node">
            <input
              type="number"
              min={1}
              value={form.tasksPerNode}
              onChange={(e) => onChange({ ...form, tasksPerNode: e.target.value })}
              className={inputCls}
            />
          </Field>
          <Field label="CPUs per task">
            <input
              type="number"
              min={1}
              value={form.cpusPerTask}
              onChange={(e) => onChange({ ...form, cpusPerTask: e.target.value })}
              className={inputCls}
            />
          </Field>
          <Field label="GPUs">
            <input
              type="number"
              min={1}
              value={form.gpus}
              onChange={(e) => onChange({ ...form, gpus: e.target.value })}
              className={inputCls}
            />
          </Field>
          <Field label="GPUs per task">
            <input
              type="number"
              min={1}
              value={form.gpusPerTask}
              onChange={(e) => onChange({ ...form, gpusPerTask: e.target.value })}
              className={inputCls}
            />
          </Field>
          <div className="sm:col-span-2">
            <Field label="Extra args">
              <textarea
                rows={5}
                value={form.extraArgsText}
                onChange={(e) => onChange({ ...form, extraArgsText: e.target.value })}
                className={textareaCls}
                spellCheck={false}
              />
            </Field>
          </div>
        </div>
      )}
      {error && <p className="mt-3 text-sm text-failed">{error}</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" onClick={onSubmit} disabled={saving} className={actionButtonCls("primary")}>
          <Save size={14} />
          Save Slurm
        </button>
        <button type="button" onClick={onCancel} className={actionButtonCls("secondary")}>
          Cancel
        </button>
      </div>
    </div>
  );
}

interface EnvForm {
  id: string;
  name: string;
  description: string;
  style: "none" | "modules" | "prologue" | "uenv";
  lmodInit: string;
  moduleUsePathsText: string;
  moduleLoadsText: string;
  prologue: string;
  generated: boolean;
}

const EMPTY_ENV_FORM: EnvForm = {
  id: "",
  name: "",
  description: "",
  style: "modules",
  lmodInit: DEFAULT_LMOD_INIT,
  moduleUsePathsText: "",
  moduleLoadsText: "",
  prologue: "",
  generated: false,
};

function envToForm(preset: EnvPreset): EnvForm {
  return {
    id: preset.id,
    name: preset.name,
    description: preset.description ?? "",
    style: preset.env.style,
    lmodInit: preset.env.lmod_init ?? DEFAULT_LMOD_INIT,
    moduleUsePathsText: arrayToLines(preset.env.module_use_paths),
    moduleLoadsText: arrayToLines(preset.env.module_loads),
    prologue: preset.env.prologue ?? "",
    generated: preset.generated,
  };
}

function parseEnvForm(form: EnvForm): { preset?: EnvPreset; error?: string } {
  const idError = validateId(form.id);
  if (idError) return { error: idError };
  if (!form.name.trim()) return { error: "Name is required." };

  const base = {
    id: form.id.trim(),
    name: form.name.trim(),
    description: emptyToNull(form.description),
    generated: form.generated,
  };
  if (form.style === "modules") {
    return {
      preset: {
        ...base,
        env: {
          style: "modules",
          lmod_init: form.lmodInit.trim() || DEFAULT_LMOD_INIT,
          module_use_paths: linesToArray(form.moduleUsePathsText),
          module_loads: linesToArray(form.moduleLoadsText),
          prologue: null,
        },
      },
    };
  }
  if (form.style === "prologue") {
    return {
      preset: {
        ...base,
        env: {
          style: "prologue",
          lmod_init: DEFAULT_LMOD_INIT,
          module_use_paths: [],
          module_loads: [],
          prologue: emptyToNull(form.prologue),
        },
      },
    };
  }
  if (form.style === "uenv") {
    return {
      preset: {
        ...base,
        env: {
          style: "uenv",
          lmod_init: DEFAULT_LMOD_INIT,
          module_use_paths: [],
          module_loads: [],
          prologue: emptyToNull(form.prologue),
        },
      },
    };
  }
  return {
    preset: {
      ...base,
      env: {
        style: "none",
        lmod_init: DEFAULT_LMOD_INIT,
        module_use_paths: [],
        module_loads: [],
        prologue: null,
      },
    },
  };
}

function EnvironmentPresetsCard({
  presets,
  saving,
  onSave,
  onDelete,
}: {
  presets: EnvPreset[];
  saving: boolean;
  onSave: SavePreset<EnvPreset>;
  onDelete: DeletePreset;
}) {
  const [form, setForm] = useState<EnvForm | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!form) return;
    const parsed = parseEnvForm(form);
    if (parsed.error || !parsed.preset) {
      setError(parsed.error ?? "Invalid environment preset.");
      return;
    }
    setError(null);
    await onSave(parsed.preset);
    setForm(null);
    setEditingId(null);
  }

  async function remove(preset: EnvPreset) {
    if (
      window.confirm(
        `Delete environment preset "${preset.name}"? Profiles that reference it will become invalid.`,
      )
    ) {
      await onDelete(preset.id);
    }
  }

  return (
    <div className="bg-surface border border-border rounded-xl p-4 sm:p-6 space-y-4">
      <SectionHeader
        icon={<Layers3 size={18} />}
        title="Environment Presets"
        count={presets.length}
      >
        {!form && (
          <button
            type="button"
            onClick={() => {
              setForm(EMPTY_ENV_FORM);
              setEditingId(null);
              setError(null);
            }}
            className={actionButtonCls("primary")}
          >
            <Plus size={14} />
            Add environment
          </button>
        )}
      </SectionHeader>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {presets.map((preset) => (
          <EnvironmentPresetCard
            key={preset.id}
            preset={preset}
            onEdit={() => {
              setForm(envToForm(preset));
              setEditingId(preset.id);
              setError(null);
            }}
            onDelete={() => void remove(preset)}
          />
        ))}
      </div>
      {form && (
        <EnvironmentPresetForm
          form={form}
          editing={editingId !== null}
          error={error}
          saving={saving}
          onChange={setForm}
          onCancel={() => {
            setForm(null);
            setEditingId(null);
            setError(null);
          }}
          onSubmit={() => void submit()}
        />
      )}
    </div>
  );
}

function EnvironmentPresetCard({
  preset,
  onEdit,
  onDelete,
}: {
  preset: EnvPreset;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const moduleLoads = preset.env.module_loads ?? [];
  const moduleUsePaths = preset.env.module_use_paths ?? [];

  return (
    <div className="rounded-lg border border-border bg-bg p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h4 className="truncate text-sm font-medium text-fg">{preset.name}</h4>
          <p className="mt-0.5 font-mono text-xs text-muted">{preset.id}</p>
        </div>
        <div className="flex shrink-0 gap-1">
          <button
            type="button"
            aria-label={`Edit environment ${preset.name}`}
            onClick={onEdit}
            className="rounded-md p-1.5 text-muted hover:text-fg"
          >
            <Edit3 size={14} />
          </button>
          <button
            type="button"
            aria-label={`Delete environment ${preset.name}`}
            onClick={onDelete}
            className="rounded-md p-1.5 text-muted hover:text-failed"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>
      {preset.description && <p className="mt-2 text-xs text-muted">{preset.description}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        <Pill tone={preset.env.style === "none" ? "muted" : "accent"}>
          {preset.env.style}
        </Pill>
        <Pill tone={preset.generated ? "muted" : "accent"}>
          {generatedLabel(preset.generated)}
        </Pill>
        {moduleLoads.length > 0 && <Pill>{moduleLoads.length} modules</Pill>}
        {moduleUsePaths.length > 0 && (
          <Pill>{moduleUsePaths.length} module paths</Pill>
        )}
      </div>
    </div>
  );
}

function EnvironmentPresetForm({
  form,
  editing,
  error,
  saving,
  onChange,
  onCancel,
  onSubmit,
}: {
  form: EnvForm;
  editing: boolean;
  error: string | null;
  saving: boolean;
  onChange: (form: EnvForm) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  return (
    <div className="rounded-lg border border-border bg-bg p-4">
      <div className="mb-4 flex items-center justify-between">
        <h4 className="text-sm font-medium text-fg">
          {editing ? `Edit ${form.name}` : "New environment preset"}
        </h4>
        <button type="button" onClick={onCancel} className="text-muted hover:text-fg">
          <X size={16} />
        </button>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="ID">
          <input
            value={form.id}
            disabled={editing}
            onChange={(e) => onChange({ ...form, id: e.target.value })}
            className={inputCls}
          />
        </Field>
        <Field label="Name">
          <input
            value={form.name}
            onChange={(e) => onChange({ ...form, name: e.target.value })}
            className={inputCls}
          />
        </Field>
        <Field label="Style">
          <select
            value={form.style}
            onChange={(e) =>
              onChange({
                ...form,
                style: e.target.value as "none" | "modules" | "prologue" | "uenv",
              })
            }
            className={selectCls}
          >
            <option value="none">None</option>
            <option value="modules">Modules</option>
            <option value="prologue">Prologue</option>
            <option value="uenv">uenv</option>
          </select>
        </Field>
        <div className="sm:col-span-2">
          <Field label="Description">
            <input
              value={form.description}
              onChange={(e) => onChange({ ...form, description: e.target.value })}
              className={inputCls}
            />
          </Field>
        </div>
        {form.style === "modules" && (
          <>
            <Field label="Lmod init">
              <input
                value={form.lmodInit}
                onChange={(e) => onChange({ ...form, lmodInit: e.target.value })}
                className={inputCls}
              />
            </Field>
            <div className="sm:col-span-2">
              <Field label="Module use paths">
                <textarea
                  rows={4}
                  value={form.moduleUsePathsText}
                  onChange={(e) =>
                    onChange({ ...form, moduleUsePathsText: e.target.value })
                  }
                  className={textareaCls}
                  spellCheck={false}
                />
              </Field>
            </div>
            <div className="sm:col-span-2">
              <Field label="Module loads">
                <textarea
                  rows={5}
                  value={form.moduleLoadsText}
                  onChange={(e) => onChange({ ...form, moduleLoadsText: e.target.value })}
                  className={textareaCls}
                  spellCheck={false}
                />
              </Field>
            </div>
          </>
        )}
        {form.style === "prologue" && (
          <div className="sm:col-span-2">
            <Field label="Prologue command">
              <textarea
                rows={5}
                value={form.prologue}
                onChange={(e) => onChange({ ...form, prologue: e.target.value })}
                className={textareaCls}
                spellCheck={false}
              />
            </Field>
          </div>
        )}
        {form.style === "uenv" && (
          <div className="sm:col-span-2">
            <Field label="uenv arguments">
              <textarea
                rows={5}
                value={form.prologue}
                onChange={(e) => onChange({ ...form, prologue: e.target.value })}
                className={textareaCls}
                spellCheck={false}
              />
            </Field>
          </div>
        )}
      </div>
      {error && <p className="mt-3 text-sm text-failed">{error}</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" onClick={onSubmit} disabled={saving} className={actionButtonCls("primary")}>
          <Save size={14} />
          Save environment
        </button>
        <button type="button" onClick={onCancel} className={actionButtonCls("secondary")}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function JsonExport({ settings }: { settings: ExecutionSettings }) {
  const [copied, setCopied] = useState(false);
  const json = useMemo(() => pretty(settings), [settings]);

  async function copyJson() {
    await navigator.clipboard?.writeText(json);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  return (
    <details className="bg-surface border border-border rounded-xl p-4 sm:p-6">
      <summary className="cursor-pointer list-none text-sm font-medium text-fg flex items-center gap-2">
        <Boxes size={16} />
        JSON export
      </summary>
      <div className="mt-4 flex items-center justify-between gap-3">
        <p className="text-xs text-muted">
          Exact saved public settings document.
        </p>
        <button type="button" onClick={() => void copyJson()} className={actionButtonCls("secondary")}>
          <Clipboard size={14} />
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="mt-3 max-h-96 overflow-auto rounded-md border border-border bg-bg p-3 text-xs text-fg">
        {json}
      </pre>
    </details>
  );
}
