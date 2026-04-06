import { api } from "./client";

export interface CurrentRunStatus {
  run_id: string;
  branch: string;
  arch: string;
  status: string;
  phase: string;
  started_at: string;
}

export interface TriggerRequest {
  branch: string;
  arch: string;
  regtests_branch?: string;
  skip_unit?: boolean;
  skip_regression?: boolean;
}

export async function getCurrentRun(): Promise<CurrentRunStatus | null> {
  const res = await api.get<CurrentRunStatus | null>("/api/runs/current");
  return res.data;
}

export async function triggerRun(body: TriggerRequest): Promise<{ run_id: string }> {
  const res = await api.post<{ run_id: string }>("/api/runs/trigger", body);
  return res.data;
}

export async function cancelRun(): Promise<void> {
  await api.post("/api/runs/current/cancel");
}

export async function getOpalxBranches(): Promise<string[]> {
  const res = await api.get<{ branches: string[] }>("/api/branches/opalx");
  return res.data.branches;
}

export async function getRegtestsBranches(): Promise<string[]> {
  const res = await api.get<{ branches: string[] }>("/api/branches/regtests");
  return res.data.branches;
}
