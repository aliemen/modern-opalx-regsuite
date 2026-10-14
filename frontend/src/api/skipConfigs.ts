import { api } from "./client";

export interface SkipConfigInput {
  name: string;
  description?: string | null;
  unit_tests: string[];
  regression_tests: string[];
}

export interface SkipConfig extends SkipConfigInput {
  id: string;
}

export interface SkipCandidate {
  name: string;
  median_seconds: number | null;
}

export interface SkipCandidates {
  regression: SkipCandidate[];
  unit: SkipCandidate[];
}

/** Mirrors the backend rule in skip_configs.py. */
export const TEST_NAME_RE = /^[A-Za-z0-9_.+-]+$/;

const BASE = "/api/settings/execution/test-skips";

export function skipSummary(
  cfg: Pick<SkipConfigInput, "unit_tests" | "regression_tests">,
): string {
  const parts: string[] = [];
  if (cfg.regression_tests.length > 0) parts.push(`${cfg.regression_tests.length} regression`);
  if (cfg.unit_tests.length > 0) parts.push(`${cfg.unit_tests.length} unit`);
  return parts.length > 0 ? `skips ${parts.join(", ")}` : "skips nothing";
}

export async function listSkipConfigs(): Promise<SkipConfig[]> {
  const res = await api.get<SkipConfig[]>(BASE);
  return res.data;
}

export async function getSkipCandidates(): Promise<SkipCandidates> {
  const res = await api.get<SkipCandidates>(`${BASE}/candidates`);
  return res.data;
}

export async function createSkipConfig(body: SkipConfigInput): Promise<SkipConfig> {
  const res = await api.post<SkipConfig>(BASE, body);
  return res.data;
}

export async function updateSkipConfig(id: string, body: SkipConfigInput): Promise<SkipConfig> {
  const res = await api.put<SkipConfig>(`${BASE}/${encodeURIComponent(id)}`, body);
  return res.data;
}

export async function deleteSkipConfig(id: string): Promise<void> {
  await api.delete(`${BASE}/${encodeURIComponent(id)}`);
}
