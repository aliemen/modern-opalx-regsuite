import { LatestMasterMatrix } from "./stats/LatestMasterMatrix";
import { NewlyBrokenCard } from "./stats/NewlyBrokenCard";
import { SuiteDurationCard } from "./stats/SuiteDurationCard";
import { ActivitySparkline } from "./stats/ActivitySparkline";
import { UsersLeaderboardCard } from "./stats/UsersLeaderboardCard";
import { FlakinessCard } from "./stats/FlakinessCard";

/**
 * Composes the developer-facing stats column. Each card fetches its own
 * endpoint via React Query so the cards are independently shippable and
 * any single-card failure doesn't take down the whole panel.
 */
export function StatsPanel({ flakinessArchs }: { flakinessArchs?: string[] }) {
  return (
    <div className="space-y-4">
      <LatestMasterMatrix />
      <NewlyBrokenCard />
      <FlakinessCard archs={flakinessArchs} />
      <SuiteDurationCard />
      <ActivitySparkline />
      <UsersLeaderboardCard />
    </div>
  );
}
