/**
 * In-app route to a run list (`/results/:branch/:arch`) or run detail
 * (`/results/:branch/:arch/:runId`). Each part is encoded because git branch
 * names may contain `/` (e.g. `fix/foo`), which would otherwise split into
 * extra route segments.
 */
export function resultsPath(branch: string, arch: string, runId?: string): string {
  const base = `/results/${encodeURIComponent(branch)}/${encodeURIComponent(arch)}`;
  return runId ? `${base}/${encodeURIComponent(runId)}` : base;
}
