import { useEffect, useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight, Search } from "lucide-react";
import type { UnitTestCase } from "../../api/results";
import { StatusBadge } from "../../components/StatusBadge";

// Problems first, skipped last, so failures sit at the top of the box.
const RANK: Record<string, number> = { passed: 1, skipped: 2 };

/**
 * Collapsible unit test results. Expanded, the table scrolls inside a box about ten
 * rows high with a sticky header, a name filter and a "Not passed" toggle. The box
 * is a focusable, labelled region so keyboard users can scroll it, and the result
 * count is a status message that screen readers announce after typing pauses.
 */
export function UnitTestsPanel({ tests, summary }: { tests: UnitTestCase[]; summary: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [problemsOnly, setProblemsOnly] = useState(false);

  const problems = tests.filter((t) => (RANK[t.status] ?? 0) === 0).length;
  const needle = query.trim().toLowerCase();
  const rows = tests
    .filter((t) => (!problemsOnly || (RANK[t.status] ?? 0) === 0) && t.name.toLowerCase().includes(needle))
    .sort((a, b) => (RANK[a.status] ?? 0) - (RANK[b.status] ?? 0));
  const count = rows.length === tests.length ? `${tests.length} tests` : `${rows.length} of ${tests.length} tests`;
  const announced = useDebounced(count, 400);

  return (
    <section className="bg-surface border border-border rounded-xl overflow-hidden">
      <h2>
        <button
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          aria-controls="unit-tests-panel"
          className="w-full flex items-center gap-3 px-5 py-3 hover:bg-border/30 transition-colors text-left"
        >
          {open ? <ChevronDown size={14} aria-hidden="true" /> : <ChevronRight size={14} aria-hidden="true" />}
          <span className="text-fg font-medium">Unit Tests</span>
          <span className="text-muted text-sm font-normal ml-auto">{summary}</span>
        </button>
      </h2>
      {open && (
        <div id="unit-tests-panel" className="border-t border-border p-4">
          <div className="max-w-5xl space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <label className="relative block w-full sm:w-64">
                <span className="sr-only">Filter unit tests by name</span>
                <Search
                  size={13}
                  aria-hidden="true"
                  className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-muted"
                />
                <input
                  type="search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Filter unit tests"
                  className="w-full rounded border border-border bg-bg py-1 pl-7 pr-2 text-xs text-fg placeholder:text-muted"
                />
              </label>
              {problems > 0 && (
                <button
                  type="button"
                  onClick={() => setProblemsOnly(!problemsOnly)}
                  aria-pressed={problemsOnly}
                  className={`rounded border px-2 py-1 text-xs transition-colors ${
                    problemsOnly ? "border-failed/50 bg-failed/10 text-failed" : "border-border text-muted hover:text-fg"
                  }`}
                >
                  Not passed ({problems})
                </button>
              )}
              <span aria-hidden="true" className="ml-auto text-xs tabular-nums text-muted">
                {count}
              </span>
              <span role="status" className="sr-only">
                {announced}
              </span>
            </div>
            <div
              role="region"
              aria-label="Unit test results"
              tabIndex={0}
              className="max-h-[20rem] overflow-y-auto rounded-lg border border-border focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              <table className="w-full text-xs">
                <caption className="sr-only">Unit test results</caption>
                <thead className="sticky top-0 z-10 bg-surface text-muted shadow-[0_1px_0_rgb(var(--color-border))]">
                  <tr className="h-7">
                    <th scope="col" className="px-3 text-left font-medium">Test</th>
                    <th scope="col" className="px-3 text-left font-medium">Status</th>
                    <th scope="col" className="px-3 text-right font-medium">Duration</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((t) => (
                    <tr key={t.name} className="h-7 border-t border-border/40 first:border-t-0 hover:bg-border/30">
                      <td className="px-3 font-mono text-fg break-all">{t.name}</td>
                      <td className="px-3">
                        <StatusBadge status={t.status} />
                      </td>
                      <td className="px-3 text-right tabular-nums text-muted">
                        {t.duration_seconds != null ? `${t.duration_seconds.toFixed(2)}s` : "—"}
                      </td>
                    </tr>
                  ))}
                  {rows.length === 0 && (
                    <tr className="h-7">
                      <td colSpan={3} className="px-3 text-muted">
                        No unit tests match.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return settled;
}
