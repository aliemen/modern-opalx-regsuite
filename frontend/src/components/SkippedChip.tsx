import { SkipForward } from "lucide-react";

/** Marks runs that skipped tests via a test skip config. */
export function SkippedChip({ unit = 0, regression = 0 }: { unit?: number; regression?: number }) {
  const total = unit + regression;
  if (total <= 0) return null;
  const parts = [
    unit > 0 ? `${unit} unit` : null,
    regression > 0 ? `${regression} regression` : null,
  ].filter(Boolean);
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border border-dashed border-muted/50 px-1.5 py-0.5 text-[10px] text-muted"
      title={`Skipped by test skip config: ${parts.join(", ")}`}
    >
      <SkipForward size={10} />
      {total} skipped
    </span>
  );
}
