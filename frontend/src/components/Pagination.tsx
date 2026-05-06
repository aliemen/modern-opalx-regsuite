import { ChevronLeft, ChevronRight } from "lucide-react";

const PAGE_SIZES = [25, 50, 100] as const;

interface PaginationProps {
  total: number;
  pageSize: number;
  offset: number;
  onPageSizeChange: (size: number) => void;
  onOffsetChange: (offset: number) => void;
}

export function Pagination({
  total,
  pageSize,
  offset,
  onPageSizeChange,
  onOffsetChange,
}: PaginationProps) {
  if (total === 0) return null;

  const from = offset + 1;
  const to = Math.min(offset + pageSize, total);
  const hasPrev = offset > 0;
  const hasNext = offset + pageSize < total;

  return (
    <div className="flex flex-col gap-3 mt-4 text-xs text-muted sm:flex-row sm:items-center sm:justify-between">
      <span className="tabular-nums">
        Showing {from}–{to} of {total}
      </span>

      <div className="flex items-center gap-2 sm:gap-3">
        <button
          onClick={() => onOffsetChange(Math.max(0, offset - pageSize))}
          disabled={!hasPrev}
          className="flex flex-1 items-center justify-center gap-0.5 px-2 py-1 border border-border rounded-md hover:text-fg hover:border-accent/30 transition-colors disabled:opacity-40 disabled:pointer-events-none sm:flex-none"
        >
          <ChevronLeft size={13} />
          Prev
        </button>
        <button
          onClick={() => onOffsetChange(offset + pageSize)}
          disabled={!hasNext}
          className="flex flex-1 items-center justify-center gap-0.5 px-2 py-1 border border-border rounded-md hover:text-fg hover:border-accent/30 transition-colors disabled:opacity-40 disabled:pointer-events-none sm:flex-none"
        >
          Next
          <ChevronRight size={13} />
        </button>
      </div>

      <select
        value={pageSize}
        onChange={(e) => onPageSizeChange(Number(e.target.value))}
        className="w-full bg-bg border border-border rounded-md px-2 py-1 text-fg text-xs focus:outline-none focus:border-accent sm:w-auto"
      >
        {PAGE_SIZES.map((s) => (
          <option key={s} value={s}>
            {s} / page
          </option>
        ))}
      </select>
    </div>
  );
}
