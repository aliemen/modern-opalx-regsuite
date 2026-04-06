interface Props {
  status: string;
  size?: "sm" | "md";
}

const MAP: Record<string, string> = {
  passed: "bg-passed/20 text-passed border border-passed/40",
  failed: "bg-failed/20 text-failed border border-failed/40",
  broken: "bg-broken/20 text-broken border border-broken/40",
  running: "bg-accent/20 text-accent border border-accent/40 animate-pulse",
  cancelled: "bg-cancelled/20 text-cancelled border border-cancelled/40",
  unknown: "bg-muted/20 text-muted border border-muted/40",
};

export function StatusBadge({ status, size = "sm" }: Props) {
  const cls = MAP[status] ?? MAP.unknown;
  const pad = size === "md" ? "px-3 py-1 text-sm" : "px-2 py-0.5 text-xs";
  return (
    <span className={`inline-flex items-center rounded-full font-medium ${pad} ${cls}`}>
      {status}
    </span>
  );
}
