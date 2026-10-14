import { useState } from "react";
import { TEST_NAME_RE, type SkipCandidate } from "../../api/skipConfigs";

interface Props {
  /** Panel heading, e.g. "Regression tests". */
  title: string;
  /** Singular noun for labels, e.g. "regression test". */
  noun: string;
  candidates: SkipCandidate[];
  selected: string[];
  onChange: (next: string[]) => void;
}

function fmtSeconds(s: number | null): string {
  return s == null ? "" : `${Math.round(s)} s`;
}

export function SkipTestPicker({ title, noun, candidates, selected, onChange }: Props) {
  const [query, setQuery] = useState("");
  const [extra, setExtra] = useState("");
  const [extraError, setExtraError] = useState<string | null>(null);

  const selectedSet = new Set(selected);
  const known = new Set(candidates.map((c) => c.name));
  const unlisted = selected.filter((name) => !known.has(name));
  const q = query.trim().toLowerCase();
  const visible = candidates.filter((c) => !q || c.name.toLowerCase().includes(q));

  function toggle(name: string) {
    onChange(
      selectedSet.has(name)
        ? selected.filter((n) => n !== name)
        : [...selected, name].sort(),
    );
  }

  function addExtra() {
    const name = extra.trim();
    if (!TEST_NAME_RE.test(name)) {
      setExtraError("Use letters, digits, '.', '_', '+' or '-'.");
      return;
    }
    if (!selectedSet.has(name)) onChange([...selected, name].sort());
    setExtra("");
    setExtraError(null);
  }

  return (
    <fieldset className="rounded-lg border border-border p-3 space-y-2 min-w-0">
      <legend className="px-1 text-sm text-fg">
        {title} <span className="text-muted text-xs">· {selected.length} selected</span>
      </legend>
      <input
        aria-label={`Search ${title}`}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search"
        className="w-full bg-bg border border-border rounded-md px-3 py-1.5 text-sm text-fg focus:outline-none focus:border-accent"
      />
      <ul className="max-h-64 overflow-y-auto space-y-0.5">
        {visible.map((c) => (
          <li key={c.name}>
            <label className="flex items-center gap-2 text-xs py-0.5 cursor-pointer">
              <input
                type="checkbox"
                aria-label={`Skip ${c.name}`}
                checked={selectedSet.has(c.name)}
                onChange={() => toggle(c.name)}
                className="accent-accent"
              />
              <span className="flex-1 truncate font-mono text-fg">{c.name}</span>
              <span className="text-muted tabular-nums">{fmtSeconds(c.median_seconds)}</span>
            </label>
          </li>
        ))}
        {unlisted.map((name) => (
          <li key={name}>
            <label className="flex items-center gap-2 text-xs py-0.5 cursor-pointer">
              <input
                type="checkbox"
                aria-label={`Skip ${name}`}
                checked
                onChange={() => toggle(name)}
                className="accent-accent"
              />
              <span className="flex-1 truncate font-mono text-fg">{name}</span>
              <span className="text-muted">not seen recently</span>
            </label>
          </li>
        ))}
      </ul>
      <div className="flex gap-2">
        <input
          aria-label={`Add ${noun} name`}
          value={extra}
          onChange={(e) => setExtra(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              addExtra();
            }
          }}
          placeholder={`Add ${noun} not listed`}
          className="min-w-0 flex-1 bg-bg border border-border rounded-md px-3 py-1.5 text-xs text-fg font-mono focus:outline-none focus:border-accent"
        />
        <button
          type="button"
          onClick={addExtra}
          className="shrink-0 rounded-md border border-border px-3 py-1.5 text-xs text-muted hover:text-fg"
        >
          Add {noun}
        </button>
      </div>
      {extraError && <p className="text-failed text-xs">{extraError}</p>}
    </fieldset>
  );
}
