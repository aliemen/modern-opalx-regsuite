import type { SlurmResources } from "../../api/runs";

export interface SlurmResourceForm {
  partition: string;
  nodes: string;
  tasks_per_node: string;
  cpus_per_task: string;
  gpus: string;
  gpus_per_task: string;
}

interface SlurmResourceFieldsProps {
  form: SlurmResourceForm;
  enabled: boolean;
  supported: boolean;
  dirty: boolean;
  onChange: (next: SlurmResourceForm) => void;
  onReset: () => void;
}

const fieldCls =
  "w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent";

export function formFromSlurmDefaults(
  defaults: SlurmResources | null | undefined,
  mpiRanks: number
): SlurmResourceForm {
  const tasksPerNode = defaults?.tasks_per_node ?? null;
  const gpusPerTask = defaults?.gpus_per_task ?? null;
  return {
    partition: defaults?.partition ?? "",
    nodes: String(defaults?.nodes ?? (tasksPerNode ? Math.ceil(mpiRanks / tasksPerNode) : "")),
    tasks_per_node: String(tasksPerNode ?? ""),
    cpus_per_task: String(defaults?.cpus_per_task ?? ""),
    gpus: String(defaults?.gpus ?? (gpusPerTask ? mpiRanks * gpusPerTask : "")),
    gpus_per_task: String(gpusPerTask ?? ""),
  };
}

export function slurmResourcesFromForm(form: SlurmResourceForm): SlurmResources {
  return {
    partition: form.partition.trim() || null,
    nodes: parseNullableInt(form.nodes),
    tasks_per_node: parseNullableInt(form.tasks_per_node),
    cpus_per_task: parseNullableInt(form.cpus_per_task),
    gpus: parseNullableInt(form.gpus),
    gpus_per_task: parseNullableInt(form.gpus_per_task),
  };
}

export function parseNullableInt(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number.parseInt(trimmed, 10);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

export function validateSlurmForm(form: SlurmResourceForm, mpiRanks: number): string | null {
  const resources = slurmResourcesFromForm(form);
  for (const [key, value] of Object.entries(resources)) {
    if (key === "partition" || value == null) continue;
    if (!Number.isInteger(value) || value < 1) {
      return `${labelFor(key)} must be a positive integer or blank.`;
    }
  }
  if (
    resources.nodes != null &&
    resources.tasks_per_node != null &&
    mpiRanks > resources.nodes * resources.tasks_per_node
  ) {
    return "MPI ranks cannot exceed nodes * tasks per node.";
  }
  return null;
}

function labelFor(key: string): string {
  switch (key) {
    case "nodes":
      return "Nodes";
    case "tasks_per_node":
      return "Tasks per node";
    case "cpus_per_task":
      return "CPUs per task";
    case "gpus":
      return "GPUs";
    case "gpus_per_task":
      return "GPUs per task";
    default:
      return key;
  }
}

export function SlurmResourceFields({
  form,
  enabled,
  supported,
  dirty,
  onChange,
  onReset,
}: SlurmResourceFieldsProps) {
  if (!enabled) return null;
  if (!supported) {
    return (
      <div className="rounded-md border border-border bg-bg px-3 py-2 text-xs text-muted">
        This run config uses legacy slurm_args. Convert it to [arch_configs.slurm]
        before using manual Slurm overrides.
      </div>
    );
  }

  function setField(field: keyof SlurmResourceForm, value: string) {
    onChange({ ...form, [field]: value });
  }

  return (
    <div className="border-t border-border pt-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-fg">Slurm resources</h3>
          <p className="text-xs text-muted">
            Blank fields clear inherited resource defaults for this run.
          </p>
        </div>
        <button
          type="button"
          onClick={onReset}
          className="shrink-0 rounded-md border border-border px-3 py-1.5 text-xs text-muted hover:text-fg"
        >
          Reset to defaults
        </button>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="slurm-partition" className="block text-xs text-muted mb-1">
            Partition
          </label>
          <input
            id="slurm-partition"
            type="text"
            value={form.partition}
            onChange={(e) => setField("partition", e.target.value)}
            className={fieldCls}
          />
        </div>
        <div>
          <label htmlFor="slurm-nodes" className="block text-xs text-muted mb-1">
            Nodes
          </label>
          <input
            id="slurm-nodes"
            type="number"
            min={1}
            value={form.nodes}
            onChange={(e) => setField("nodes", e.target.value)}
            className={fieldCls}
          />
        </div>
        <div>
          <label
            htmlFor="slurm-tasks-per-node"
            className="block text-xs text-muted mb-1"
          >
            Tasks per node
          </label>
          <input
            id="slurm-tasks-per-node"
            type="number"
            min={1}
            value={form.tasks_per_node}
            onChange={(e) => setField("tasks_per_node", e.target.value)}
            className={fieldCls}
          />
        </div>
        <div>
          <label
            htmlFor="slurm-cpus-per-task"
            className="block text-xs text-muted mb-1"
          >
            CPUs per task
          </label>
          <input
            id="slurm-cpus-per-task"
            type="number"
            min={1}
            value={form.cpus_per_task}
            onChange={(e) => setField("cpus_per_task", e.target.value)}
            className={fieldCls}
          />
        </div>
        <div>
          <label htmlFor="slurm-gpus" className="block text-xs text-muted mb-1">
            GPUs
          </label>
          <input
            id="slurm-gpus"
            type="number"
            min={1}
            value={form.gpus}
            onChange={(e) => setField("gpus", e.target.value)}
            className={fieldCls}
          />
        </div>
        <div>
          <label
            htmlFor="slurm-gpus-per-task"
            className="block text-xs text-muted mb-1"
          >
            GPUs per task
          </label>
          <input
            id="slurm-gpus-per-task"
            type="number"
            min={1}
            value={form.gpus_per_task}
            onChange={(e) => setField("gpus_per_task", e.target.value)}
            className={fieldCls}
          />
        </div>
      </div>
      {dirty && (
        <p className="text-xs text-accent mt-2">
          Manual Slurm resources will be used for this run.
        </p>
      )}
    </div>
  );
}
