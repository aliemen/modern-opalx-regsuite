import { api } from "./client";

export interface CatalogMetricCheck {
  metric: string;
  mode: string;
  eps: number | null;
}

export interface CatalogTestEntry {
  name: string;
  enabled: boolean;
  path: string;
  description: string | null;
  metrics: CatalogMetricCheck[];
  has_input: boolean;
  has_local: boolean;
  reference_stat_count: number;
  multi_container_refs: string[];
  warnings: string[];
  last_status: string | null;
  last_run_id: string | null;
  flaky: boolean;
}

export interface CatalogReport {
  branch: string;
  commit: string | null;
  commit_url: string | null;
  tests: CatalogTestEntry[];
}

export async function getCatalogTests(
  branch = "master",
  includeDisabled = false,
  opalxBranch: string | null = "master",
  arch: string | null = "cpu-serial"
): Promise<CatalogReport> {
  const res = await api.get<CatalogReport>("/api/catalog/tests", {
    params: {
      branch,
      include_disabled: includeDisabled,
      opalx_branch: opalxBranch || undefined,
      arch: arch || undefined,
    },
  });
  return res.data;
}
