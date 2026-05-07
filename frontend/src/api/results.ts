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
  regtest_branch: string | null;
  connection_name: string | null;
  unit_tests_total: number;
  unit_tests_failed: number;
  regression_total: number;
  regression_passed: number;
  regression_failed: number;
  regression_broken: number;
  archived: boolean;
  public: boolean;
  run_options: RunOptions;
  rerun_of: RerunReference | null;
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

export interface RegressionContainer {
  id: string | null;
  state: string;
  metrics: RegressionMetric[];
  revision: string | null;
}

export interface RegressionSimulation {
  name: string;
  description: string | null;
  state: string | null;
  log_file: string | null;
  containers: RegressionContainer[];
  duration_seconds: number | null;
  beamline_plot: string | null;
  beamline_3d_data: string | null;
  exit_code: number | null;
  crash_signal: string | null;
  crash_summary: string | null;
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
  regtest_branch: string | null;
  connection_name: string | null;
  triggered_by: string | null;
  unit_tests_total: number;
  unit_tests_failed: number;
  regression_total: number;
  regression_passed: number;
  regression_failed: number;
  regression_broken: number;
  archived: boolean;
  public: boolean;
  run_options: RunOptions;
  rerun_of: RerunReference | null;
}

export interface RunOptions {
  skip_unit: boolean;
  skip_regression: boolean;
  clean_build: boolean;
  custom_cmake_args: string[];
}

export interface RerunReference {
  branch: string;
  arch: string;
  run_id: string;
}

export interface RunDetail {
  meta: RunMeta;
  unit: UnitTestsReport;
  regression: RegressionTestsReport;
  archived_on_cold_storage: boolean;
}

/** Build a query-param object that omits null/undefined values so axios
 *  doesn't serialise `?triggered_by=` into the URL when no user is selected. */
function paramsWithUser(
  base: Record<string, unknown>,
  triggeredBy: string | null | undefined
): Record<string, unknown> {
  return triggeredBy ? { ...base, triggered_by: triggeredBy } : base;
}

export async function getBranches(
  view: ViewMode = "active",
  triggeredBy: string | null = null
): Promise<Record<string, string[]>> {
  const res = await api.get<Record<string, string[]>>(
    "/api/results/branches",
    { params: paramsWithUser({ view }, triggeredBy) }
  );
  return res.data;
}

export interface PaginatedRuns {
  runs: RunIndexEntry[];
  total: number;
}

export interface ArchiveSummary {
  total: number;
  by_branch: Record<string, number>;
  by_regtest_branch: Record<string, number>;
}

export async function getArchiveSummary(): Promise<ArchiveSummary> {
  const res = await api.get<ArchiveSummary>("/api/results/archive-summary");
  return res.data;
}

export async function getRuns(
  branch: string,
  arch: string,
  limit = 50,
  offset = 0,
  view: ViewMode = "active",
  triggeredBy: string | null = null
): Promise<{ runs: RunIndexEntry[]; total: number }> {
  const res = await api.get<RunIndexEntry[]>(
    `/api/results/branches/${branch}/archs/${arch}/runs`,
    { params: paramsWithUser({ limit, offset, view }, triggeredBy) }
  );
  const total = parseInt(res.headers["x-total-count"] ?? "0", 10);
  return { runs: res.data, total };
}

export async function getAllRuns(
  limit = 25,
  offset = 0,
  view: ViewMode = "active",
  triggeredBy: string | null = null
): Promise<PaginatedRuns> {
  const res = await api.get<PaginatedRuns>("/api/results/all-runs", {
    params: paramsWithUser({ limit, offset, view }, triggeredBy),
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

export async function setRunVisibility(
  branch: string,
  arch: string,
  runId: string,
  isPublic: boolean
): Promise<RunIndexEntry> {
  const res = await api.patch<RunIndexEntry>(
    `/api/results/branches/${encodeURIComponent(branch)}/archs/${encodeURIComponent(arch)}/runs/${encodeURIComponent(runId)}/visibility`,
    { public: isPublic }
  );
  return res.data;
}

// ── Bulk archive / unarchive / hard-delete ────────────────────────────────

export interface ArchiveResult {
  changed: number;
  skipped_active: string[];
  not_found: string[];
  failed_move: string[];
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

export async function archiveRun(
  branch: string,
  arch: string,
  runId: string,
  archived: boolean
): Promise<ArchiveResult> {
  const url = `/api/archive/branches/${encodeURIComponent(branch)}/archs/${encodeURIComponent(arch)}/runs`;
  const payload = { run_ids: [runId] };
  const res = archived
    ? await api.post<ArchiveResult>(url, payload)
    : await api.delete<ArchiveResult>(url, { data: payload });
  return res.data;
}

export async function restoreRun(
  branch: string,
  arch: string,
  runId: string
): Promise<ArchiveResult> {
  const res = await api.post<ArchiveResult>(
    `/api/archive/branches/${encodeURIComponent(branch)}/archs/${encodeURIComponent(arch)}/runs/${encodeURIComponent(runId)}/restore`
  );
  return res.data;
}

export async function hardDeleteArch(
  branch: string,
  arch: string
): Promise<ArchiveResult> {
  const res = await api.post<ArchiveResult>(
    `/api/archive/branches/${encodeURIComponent(branch)}/archs/${encodeURIComponent(arch)}/hard-delete-arch`
  );
  return res.data;
}
