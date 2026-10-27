/* eslint-disable react-refresh/only-export-components */
import type { SlurmResources } from "../../api/runs";
import { Fact } from "./RunFacts";

interface SlurmResourceSummaryProps {
  resources: SlurmResources | null;
}

export function addSlurmRerunParams(
  params: URLSearchParams,
  resources: SlurmResources | null
) {
  if (!resources) return;
  const slurmParamMap = {
    slurm_partition: resources.partition,
    slurm_nodes: resources.nodes,
    slurm_tasks_per_node: resources.tasks_per_node,
    slurm_cpus_per_task: resources.cpus_per_task,
    slurm_gpus: resources.gpus,
    slurm_gpus_per_task: resources.gpus_per_task,
  };
  for (const [key, value] of Object.entries(slurmParamMap)) {
    params.set(key, value == null ? "" : String(value));
  }
}

export function SlurmResourceSummary({ resources }: SlurmResourceSummaryProps) {
  if (!resources) return null;
  const parts = [
    resources.partition ? `partition=${resources.partition}` : null,
    resources.nodes != null ? `nodes=${resources.nodes}` : null,
    resources.tasks_per_node != null
      ? `tasks/node=${resources.tasks_per_node}`
      : null,
    resources.cpus_per_task != null
      ? `cpus/task=${resources.cpus_per_task}`
      : null,
    resources.gpus != null ? `gpus=${resources.gpus}` : null,
    resources.gpus_per_task != null
      ? `gpus/task=${resources.gpus_per_task}`
      : null,
  ].filter(Boolean);

  return (
    <Fact label="Slurm Resources">
      <span className="text-xs">{parts.join(" / ")}</span>
    </Fact>
  );
}
