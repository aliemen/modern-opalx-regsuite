import { api } from "./client";

export type EnvActivationStyle = "none" | "modules" | "prologue";

export interface EnvActivation {
  style: EnvActivationStyle;
  lmod_init?: string;
  module_use_paths?: string[];
  module_loads?: string[];
  prologue?: string | null;
}

export interface GatewayEndpoint {
  host: string;
  user: string;
  port: number;
  key_name: string;
}

export interface Connection {
  name: string;
  description?: string | null;
  host: string;
  user: string;
  port: number;
  key_name: string;
  gateway?: GatewayEndpoint | null;
  work_dir: string;
  cleanup_after_run: boolean;
  env: EnvActivation;
}

export interface ConnectionTestResult {
  ok: boolean;
  whoami?: string | null;
  error?: string | null;
}

export async function listConnections(): Promise<Connection[]> {
  const res = await api.get<Connection[]>("/api/settings/connections");
  return res.data;
}

export async function getConnection(name: string): Promise<Connection> {
  const res = await api.get<Connection>(`/api/settings/connections/${encodeURIComponent(name)}`);
  return res.data;
}

export async function createConnection(body: Connection): Promise<Connection> {
  const res = await api.post<Connection>("/api/settings/connections", body);
  return res.data;
}

export async function updateConnection(name: string, body: Connection): Promise<Connection> {
  const res = await api.put<Connection>(
    `/api/settings/connections/${encodeURIComponent(name)}`,
    body,
  );
  return res.data;
}

export async function deleteConnection(name: string): Promise<void> {
  await api.delete(`/api/settings/connections/${encodeURIComponent(name)}`);
}

export async function testConnection(name: string): Promise<ConnectionTestResult> {
  const res = await api.post<ConnectionTestResult>(
    `/api/settings/connections/${encodeURIComponent(name)}/test`,
  );
  return res.data;
}

/** Sentinel connection name representing local execution. */
export const LOCAL_CONNECTION = "local";
