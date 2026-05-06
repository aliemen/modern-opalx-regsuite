import { api } from "./client";

export interface RunArtifactFile {
  path: string;
  kind: string;
  size_bytes: number;
  sha256: string;
}

export interface RunArtifactManifest {
  schema_version: number;
  generated_at: string;
  files: RunArtifactFile[];
}

export interface IntegrityIssue {
  severity: "warning" | "error";
  code: string;
  message: string;
  path: string | null;
}

export interface RunIntegrityReport {
  status: "ok" | "warning" | "error";
  issues: IntegrityIssue[];
  manifest: RunArtifactManifest | null;
}

export async function getRunIntegrity(
  branch: string,
  arch: string,
  runId: string
): Promise<RunIntegrityReport> {
  const res = await api.get<RunIntegrityReport>(
    `/api/integrity/runs/${encodeURIComponent(branch)}/${encodeURIComponent(arch)}/${encodeURIComponent(runId)}`
  );
  return res.data;
}
