import { useEffect, useState } from "react";
import { formatSeconds } from "../lib/time";

/** Live "elapsed since *since*" label that re-renders only itself each second. */
export function Elapsed({ since }: { since: string }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  return <>{formatSeconds((now - new Date(since).getTime()) / 1000)}</>;
}
