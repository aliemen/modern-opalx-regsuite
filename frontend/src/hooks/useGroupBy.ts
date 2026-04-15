import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { GroupBy } from "../lib/grouping";

const VALID: GroupBy[] = ["branch", "arch", "date", "regtest-branch"];
const STORAGE_KEY = "opalx-dashboard-group";

function isValid(s: string | null): s is GroupBy {
  return s !== null && (VALID as string[]).includes(s);
}

function loadDefault(): GroupBy {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (isValid(v)) return v;
  } catch {
    /* ignore */
  }
  return "branch";
}

/**
 * Read/write the dashboard's grouping axis from a URL query param
 * (`?group=branch|arch|date`). The URL is the source of truth so the
 * grouping survives refresh and is shareable; localStorage holds the user's
 * default for the next visit.
 */
export function useGroupBy(): [GroupBy, (next: GroupBy) => void] {
  const [params, setParams] = useSearchParams();
  const fromUrl = params.get("group");
  const [value, setValue] = useState<GroupBy>(() =>
    isValid(fromUrl) ? fromUrl : loadDefault()
  );

  // Keep the URL in sync with the resolved value on mount (if the URL was
  // empty, we wrote the localStorage default into state — push it to the URL
  // so refreshes are stable).
  useEffect(() => {
    if (!isValid(fromUrl)) {
      const next = new URLSearchParams(params);
      next.set("group", value);
      setParams(next, { replace: true });
    } else if (fromUrl !== value) {
      setValue(fromUrl);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fromUrl]);

  const setGroupBy = useCallback(
    (next: GroupBy) => {
      setValue(next);
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch {
        /* ignore */
      }
      const nextParams = new URLSearchParams(params);
      nextParams.set("group", next);
      setParams(nextParams, { replace: true });
    },
    [params, setParams]
  );

  return [value, setGroupBy];
}
