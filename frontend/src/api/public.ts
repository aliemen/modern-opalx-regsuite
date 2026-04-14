import axios from "axios";

import type { RegressionTestsReport, RunIndexEntry, RunMeta, UnitTestsReport } from "./results";

// Bare axios client — no token interceptor — so requests to /api/public never
// trigger the 401 refresh/redirect flow. Public endpoints are unauthenticated
// by design, and the login page itself mounts the public panel.
const publicClient = axios.create({ baseURL: "/" });

export interface PublicPaginatedRuns {
  runs: RunIndexEntry[];
  total: number;
}

export interface PublicActivityDay {
  date: string;
  passed: number;
  failed: number;
  broken: number;
}

export interface PublicActivityReport {
  days: PublicActivityDay[];
}

export interface PublicRunDetail {
  meta: RunMeta;
  unit: UnitTestsReport;
  regression: RegressionTestsReport;
}

export async function getPublicRuns(
  limit = 25,
  offset = 0,
): Promise<PublicPaginatedRuns> {
  const res = await publicClient.get<PublicPaginatedRuns>(
    "/api/public/all-runs",
    { params: { limit, offset } },
  );
  return res.data;
}

export async function getPublicActivity(
  days = 14,
): Promise<PublicActivityReport> {
  const res = await publicClient.get<PublicActivityReport>(
    "/api/public/stats/activity",
    { params: { days } },
  );
  return res.data;
}

export async function getPublicRunDetail(
  branch: string,
  arch: string,
  runId: string,
): Promise<PublicRunDetail> {
  const res = await publicClient.get<PublicRunDetail>(
    `/api/public/runs/${encodeURIComponent(branch)}/${encodeURIComponent(arch)}/${encodeURIComponent(runId)}`,
  );
  return res.data;
}
