import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ListFilter, Search } from "lucide-react";
import { getCatalogTests } from "../api/catalog";
import {
  getArchConfigs,
  getOpalxBranches,
  getRegtestsBranches,
} from "../api/runs";
import { StatusBadge } from "../components/StatusBadge";

export function CatalogPage() {
  const [regtestsBranch, setRegtestsBranch] = useState("master");
  const [opalxBranch, setOpalxBranch] = useState("master");
  const [arch, setArch] = useState("cpu-serial");
  const [search, setSearch] = useState("");

  const { data: regBranches } = useQuery({
    queryKey: ["regtests-branches"],
    queryFn: getRegtestsBranches,
  });
  const { data: opalxBranches } = useQuery({
    queryKey: ["opalx-branches"],
    queryFn: getOpalxBranches,
  });
  const { data: archs } = useQuery({
    queryKey: ["arch-configs"],
    queryFn: getArchConfigs,
  });
  const { data, isLoading } = useQuery({
    queryKey: ["catalog-tests", regtestsBranch, opalxBranch, arch],
    queryFn: () => getCatalogTests(regtestsBranch, false, opalxBranch, arch),
  });

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (data?.tests ?? []).filter((test) => {
      if (!q) return true;
      return (
        test.name.toLowerCase().includes(q) ||
        (test.description ?? "").toLowerCase().includes(q) ||
        test.metrics.some((m) => m.metric.toLowerCase().includes(q))
      );
    });
  }, [data?.tests, search]);

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto">
      <div className="flex flex-col gap-1 mb-6">
        <h1 className="text-fg text-2xl font-semibold">Test Catalog</h1>
        <p className="text-muted text-sm">
          {data?.commit ? (
            <>
              regression-tests-x{" "}
              {data.commit_url ? (
                <a
                  href={data.commit_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-accent hover:underline"
                >
                  {data.commit.slice(0, 10)}
                </a>
              ) : (
                <span>{data.commit.slice(0, 10)}</span>
              )}
            </>
          ) : (
            "Local regression-tests-x clone"
          )}
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3 mb-5 md:grid-cols-[1fr_1fr_1fr_2fr]">
        <select
          value={regtestsBranch}
          onChange={(e) => setRegtestsBranch(e.target.value)}
          className="bg-surface border border-border rounded-lg px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
          title="Regression-tests branch"
        >
          {(regBranches ?? ["master"]).map((branch) => (
            <option key={branch} value={branch}>
              tests: {branch}
            </option>
          ))}
        </select>
        <select
          value={opalxBranch}
          onChange={(e) => setOpalxBranch(e.target.value)}
          className="bg-surface border border-border rounded-lg px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
          title="OPALX branch for status context"
        >
          {(opalxBranches ?? ["master"]).map((branch) => (
            <option key={branch} value={branch}>
              opalx: {branch}
            </option>
          ))}
        </select>
        <select
          value={arch}
          onChange={(e) => setArch(e.target.value)}
          className="bg-surface border border-border rounded-lg px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
          title="Architecture for status context"
        >
          {(archs ?? ["cpu-serial"]).map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search tests or metrics"
            className="w-full bg-surface border border-border rounded-lg pl-9 pr-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
          />
        </div>
      </div>

      <div className="flex items-center gap-2 text-muted text-xs mb-3">
        <ListFilter size={13} />
        {rows.length} of {data?.tests.length ?? 0} tests
      </div>

      {isLoading && !data ? (
        <p className="text-muted text-sm">Loading catalog…</p>
      ) : rows.length === 0 ? (
        <p className="text-muted text-sm">No tests match the current filters.</p>
      ) : (
        <div className="border border-border rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-surface text-muted text-left">
              <tr>
                <th className="px-4 py-3 font-medium">Test</th>
                <th className="px-4 py-3 font-medium">State</th>
                <th className="px-4 py-3 font-medium">Last</th>
                <th className="px-4 py-3 font-medium">Metrics</th>
                <th className="px-4 py-3 font-medium">Refs</th>
                <th className="px-4 py-3 font-medium">Warnings</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((test, i) => (
                <tr
                  key={test.path}
                  className={`border-t border-border ${i % 2 ? "bg-surface/20" : ""}`}
                >
                  <td className="px-4 py-3 min-w-0">
                    {test.last_run_id ? (
                      <Link
                        to={`/results/${encodeURIComponent(opalxBranch)}/${encodeURIComponent(arch)}/${encodeURIComponent(test.last_run_id)}`}
                        className="font-mono text-accent text-xs hover:underline"
                        title="Open newest active run containing this test"
                      >
                        {test.name}
                      </Link>
                    ) : (
                      <p className="font-mono text-fg text-xs">{test.name}</p>
                    )}
                    {test.description && (
                      <p className="text-muted text-xs mt-1 line-clamp-2">
                        {test.description}
                      </p>
                    )}
                    {test.multi_container_refs.length > 0 && (
                      <p className="text-accent text-xs mt-1">
                        multi-container: {test.multi_container_refs.join(", ")}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full border ${
                        test.enabled
                          ? "border-passed/40 text-passed bg-passed/10"
                          : "border-border text-muted"
                      }`}
                    >
                      {test.enabled ? "enabled" : "disabled"}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      {test.last_status ? (
                        <StatusBadge status={test.last_status} />
                      ) : (
                        <span className="text-muted text-xs">—</span>
                      )}
                      {test.flaky && (
                        <span className="text-xs text-broken">flaky</span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-xs tabular-nums">
                    {test.metrics.length}
                  </td>
                  <td className="px-4 py-3 text-xs tabular-nums">
                    {test.reference_stat_count}
                  </td>
                  <td className="px-4 py-3 text-xs text-muted">
                    {test.warnings.length === 0 ? (
                      "—"
                    ) : (
                      <span title={test.warnings.join("; ")}>
                        {test.warnings.length}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
