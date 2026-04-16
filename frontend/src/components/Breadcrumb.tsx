import { Link, useSearchParams } from "react-router-dom";
import { ChevronRight } from "lucide-react";

export interface Crumb {
  /** Label shown to the user. */
  label: string;
  /** Relative path. When omitted, the crumb is rendered as plain text (the
   *  "current page" crumb). The Dashboard crumb is a special case — its `to`
   *  is auto-composed from the current `?group=` query param so the user
   *  lands back on the grouping they were using. */
  to?: string;
  /** Optional tooltip. */
  title?: string;
}

interface BreadcrumbProps {
  crumbs: Crumb[];
}

/**
 * Horizontal breadcrumb trail rendered at the top of run-list and run-detail
 * pages. The first crumb is always a link back to the dashboard, preserving
 * the user's current grouping via the ``?group=`` query param inherited from
 * the URL. Subsequent crumbs are supplied by the caller.
 *
 * Intentionally tiny: no multi-level dropdowns, no active-aria styling. The
 * only responsibility is "show me the path, let me click a parent."
 */
export function Breadcrumb({ crumbs }: BreadcrumbProps) {
  const [params] = useSearchParams();
  const group = params.get("group");
  const dashHref = group ? `/?group=${encodeURIComponent(group)}` : "/";

  const all: Crumb[] = [
    { label: "Dashboard", to: dashHref },
    ...crumbs,
  ];

  return (
    <nav
      className="flex items-center flex-wrap gap-1 text-sm mb-4"
      aria-label="Breadcrumb"
    >
      {all.map((crumb, i) => {
        const isLast = i === all.length - 1;
        return (
          <span key={i} className="flex items-center gap-1">
            {i > 0 && (
              <ChevronRight size={12} className="text-muted shrink-0" />
            )}
            {crumb.to && !isLast ? (
              <Link
                to={crumb.to}
                title={crumb.title}
                className="text-muted hover:text-fg transition-colors"
              >
                {crumb.label}
              </Link>
            ) : (
              <span
                className={isLast ? "text-fg font-medium" : "text-muted"}
                title={crumb.title}
              >
                {crumb.label}
              </span>
            )}
          </span>
        );
      })}
    </nav>
  );
}
