import { api } from "./client";

/** "active" hides archived runs (default), "archived" shows only archived,
 *  "all" returns everything. Sent as a `view` query param to the backend. */
export type ViewMode = "active" | "archived" | "all";

export interface RunIndexEntry {
  run_id: string;
  branch: string;
  arch: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  triggered_by: string | null;
  unit_tests_total: number;
  unit_tests_failed: number;
  regression_total: number;
  regression_passed: number;
  regression_failed: number;
  regression_broken: number;
  archived: boolean;
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
  duration_seconds: number | null;
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
  connection_name: string | null;
  triggered_by: string | null;
  unit_tests_total: number;
  unit_tests_failed: number;
  regression_total: number;
  regression_passed: number;
  regression_failed: number;
  regression_broken: number;
  archived: boolean;
}

export interface RunDetail {
  meta: RunMeta;
  unit: UnitTestsReport;
  regression: RegressionTestsReport;
}

export async function getBranches(
  view: ViewMode = "active"
): Promise<Record<string, string[]>> {
  const res = await api.get<Record<string, string[]>>(
    "/api/results/branches",
    { params: { view } }
  );
  return res.data;
}

export interface PaginatedRuns {
  runs: RunIndexEntry[];
  total: number;
}

export async function getRuns(
  branch: string,
  arch: string,
  limit = 50,
  offset = 0,
  view: ViewMode = "active"
): Promise<{ runs: RunIndexEntry[]; total: number }> {
  const res = await api.get<RunIndexEntry[]>(
    `/api/results/branches/${branch}/archs/${arch}/runs`,
    { params: { limit, offset, view } }
  );
  const total = parseInt(res.headers["x-total-count"] ?? "0", 10);
  return { runs: res.data, total };
}

export async function getAllRuns(
  limit = 25,
  offset = 0,
  view: ViewMode = "active"
): Promise<PaginatedRuns> {
  const res = await api.get<PaginatedRuns>("/api/results/all-runs", {
    params: { limit, offset, view },
  });
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

// ── Bulk archive / unarchive / hard-delete ────────────────────────────────

export interface ArchiveResult {
  changed: number;
  skipped_active: string[];
  not_found: string[];
}

export async function archiveBranch(
  branch: string,
  archived: boolean
): Promise<ArchiveResult> {
  const url = `/api/archive/branches/${encodeURIComponent(branch)}`;
  const res = archived ? await api.post<ArchiveResult>(url) : await api.delete<ArchiveResult>(url);
  return res.data;
}

export async function archiveArch(
  branch: string,
  arch: string,
  archived: boolean
): Promise<ArchiveResult> {
  const url = `/api/archive/branches/${encodeURIComponent(branch)}/archs/${encodeURIComponent(arch)}`;
  const res = archived ? await api.post<ArchiveResult>(url) : await api.delete<ArchiveResult>(url);
  return res.data;
}

export async function archiveRuns(
  branch: string,
  arch: string,
  runIds: string[],
  archived: boolean
): Promise<ArchiveResult> {
  const url = `/api/archive/branches/${encodeURIComponent(branch)}/archs/${encodeURIComponent(arch)}/runs`;
  const body = { run_ids: runIds };
  const res = archived
    ? await api.post<ArchiveResult>(url, body)
    : await api.delete<ArchiveResult>(url, { data: body });
  return res.data;
}

export async function hardDeleteRuns(
  branch: string,
  arch: string,
  runIds: string[]
): Promise<ArchiveResult> {
  const res = await api.post<ArchiveResult>(
    `/api/archive/branches/${encodeURIComponent(branch)}/archs/${encodeURIComponent(arch)}/runs/hard-delete`,
    { run_ids: runIds }
  );
  return res.data;
}
