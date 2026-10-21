import { useCallback, useState } from "react";
import { useSearchParams } from "react-router-dom";

export type RecentScope = "all" | "mine";

const STORAGE_KEY = "opalx-recent-scope";

function parse(s: string | null): RecentScope | null {
  return s === "all" || s === "mine" ? s : null;
}

function loadStored(): RecentScope | null {
  try {
    return parse(localStorage.getItem(STORAGE_KEY));
  } catch {
    return null;
  }
}

/**
 * Whose runs the dashboard "Recent runs" table shows. `?scope=` wins so a
 * link can force it; otherwise the viewer's last choice from localStorage;
 * otherwise everyone's.
 */
export function useRecentScope(): [RecentScope, (next: RecentScope) => void] {
  const [params, setParams] = useSearchParams();
  const [stored, setStored] = useState(loadStored);
  const scope = parse(params.get("scope")) ?? stored ?? "all";

  const setScope = useCallback(
    (next: RecentScope) => {
      setStored(next);
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch {
        /* storage unavailable: the URL still carries the choice */
      }
      const nextParams = new URLSearchParams(params);
      nextParams.set("scope", next);
      setParams(nextParams, { replace: true });
    },
    [params, setParams]
  );

  return [scope, setScope];
}
