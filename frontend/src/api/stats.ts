import { api } from "./client";
import type { ViewMode } from "./results";

// ── Schemas (mirrored from modern_opalx_regsuite/api/stats_developer.py) ──

export interface LatestMasterCell {
  arch: string;
  run_id: string | null;
  status: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  unit_total: number;
  unit_failed: number;
  regression_total: number;
  regression_passed: number;
  regression_failed: number;
  regression_broken: number;
}

export interface LatestMasterMatrix {
  cells: LatestMasterCell[];
}

export interface NewlyBrokenEntry {
  arch: string;
  current_run_id: string | null;
  previous_run_id: string | null;
  sim_names: string[];
  enough_runs: boolean;
}

export interface NewlyBrokenReport {
  entries: NewlyBrokenEntry[];
}

export interface SuiteDurationCell {
  arch: string;
  current_seconds: number | null;
  avg_last_10_seconds: number | null;
  delta_pct: number | null;
}

export interface SuiteDurationReport {
  cells: SuiteDurationCell[];
}

export interface ActivityDay {
  date: string; // ISO date (YYYY-MM-DD)
  passed: number;
  failed: number;
  broken: number;
}

export interface ActivityReport {
  days: ActivityDay[];
}

export interface UserRunCount {
  username: string;
  count: number;
}

export interface UsersLeaderboard {
  users: UserRunCount[];
}

export interface FlakySimulation {
  name: string;
  observations: number;
  passed: number;
  failed: number;
  broken: number;
  crashed: number;
  latest_status: string | null;
  latest_run_id: string | null;
}

export interface FlakinessReport {
  branch: string;
  arch: string;
  regtests_branch: string;
  limit: number;
  min_observations: number;
  runs_considered: number;
  simulations: FlakySimulation[];
}

// ── Endpoints ──────────────────────────────────────────────────────────────

export async function getLatestMaster(
  view: ViewMode = "active"
): Promise<LatestMasterMatrix> {
  const res = await api.get<LatestMasterMatrix>("/api/stats/latest-master", {
    params: { view },
  });
  return res.data;
}

export async function getNewlyBroken(
  view: ViewMode = "active"
): Promise<NewlyBrokenReport> {
  const res = await api.get<NewlyBrokenReport>("/api/stats/newly-broken", {
    params: { view },
  });
  return res.data;
}

export async function getSuiteDuration(
  view: ViewMode = "active"
): Promise<SuiteDurationReport> {
  const res = await api.get<SuiteDurationReport>("/api/stats/suite-duration", {
    params: { view },
  });
  return res.data;
}

export async function getActivity(
  days = 14,
  view: ViewMode = "active"
): Promise<ActivityReport> {
  const res = await api.get<ActivityReport>("/api/stats/activity", {
    params: { view, days },
  });
  return res.data;
}

export async function getUsersLeaderboard(
  view: ViewMode = "all"
): Promise<UsersLeaderboard> {
  const res = await api.get<UsersLeaderboard>("/api/stats/users-leaderboard", {
    params: { view },
  });
  return res.data;
}

export async function getFlakiness(
  branch = "master",
  arch = "cpu-serial",
  regtestsBranch = "master",
  limit = 20
): Promise<FlakinessReport> {
  const res = await api.get<FlakinessReport>("/api/stats/flakiness", {
    params: { branch, arch, regtests_branch: regtestsBranch, limit },
  });
  return res.data;
}
