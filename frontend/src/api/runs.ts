import { api } from "./client";

export interface CurrentRunStatus {
  run_id: string;
  branch: string;
  arch: string;
  status: string;
  phase: string;
  started_at: string;
  machine_id: string | null;
  connection_name?: string | null;
}

export interface TriggerRequest {
  branch: string;
  arch: string;
  regtests_branch?: string;
  skip_unit?: boolean;
  skip_regression?: boolean;
  /**
   * Name of the per-user Connection to run on. Use `null` or `"local"` for
   * local execution. Connections are managed in Settings.
   */
  connection_name?: string | null;
}

export interface TriggerResponse {
  run_id: string;
  queued: boolean;
  queue_id: string | null;
  position: number | null;
}

export interface QueuedRunItem {
  queue_id: string;
  run_id: string;
  branch: string;
  arch: string;
  queued_at: string;
}

export interface MachineStatus {
  machine_id: string;
  active_run: CurrentRunStatus | null;
  queue: QueuedRunItem[];
}

export interface QueueStateResponse {
  machines: MachineStatus[];
}

export interface DashboardStats {
  last_run: string | null;
  last_run_branch: string | null;
  last_run_arch: string | null;
  last_run_status: string | null;
  last_run_id: string | null;
  runs_total: number;
  runs_last_week: number;
  branches_covered: number;
  avg_unit_pass_rate_master: number | null;
  avg_regression_pass_rate_master: number | null;
}

export async function getCurrentRun(): Promise<CurrentRunStatus | null> {
  const res = await api.get<CurrentRunStatus | null>("/api/runs/current");
  return res.data;
}

export async function getActiveRuns(): Promise<CurrentRunStatus[]> {
  const res = await api.get<CurrentRunStatus[]>("/api/runs/active");
  return res.data;
}

export async function getQueueState(): Promise<QueueStateResponse> {
  const res = await api.get<QueueStateResponse>("/api/runs/queue");
  return res.data;
}

export async function triggerRun(body: TriggerRequest): Promise<TriggerResponse> {
  const res = await api.post<TriggerResponse>("/api/runs/trigger", body);
  return res.data;
}

export async function cancelRun(): Promise<void> {
  await api.post("/api/runs/current/cancel");
}

export async function cancelRunById(runId: string): Promise<void> {
  await api.post(`/api/runs/${runId}/cancel`);
}

export async function cancelQueuedRun(queueId: string): Promise<void> {
  await api.delete(`/api/runs/queue/${queueId}`);
}

export async function getDashboardStats(): Promise<DashboardStats> {
  const res = await api.get<DashboardStats>("/api/stats");
  return res.data;
}

export async function getArchConfigs(): Promise<string[]> {
  const res = await api.get<string[]>("/api/runs/archs");
  return res.data;
}

export async function getOpalxBranches(): Promise<string[]> {
  const res = await api.get<{ branches: string[] }>("/api/branches/opalx");
  return res.data.branches;
}

export async function getRegtestsBranches(): Promise<string[]> {
  const res = await api.get<{ branches: string[] }>("/api/branches/regtests");
  return res.data.branches;
}
