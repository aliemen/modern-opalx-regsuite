import { api } from "./client";
import type { EnvActivation, GatewayAuthMethod } from "./connections";
import type { SlurmResources } from "./runs";

export interface BuildPreset {
  id: string;
  name: string;
  description?: string | null;
  cmake_args?: string[] | null;
  build_jobs: number;
  mpi_ranks: number;
  max_mpi_ranks?: number | null;
  opalx_info_level?: number | null;
  generated: boolean;
}

export interface MachineGatewayPreset {
  host: string;
  port: number;
  auth_method: GatewayAuthMethod;
}

export interface MachinePreset {
  id: string;
  name: string;
  description?: string | null;
  kind: "local" | "ssh";
  host?: string | null;
  port: number;
  gateway?: MachineGatewayPreset | null;
  queue_key?: string | null;
  generated: boolean;
}

export interface EnvPreset {
  id: string;
  name: string;
  description?: string | null;
  env: EnvActivation;
  generated: boolean;
}

export interface SlurmPreset {
  id: string;
  name: string;
  description?: string | null;
  slurm?: {
    partition?: string | null;
    nodes?: number | null;
    tasks_per_node?: number | null;
    cpus_per_task?: number | null;
    gpus?: number | null;
    gpus_per_task?: number | null;
    account?: string | null;
    cluster?: string | null;
    time?: string | null;
    extra_args: string[];
  } | null;
  slurm_args: string[];
  command_timeout: number;
  salloc_timeout: number;
  generated: boolean;
}

export interface ExecutionSettings {
  version: number;
  build_presets: BuildPreset[];
  machine_presets: MachinePreset[];
  env_presets: EnvPreset[];
  slurm_presets: SlurmPreset[];
  created_at?: string | null;
  modified_at?: string | null;
}

export interface RunProfile {
  id: string;
  name: string;
  description?: string | null;
  build_preset_id: string;
  machine_preset_id: string;
  env_preset_id?: string | null;
  slurm_preset_id?: string | null;
  ssh_user?: string | null;
  key_name?: string | null;
  gateway_user?: string | null;
  gateway_key_name?: string | null;
  work_dir: string;
  cleanup_after_run: boolean;
  keepalive_interval: number;
  generated: boolean;
}

export interface RunProfileSummary {
  id: string;
  name: string;
  description?: string | null;
  arch: string;
  build_preset_id: string;
  build_preset_name: string;
  machine_preset_id: string;
  machine_preset_name: string;
  machine_kind: "local" | "ssh";
  env_preset_id?: string | null;
  env_preset_name?: string | null;
  env_style: string;
  slurm_preset_id?: string | null;
  slurm_preset_name?: string | null;
  default_mpi_ranks: number;
  max_mpi_ranks?: number | null;
  default_opalx_info_level: number;
  slurm_enabled: boolean;
  slurm_overrides_supported: boolean;
  slurm_defaults?: SlurmResources | null;
  interactive_gateway: boolean;
  generated: boolean;
  valid: boolean;
  validation_errors: string[];
}

export interface ProfileTestCredentials {
  gateway_password?: string;
  gateway_otp?: string;
}

export interface ProfileTestResult {
  ok: boolean;
  whoami?: string | null;
  error?: string | null;
}

export async function getExecutionSettings(): Promise<ExecutionSettings> {
  const res = await api.get<ExecutionSettings>("/api/settings/execution/public");
  return res.data;
}

export async function saveExecutionSettings(
  body: ExecutionSettings,
): Promise<ExecutionSettings> {
  const res = await api.put<ExecutionSettings>("/api/settings/execution/public", body);
  return res.data;
}

export async function resetExecutionSettingsFromConfig(): Promise<ExecutionSettings> {
  const res = await api.post<ExecutionSettings>(
    "/api/settings/execution/public/reset-from-config",
  );
  return res.data;
}

export async function listRunProfiles(): Promise<RunProfile[]> {
  const res = await api.get<RunProfile[]>("/api/settings/execution/profiles");
  return res.data;
}

export async function listRunProfileSummaries(): Promise<RunProfileSummary[]> {
  const res = await api.get<RunProfileSummary[]>(
    "/api/settings/execution/profile-summaries",
  );
  return res.data;
}

export async function getRunProfilesForTrigger(): Promise<RunProfileSummary[]> {
  const res = await api.get<RunProfileSummary[]>("/api/runs/profiles");
  return res.data;
}

export async function createRunProfile(body: RunProfile): Promise<RunProfile> {
  const res = await api.post<RunProfile>("/api/settings/execution/profiles", body);
  return res.data;
}

export async function updateRunProfile(
  id: string,
  body: RunProfile,
): Promise<RunProfile> {
  const res = await api.put<RunProfile>(
    `/api/settings/execution/profiles/${encodeURIComponent(id)}`,
    body,
  );
  return res.data;
}

export async function deleteRunProfile(id: string): Promise<void> {
  await api.delete(`/api/settings/execution/profiles/${encodeURIComponent(id)}`);
}

export async function testRunProfile(
  id: string,
  credentials?: ProfileTestCredentials,
): Promise<ProfileTestResult> {
  const res = await api.post<ProfileTestResult>(
    `/api/settings/execution/profiles/${encodeURIComponent(id)}/test`,
    credentials ?? undefined,
  );
  return res.data;
}

