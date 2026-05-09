import type { SlurmResourceForm } from "./SlurmResourceFields";

const SLURM_QUERY_KEYS = [
  "slurm_partition",
  "slurm_nodes",
  "slurm_tasks_per_node",
  "slurm_cpus_per_task",
  "slurm_gpus",
  "slurm_gpus_per_task",
];

export function hasSlurmQueryParams(searchParams: URLSearchParams): boolean {
  return SLURM_QUERY_KEYS.some((key) => searchParams.has(key));
}

export function slurmFormFromQuery(
  searchParams: URLSearchParams
): SlurmResourceForm {
  return {
    partition: searchParams.get("slurm_partition") ?? "",
    nodes: searchParams.get("slurm_nodes") ?? "",
    tasks_per_node: searchParams.get("slurm_tasks_per_node") ?? "",
    cpus_per_task: searchParams.get("slurm_cpus_per_task") ?? "",
    gpus: searchParams.get("slurm_gpus") ?? "",
    gpus_per_task: searchParams.get("slurm_gpus_per_task") ?? "",
  };
}
