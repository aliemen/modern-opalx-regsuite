import { api } from "./client";

export interface RunIndexEntry {
  run_id: string;
  branch: string;
  arch: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  unit_tests_total: number;
  unit_tests_failed: number;
  regression_total: number;
  regression_passed: number;
  regression_failed: number;
  regression_broken: number;
}

export interface UnitTestCase {
  name: string;
  status: string;
  duration_seconds: number | null;
  output_snippet: string | null;
}

export interface UnitTestsReport {
  tests: UnitTestCase[];
}

export interface RegressionMetric {
  metric: string;
  mode: string;
  eps: number | null;
  delta: number | null;
  state: string;
  reference_value: number | null;
  current_value: number | null;
  plot: string | null;
}

export interface RegressionSimulation {
  name: string;
  description: string | null;
  state: string | null;
  log_file: string | null;
  metrics: RegressionMetric[];
}

export interface RegressionTestsReport {
  simulations: RegressionSimulation[];
}

export interface RunMeta {
  branch: string;
  arch: string;
  run_id: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  opalx_commit: string | null;
  tests_repo_commit: string | null;
  unit_tests_total: number;
  unit_tests_failed: number;
  regression_total: number;
  regression_passed: number;
  regression_failed: number;
  regression_broken: number;
}

export interface RunDetail {
  meta: RunMeta;
  unit: UnitTestsReport;
  regression: RegressionTestsReport;
}

export async function getBranches(): Promise<Record<string, string[]>> {
  const res = await api.get<Record<string, string[]>>("/api/results/branches");
  return res.data;
}

export async function getRuns(
  branch: string,
  arch: string,
  limit = 50,
  offset = 0
): Promise<RunIndexEntry[]> {
  const res = await api.get<RunIndexEntry[]>(
    `/api/results/branches/${branch}/archs/${arch}/runs`,
    { params: { limit, offset } }
  );
  return res.data;
}

export async function getRunDetail(
  branch: string,
  arch: string,
  runId: string
): Promise<RunDetail> {
  const res = await api.get<RunDetail>(
    `/api/results/branches/${branch}/archs/${arch}/runs/${runId}`
  );
  return res.data;
}

export async function deleteRun(
  branch: string,
  arch: string,
  runId: string
): Promise<void> {
  await api.delete(`/api/results/branches/${branch}/archs/${arch}/runs/${runId}`);
}
