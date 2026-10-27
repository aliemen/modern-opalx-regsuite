import type { SkipConfigSnapshot } from "../../api/results";
import { Fact } from "./RunFacts";

export function SkipConfigInfo({ snapshot }: { snapshot: SkipConfigSnapshot }) {
  const names = [...snapshot.regression_tests, ...snapshot.unit_tests];
  return (
    <Fact label="Test Skip Config" wide={names.length > 0}>
      <span className="block">{snapshot.name}</span>
      {names.length > 0 && (
        <span className="block text-muted text-xs font-mono">{names.join(", ")}</span>
      )}
    </Fact>
  );
}
