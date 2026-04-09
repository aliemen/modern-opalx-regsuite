import { useEffect, useRef, useState } from "react";
import { getAccessToken } from "../api/client";

interface Props {
  runId?: string;
  onStatusChange?: (status: string) => void;
  onPhaseChange?: (phase: string) => void;
  onLogLine?: (line: string) => void;
}

const MAX_LINES = 5_000;
const FLUSH_MS = 250; // flush at most 4×/sec; cheap because DOM is updated directly

export function LogViewer({ runId, onStatusChange, onPhaseChange, onLogLine }: Props) {
  // Minimal React state — only what affects rendered structure, not log content.
  const [hasLines, setHasLines] = useState(false);
  const [truncated, setTruncated] = useState(0);

  const containerRef = useRef<HTMLDivElement>(null);
  // Lines are stored in a plain ref and written directly into the <pre> DOM node,
  // completely bypassing React's reconciler for text updates.
  const preRef = useRef<HTMLPreElement>(null);
  const autoScrollRef = useRef(true);
  const bufRef = useRef<string[]>([]);
  const linesRef = useRef<string[]>([]);
  const truncatedRef = useRef(0);
  const hasLinesRef = useRef(false);
  const flushTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  // Keep a stable ref so the flush closure always calls the latest callback.
  const onLogLineRef = useRef(onLogLine);
  useEffect(() => { onLogLineRef.current = onLogLine; }, [onLogLine]);

  useEffect(() => {
    const token = getAccessToken();
    const base = runId ? `/api/runs/${runId}/stream` : `/api/runs/current/stream`;
    const storedLastId = runId ? sessionStorage.getItem(`sse-last-id-${runId}`) : null;
    const params = new URLSearchParams();
    if (token) params.set("token", token);
    if (storedLastId !== null) params.set("last_id", storedLastId);
    const url = `${base}?${params.toString()}`;
    const es = new EventSource(url);

    function applyLines(incoming: string[]) {
      if (incoming.length === 0) return;

      incoming.forEach((line) => onLogLineRef.current?.(line));

      linesRef.current.push(...incoming);
      if (linesRef.current.length > MAX_LINES) {
        const dropped = linesRef.current.length - MAX_LINES;
        truncatedRef.current += dropped;
        linesRef.current = linesRef.current.slice(-MAX_LINES);
        setTruncated(truncatedRef.current); // rare, triggers React update for notice
      }

      // Direct DOM write — no React reconciliation, no diffing.
      if (preRef.current) {
        preRef.current.textContent = linesRef.current.join("\n");
      }

      // Swap "Waiting…" placeholder once.
      if (!hasLinesRef.current) {
        hasLinesRef.current = true;
        setHasLines(true);
      }

      // Auto-scroll if at the bottom.
      const el = containerRef.current;
      if (el && autoScrollRef.current) {
        el.scrollTop = el.scrollHeight;
      }
    }

    function flush() {
      applyLines(bufRef.current.splice(0));
    }

    flushTimer.current = setInterval(flush, FLUSH_MS);

    es.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data) as {
          type: string;
          line?: string;
          phase?: string;
          status?: string;
        };

        // Persist the last-event-id so a page refresh can resume from here.
        if (runId && e.lastEventId) {
          sessionStorage.setItem(`sse-last-id-${runId}`, e.lastEventId);
        }

        if (event.type === "log" && event.line !== undefined) {
          bufRef.current.push(event.line);
        } else if (event.type === "phase" && event.phase) {
          onPhaseChange?.(event.phase);
        } else if (event.type === "status" && event.status) {
          flush(); // drain buffer before signalling done
          onStatusChange?.(event.status);
          es.close();
        }
      } catch {
        // Ignore parse errors.
      }
    };

    es.onerror = () => {
      flush();
      es.close();
    };

    return () => {
      if (flushTimer.current) clearInterval(flushTimer.current);
      es.close();
      // Reset all internal state so the next run starts clean.
      bufRef.current = [];
      linesRef.current = [];
      truncatedRef.current = 0;
      hasLinesRef.current = false;
      setHasLines(false);
      setTruncated(0);
      if (preRef.current) preRef.current.textContent = "";
      // Don't clear sse-last-id here — it must survive page refreshes.
      // It is keyed by runId, so stale entries from old runs are harmless.
    };
  }, [runId]); // eslint-disable-line react-hooks/exhaustive-deps

  function handleScroll() {
    const el = containerRef.current;
    if (!el) return;
    autoScrollRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  }

  return (
    <div className="flex flex-col gap-1">
      {truncated > 0 && (
        <div className="text-xs text-muted bg-surface border border-border rounded px-3 py-1.5">
          {truncated.toLocaleString()} earlier lines not shown (buffer capped at {MAX_LINES.toLocaleString()}).
          Use the download link below to get the full log.
        </div>
      )}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="log-viewer bg-bg rounded-md border border-border p-4 h-[60vh] overflow-y-auto font-mono text-xs leading-5"
      >
        {!hasLines ? (
          <span className="text-muted">Waiting for output…</span>
        ) : (
          /* Single <pre> node — React never touches its content after mount. */
          <pre ref={preRef} className="text-fg whitespace-pre-wrap m-0 font-mono" />
        )}
      </div>
    </div>
  );
}
