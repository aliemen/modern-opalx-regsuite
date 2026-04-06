import { useEffect, useRef, useState } from "react";
import { getAccessToken } from "../api/client";

interface Props {
  onStatusChange?: (status: string) => void;
  onPhaseChange?: (phase: string) => void;
}

const MAX_LINES = 5_000;
const FLUSH_MS = 100; // batch SSE lines and re-render at most 10×/sec

export function LogViewer({ onStatusChange, onPhaseChange }: Props) {
  const [lines, setLines] = useState<string[]>([]);
  const [truncated, setTruncated] = useState(0); // lines dropped from the top
  const containerRef = useRef<HTMLDivElement>(null);
  const autoScrollRef = useRef(true);
  // Buffer for incoming lines between flushes.
  const bufRef = useRef<string[]>([]);
  const flushTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const token = getAccessToken();
    const url = `/api/runs/current/stream${token ? `?token=${encodeURIComponent(token)}` : ""}`;
    const es = new EventSource(url);

    // Flush buffered lines into React state.
    function flush() {
      const incoming = bufRef.current.splice(0);
      if (incoming.length === 0) return;
      setLines((prev) => {
        const combined = [...prev, ...incoming];
        if (combined.length <= MAX_LINES) return combined;
        const dropped = combined.length - MAX_LINES;
        setTruncated((t) => t + dropped);
        return combined.slice(-MAX_LINES);
      });
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

        if (event.type === "log" && event.line !== undefined) {
          bufRef.current.push(event.line);
        } else if (event.type === "phase" && event.phase) {
          onPhaseChange?.(event.phase);
        } else if (event.type === "status" && event.status) {
          // Flush whatever is buffered before signalling done.
          flush();
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
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-scroll only when at bottom.
  useEffect(() => {
    const el = containerRef.current;
    if (!el || !autoScrollRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, [lines]);

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
        className="log-viewer bg-bg rounded-md border border-border p-4 h-[60vh] overflow-y-auto text-slate-300 font-mono text-xs leading-5"
      >
        {lines.length === 0 ? (
          <span className="text-muted">Waiting for output…</span>
        ) : (
          lines.map((ln, i) => (
            <div key={i}>{ln || "\u00a0"}</div>
          ))
        )}
      </div>
    </div>
  );
}
