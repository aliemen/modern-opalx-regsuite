import { useEffect, useRef, useState } from "react";
import { getAccessToken } from "../api/client";

interface Props {
  onStatusChange?: (status: string) => void;
  onPhaseChange?: (phase: string) => void;
}

const MAX_LINES = 10_000;

export function LogViewer({ onStatusChange, onPhaseChange }: Props) {
  const [lines, setLines] = useState<string[]>([]);
  const containerRef = useRef<HTMLDivElement>(null);
  const autoScrollRef = useRef(true);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    // Build the URL with the auth token as a query param since EventSource
    // cannot set custom headers.
    const token = getAccessToken();
    const url = `/api/runs/current/stream${token ? `?token=${encodeURIComponent(token)}` : ""}`;
    const es = new EventSource(url);
    esRef.current = es;

    es.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data) as {
          type: string;
          line?: string;
          phase?: string;
          status?: string;
          id?: number;
        };

        if (event.type === "log" && event.line !== undefined) {
          setLines((prev) => {
            const next = [...prev, event.line!];
            return next.length > MAX_LINES ? next.slice(-MAX_LINES) : next;
          });
        } else if (event.type === "phase" && event.phase) {
          onPhaseChange?.(event.phase);
        } else if (event.type === "status" && event.status) {
          onStatusChange?.(event.status);
          es.close();
        }
      } catch {
        // Ignore parse errors.
      }
    };

    es.onerror = () => {
      es.close();
    };

    return () => {
      es.close();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-scroll logic.
  useEffect(() => {
    const el = containerRef.current;
    if (!el || !autoScrollRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, [lines]);

  function handleScroll() {
    const el = containerRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    autoScrollRef.current = atBottom;
  }

  return (
    <div
      ref={containerRef}
      onScroll={handleScroll}
      className="log-viewer bg-bg rounded-md border border-border p-4 h-[60vh] overflow-y-auto text-slate-300"
    >
      {lines.length === 0 ? (
        <span className="text-muted">Waiting for output…</span>
      ) : (
        lines.map((ln, i) => (
          <div key={i} className="leading-5">
            {ln || "\u00a0"}
          </div>
        ))
      )}
    </div>
  );
}
