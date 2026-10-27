import type { ReactNode } from "react";

/** Label/value pairs that flow into as many columns as the width allows. */
export function FactGrid({ children }: { children: ReactNode }) {
  return (
    <dl className="grid gap-x-6 gap-y-3 text-sm [grid-template-columns:repeat(auto-fill,minmax(min(100%,9.5rem),1fr))] sm:[grid-template-columns:repeat(auto-fill,minmax(13rem,1fr))]">
      {children}
    </dl>
  );
}

export function Fact({ label, wide = false, children }: { label: string; wide?: boolean; children: ReactNode }) {
  return (
    <div className={`min-w-0 ${wide ? "col-span-full" : ""}`}>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 break-words text-fg">{children}</dd>
    </div>
  );
}
