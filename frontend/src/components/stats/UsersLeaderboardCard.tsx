import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Trophy } from "lucide-react";
import { getUsersLeaderboard } from "../../api/stats";

/** Approx. height for ~5 user rows. Anything beyond scrolls inside the card
 *  so the panel layout stays predictable regardless of how many users exist. */
const MAX_LIST_HEIGHT = "11.25rem"; // 5 rows * ~2.25rem each

/**
 * "Top users" leaderboard card. Counts every run (active + archived) per
 * ``triggered_by`` and shows the result sorted by run count descending.
 *
 * Each row links to the Activity page filtered by that user, so the
 * leaderboard doubles as a navigation shortcut into per-user history.
 */
export function UsersLeaderboardCard() {
  const { data, isLoading } = useQuery({
    queryKey: ["users-leaderboard", "all"],
    queryFn: () => getUsersLeaderboard("all"),
    refetchInterval: 60_000,
  });

  const users = data?.users ?? [];
  const maxCount = users[0]?.count ?? 0;

  return (
    <div className="bg-surface border border-border rounded-xl p-5">
      <h2 className="text-fg font-medium text-sm mb-4 flex items-center gap-2">
        <Trophy size={14} className="text-muted" />
        Top users
      </h2>
      {isLoading && !data ? (
        <p className="text-muted text-xs py-2">Loading…</p>
      ) : users.length === 0 ? (
        <p className="text-muted text-xs py-2">No runs recorded yet.</p>
      ) : (
        <div
          className="overflow-y-auto pr-1 -mr-1 space-y-1"
          style={{ maxHeight: MAX_LIST_HEIGHT }}
        >
          {users.map((u, i) => {
            // Subtle bar background visualises share of the leader. Hidden
            // when only one user exists (no comparison to make).
            const pct =
              maxCount > 0 ? Math.round((u.count / maxCount) * 100) : 0;
            return (
              <Link
                key={u.username}
                to={`/activity?user=${encodeURIComponent(u.username)}`}
                className="relative flex items-center gap-2 text-xs px-2 py-1.5 rounded hover:bg-border/30 transition-colors"
                title={`Show ${u.username}'s runs in the Activity tab`}
              >
                <span
                  aria-hidden
                  className="absolute inset-y-0 left-0 bg-accent/10 rounded pointer-events-none"
                  style={{ width: `${pct}%` }}
                />
                <span className="relative text-muted w-5 tabular-nums">
                  {i + 1}.
                </span>
                <span className="relative text-fg font-mono truncate flex-1">
                  {u.username}
                </span>
                <span className="relative text-muted tabular-nums">
                  {u.count}
                </span>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
