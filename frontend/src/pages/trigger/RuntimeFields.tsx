import type { RunConfigSummary } from "../../api/runs";

interface RuntimeFieldsProps {
  selectedRunConfig: RunConfigSummary | null;
  mpiRanks: number;
  opalxInfoLevel: number;
  showMpiRanks?: boolean;
  showOpalxInfoLevel?: boolean;
  onMpiRanksChange: (value: number) => void;
  onOpalxInfoLevelChange: (value: number) => void;
}

export function RuntimeFields({
  selectedRunConfig,
  mpiRanks,
  opalxInfoLevel,
  showMpiRanks = true,
  showOpalxInfoLevel = true,
  onMpiRanksChange,
  onOpalxInfoLevelChange,
}: RuntimeFieldsProps) {
  if (!showMpiRanks && !showOpalxInfoLevel) return null;

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {showMpiRanks && (
        <div>
          <label htmlFor="mpi-ranks" className="block text-sm text-muted mb-1">
            MPI ranks
          </label>
          <input
            id="mpi-ranks"
            type="number"
            min={1}
            max={selectedRunConfig?.max_mpi_ranks ?? undefined}
            step={1}
            value={mpiRanks}
            onChange={(e) =>
              onMpiRanksChange(Number.parseInt(e.target.value, 10) || 1)
            }
            className="w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
          />
        </div>
      )}
      {showOpalxInfoLevel && (
        <div>
          <label
            htmlFor="opalx-info-level"
            className="block text-sm text-muted mb-1"
          >
            OPALX info level
          </label>
          <input
            id="opalx-info-level"
            type="number"
            min={0}
            step={1}
            value={opalxInfoLevel}
            onChange={(e) =>
              onOpalxInfoLevelChange(Math.max(0, Number.parseInt(e.target.value, 10) || 0))
            }
            className="w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
          />
        </div>
      )}
    </div>
  );
}
