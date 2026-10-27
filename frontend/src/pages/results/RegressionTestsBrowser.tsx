import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import type { RegressionSimulation } from "../../api/results";
import { SimDetail, type SeriesLoader } from "./SimDetail";
import { StatusIcon, checkCounts, isProblem } from "./simStatus";

/** URL search parameter naming the selected test, so a test view can be linked. */
export const TEST_PARAM = "test";

interface RegressionTestsBrowserProps {
  simulations: RegressionSimulation[];
  runPath: string;
  series: SeriesLoader | null;
}

/**
 * Master-detail view of a run's regression tests. Every test stays one click away in
 * a sticky list (a select box on small screens) while the selected one fills the rest
 * of the width. Opens on the first test that did not pass, else the first test.
 */
export function RegressionTestsBrowser({ simulations, runPath, series }: RegressionTestsBrowserProps) {
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState("");
  const [problemsOnly, setProblemsOnly] = useState(false);
  const detailRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  const executed = simulations.filter((s) => s.state !== "skipped");
  const skipped = simulations.filter((s) => s.state === "skipped").map((s) => s.name);
  const problems = executed.filter((s) => isProblem(s.state));
  const needle = query.trim().toLowerCase();
  const visible = executed.filter(
    (s) => (!problemsOnly || isProblem(s.state)) && s.name.toLowerCase().includes(needle)
  );
  const selected = executed.find((s) => s.name === params.get(TEST_PARAM)) ?? problems[0] ?? executed[0];

  // Step through what the list shows, or through everything once the selection is filtered out.
  const order = visible.includes(selected) ? visible : executed;
  const pos = order.indexOf(selected);
  const prev = pos > 0 ? order[pos - 1] : undefined;
  const next = pos >= 0 && pos < order.length - 1 ? order[pos + 1] : undefined;

  const searchFor = (name: string) => {
    const nextParams = new URLSearchParams(params);
    nextParams.set(TEST_PARAM, name);
    return `?${nextParams.toString()}`;
  };
  const select = (name: string) => setParams(new URLSearchParams(searchFor(name)), { replace: true });

  // After switching tests, bring the detail's top back into view and the list entry into the list's view.
  const shown = useRef(selected?.name);
  useEffect(() => {
    if (!selected || shown.current === selected.name) return;
    shown.current = selected.name;
    const detail = detailRef.current;
    if (detail && detail.getBoundingClientRect().top < 0) detail.scrollIntoView({ block: "start" });
  }, [selected]);
  useEffect(() => {
    const list = listRef.current;
    const item = list?.querySelector<HTMLElement>('[aria-current="true"]');
    if (!list || !item) return;
    if (item.offsetTop < list.scrollTop) list.scrollTop = item.offsetTop;
    else if (item.offsetTop + item.offsetHeight > list.scrollTop + list.clientHeight)
      list.scrollTop = item.offsetTop + item.offsetHeight - list.clientHeight;
  }, [selected, visible.length]);

  function onListKey(e: KeyboardEvent<HTMLUListElement>) {
    const links = [...e.currentTarget.querySelectorAll<HTMLAnchorElement>("a")];
    const at = links.indexOf(document.activeElement as HTMLAnchorElement);
    const target =
      e.key === "ArrowDown" ? links[Math.min(at + 1, links.length - 1)]
      : e.key === "ArrowUp" ? links[Math.max(at - 1, 0)]
      : e.key === "Home" ? links[0]
      : e.key === "End" ? links[links.length - 1]
      : undefined;
    if (target) {
      e.preventDefault();
      target.focus();
    }
  }

  if (!selected) return <SkippedTestsList names={skipped} />;

  return (
    <div className="grid gap-4 lg:grid-cols-[15rem_minmax(0,1fr)] xl:grid-cols-[17rem_minmax(0,1fr)]">
      <div className="order-last flex min-h-0 flex-col gap-3 lg:sticky lg:top-4 lg:order-none lg:max-h-[calc(100vh-2rem)] lg:self-start">
        <nav
          aria-label="Regression tests"
          className="hidden min-h-0 flex-col rounded-xl border border-border bg-surface lg:flex"
        >
          <div className="space-y-2 border-b border-border p-2">
            <label className="relative block">
              <span className="sr-only">Filter tests by name</span>
              <Search
                size={13}
                aria-hidden="true"
                className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-muted"
              />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Filter tests"
                className="w-full rounded border border-border bg-bg py-1 pl-7 pr-2 text-xs text-fg placeholder:text-muted"
              />
            </label>
            {problems.length > 0 && (
              <div role="group" aria-label="Show tests" className="flex overflow-hidden rounded border border-border text-[11px]">
                {[
                  { label: `All (${executed.length})`, value: false },
                  { label: `Not passed (${problems.length})`, value: true },
                ].map((o, i) => (
                  <button
                    key={o.label}
                    type="button"
                    onClick={() => setProblemsOnly(o.value)}
                    aria-pressed={problemsOnly === o.value}
                    className={`flex-1 px-2 py-0.5 transition-colors ${i > 0 ? "border-l border-border" : ""} ${
                      problemsOnly === o.value ? "bg-border/60 text-fg" : "text-muted hover:text-fg"
                    }`}
                  >
                    {o.label}
                  </button>
                ))}
              </div>
            )}
          </div>
          <ul ref={listRef} onKeyDown={onListKey} className="relative min-h-0 flex-1 overflow-y-auto p-1">
            {visible.map((s) => {
              const counts = checkCounts(s);
              const current = s === selected;
              return (
                <li key={s.name}>
                  <Link
                    to={searchFor(s.name)}
                    replace
                    aria-current={current ? "true" : undefined}
                    title={s.name}
                    className={`flex items-center gap-2 rounded px-2 py-1.5 text-xs transition-colors ${
                      current ? "bg-accent/15 text-fg" : "text-muted hover:bg-border/40 hover:text-fg"
                    }`}
                  >
                    <StatusIcon status={s.state} />
                    <span className={`min-w-0 flex-1 truncate ${current ? "font-medium" : ""}`}>{s.name}</span>
                    <span className="sr-only">{s.state},</span>
                    <span className={`tabular-nums ${counts.passed < counts.total ? "text-failed" : ""}`}>
                      {counts.passed}/{counts.total}
                    </span>
                  </Link>
                </li>
              );
            })}
            {visible.length === 0 && <li className="px-2 py-3 text-xs text-muted">No tests match.</li>}
          </ul>
        </nav>
        <SkippedTestsList names={skipped} />
      </div>

      <div ref={detailRef} className="min-w-0 scroll-mt-4 space-y-3">
        <div className="sticky top-0 z-20 -mx-4 flex items-center gap-2 border-b border-border bg-bg/95 px-4 py-2 backdrop-blur sm:-mx-6 sm:px-6 lg:hidden">
          <button
            type="button"
            onClick={prev && (() => select(prev.name))}
            disabled={!prev}
            aria-label="Previous test"
            className="rounded border border-border p-1.5 text-muted disabled:opacity-30"
          >
            <ChevronLeft size={16} />
          </button>
          <label className="min-w-0 flex-1">
            <span className="sr-only">Regression test</span>
            <select
              value={selected.name}
              onChange={(e) => select(e.target.value)}
              className="w-full rounded border border-border bg-surface px-2 py-1.5 text-sm text-fg"
            >
              {executed.map((s) => {
                const counts = checkCounts(s);
                return (
                  <option key={s.name} value={s.name}>
                    {s.name} · {s.state ?? "unknown"} · {counts.passed}/{counts.total}
                  </option>
                );
              })}
            </select>
          </label>
          <button
            type="button"
            onClick={next && (() => select(next.name))}
            disabled={!next}
            aria-label="Next test"
            className="rounded border border-border p-1.5 text-muted disabled:opacity-30"
          >
            <ChevronRight size={16} />
          </button>
        </div>
        <SimDetail
          key={selected.name}
          sim={selected}
          runPath={runPath}
          series={series}
          onPrev={prev && (() => select(prev.name))}
          onNext={next && (() => select(next.name))}
        />
      </div>
    </div>
  );
}

function SkippedTestsList({ names }: { names: string[] }) {
  if (names.length === 0) return null;
  return (
    <details className="rounded-xl border border-dashed border-border bg-surface text-xs">
      <summary className="cursor-pointer px-3 py-2 text-muted">Skipped ({names.length})</summary>
      <ul className="max-h-48 space-y-1 overflow-y-auto border-t border-border px-3 py-2">
        {names.map((name) => (
          <li key={name} className="flex items-center gap-2 text-muted">
            <StatusIcon status="skipped" size={12} />
            <span className="truncate font-mono" title={name}>{name}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}
