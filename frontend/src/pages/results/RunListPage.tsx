import { useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Clock } from "lucide-react";
import { getRuns, type RunIndexEntry } from "../../api/results";
import { StatusBadge } from "../../components/StatusBadge";
import { Pagination } from "../../components/Pagination";
import { Breadcrumb } from "../../components/Breadcrumb";

function fmtDate(d: string | null) {
  if (!d) return "\u2014";
  return new Date(d).toLocaleString();
}

function duration(start: string, end: string | null) {
  if (!end) return "\u2014";
  const s = Math.floor((new Date(end).getTime() - new Date(start).getTime()) / 1000);
  const m = Math.floor(s / 60);
  return `${m}m ${(s % 60).toString().padStart(2, "0")}s`;
}

export function RunListPage() {
  const { branch, arch } = useParams<{ branch: string; arch: string }>();
  const [searchParams] = useSearchParams();
  const [pageSize, setPageSize] = useState(25);
  const [offset, setOffset] = useState(0);

  const { data, isLoading } = useQuery({
    queryKey: ["runs", branch, arch, pageSize, offset],
    queryFn: () => getRuns(branch!, arch!, pageSize, offset),
    enabled: !!branch && !!arch,
    placeholderData: keepPreviousData,
  });

  const runs = data?.runs ?? [];
  const total = data?.total ?? 0;
  const qs = searchParams.toString();

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <Breadcrumb
        crumbs={[
          {
            label: `${branch} \u00b7 ${arch}`,
            title: `OPALX branch ${branch} on ${arch}`,
          },
        ]}
      />
      <h1 className="text-fg text-xl font-semibold mb-1">
        {branch} / {arch}
      </h1>
      <p className="text-muted text-sm mb-6">
        {total} run{total !== 1 ? "s" : ""} across all regtest branches
      </p>

      {isLoading && !data ? (
        <div className="text-muted text-sm">Loading...</div>
      ) : runs.length === 0 ? (
        <div className="text-muted text-sm">No runs found.</div>
      ) : (
        <>
          <div className="border border-border rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-surface text-muted text-left">
                <tr>
                  <th className="px-4 py-3 font-medium">Run ID</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Regtests</th>
                  <th className="px-4 py-3 font-medium">
                    <Clock size={12} className="inline mr-1" />
                    Started
                  </th>
                  <th className="px-4 py-3 font-medium">User</th>
                  <th className="px-4 py-3 font-medium">Duration</th>
                  <th className="px-4 py-3 font-medium">Unit</th>
                  <th className="px-4 py-3 font-medium">Regression</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run: RunIndexEntry, i: number) => (
                  <tr
                    key={run.run_id}
                    className={`border-t border-border hover:bg-surface/50 transition-colors ${i % 2 === 0 ? "" : "bg-surface/20"}`}
                  >
                    <td className="px-4 py-3">
                      <Link
                        to={`/results/${branch}/${arch}/${run.run_id}${qs ? `?${qs}` : ""}`}
                        className="text-accent hover:underline font-mono text-xs"
                      >
                        {run.run_id}
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={run.status} />
                    </td>
                    <td className="px-4 py-3 text-muted font-mono text-xs">
                      {run.regtest_branch ?? "\u2014"}
                    </td>
                    <td className="px-4 py-3 text-muted text-xs">{fmtDate(run.started_at)}</td>
                    <td className="px-4 py-3 text-muted font-mono text-xs">{run.triggered_by ?? "—"}</td>
                    <td className="px-4 py-3 text-muted text-xs">
                      {duration(run.started_at, run.finished_at)}
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {run.unit_tests_total - run.unit_tests_failed}/{run.unit_tests_total}
                    </td>
                    <td className="px-4 py-3 text-xs">
                      <span className="text-passed">{run.regression_passed}</span>
                      {" / "}
                      {run.regression_total}
                      {run.regression_failed > 0 && (
                        <span className="text-failed ml-1">({run.regression_failed} fail)</span>
                      )}
                      {run.regression_broken > 0 && (
                        <span className="text-broken ml-1">({run.regression_broken} broken)</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <Pagination
            total={total}
            pageSize={pageSize}
            offset={offset}
            onPageSizeChange={(s) => {
              setPageSize(s);
              setOffset(0);
            }}
            onOffsetChange={setOffset}
          />
        </>
      )}
    </div>
  );
}
