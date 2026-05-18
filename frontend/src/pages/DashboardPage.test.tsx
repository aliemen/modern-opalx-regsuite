import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RunIndexEntry } from "../api/results";
import { getQueueState } from "../api/runs";
import { useArchiveMutations } from "../hooks/useArchiveMutations";
import { useLatestRuns } from "../hooks/useLatestRuns";
import { DashboardPage } from "./DashboardPage";

vi.mock("../api/runs", () => ({
  getQueueState: vi.fn(async () => ({ machines: [] })),
}));

vi.mock("../hooks/useLatestRuns", () => ({
  useLatestRuns: vi.fn(),
}));

vi.mock("../hooks/useArchiveMutations", () => ({
  useArchiveMutations: vi.fn(),
}));

vi.mock("../components/TrendsPanel", () => ({
  TrendsPanel: () => <div data-testid="trends-panel" />,
}));

vi.mock("../components/StatsPanel", () => ({
  StatsPanel: () => <div data-testid="stats-panel" />,
}));

vi.mock("../components/QueuePanel", () => ({
  QueuePanel: () => <div data-testid="queue-panel" />,
}));

const localStorageStore = new Map<string, string>();
const localStorageMock: Storage = {
  get length() {
    return localStorageStore.size;
  },
  clear() {
    localStorageStore.clear();
  },
  getItem(key: string) {
    return localStorageStore.get(key) ?? null;
  },
  key(index: number) {
    return Array.from(localStorageStore.keys())[index] ?? null;
  },
  removeItem(key: string) {
    localStorageStore.delete(key);
  },
  setItem(key: string, value: string) {
    localStorageStore.set(key, value);
  },
};

Object.defineProperty(window, "localStorage", {
  value: localStorageMock,
  configurable: true,
});
Object.defineProperty(globalThis, "localStorage", {
  value: localStorageMock,
  configurable: true,
});

function run(branch: string, arch: string, runId: string): RunIndexEntry {
  return {
    branch,
    arch,
    run_id: runId,
    started_at: "2026-05-18T10:00:00Z",
    finished_at: "2026-05-18T10:01:00Z",
    status: "passed",
    triggered_by: "demo-user",
    regtest_branch: "master",
    connection_name: "local",
    unit_tests_total: 1,
    unit_tests_failed: 0,
    regression_total: 1,
    regression_passed: 1,
    regression_failed: 0,
    regression_broken: 0,
    archived: false,
    public: false,
    run_options: {
      skip_unit: false,
      skip_regression: false,
      clean_build: false,
      custom_cmake_args: [],
      mpi_ranks: 1,
      opalx_info_level: 2,
      slurm_resources: null,
    },
    rerun_of: null,
  };
}

const archiveResult = {
  changed: 0,
  skipped_active: [],
  not_found: [],
  failed_move: [],
};

let archiveBranchMutate: ReturnType<typeof vi.fn>;
let archiveCellsMutate: ReturnType<typeof vi.fn>;

function renderDashboard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/?group=branch"]}>
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("DashboardPage archive policy", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.mocked(getQueueState).mockResolvedValue({ machines: [] });
    vi.mocked(useLatestRuns).mockReturnValue({
      cells: [
        { branch: "master", arch: "cpu-serial", run: run("master", "cpu-serial", "master-run") },
        {
          branch: "feature/archive",
          arch: "cpu-serial",
          run: run("feature/archive", "cpu-serial", "feature-run"),
        },
      ],
      branches: {
        master: ["cpu-serial"],
        "feature/archive": ["cpu-serial"],
      },
      runCounts: new Map([
        ["master/cpu-serial", 1],
        ["feature/archive/cpu-serial", 1],
      ]),
      isLoading: false,
    });
    archiveBranchMutate = vi.fn(async () => archiveResult);
    archiveCellsMutate = vi.fn(async () => [archiveResult]);
    vi.mocked(useArchiveMutations).mockReturnValue({
      archiveBranch: {
        mutateAsync: archiveBranchMutate,
        isPending: false,
      },
      archiveCells: {
        mutateAsync: archiveCellsMutate,
        isPending: false,
      },
      hardDeleteCells: {
        mutateAsync: vi.fn(),
        isPending: false,
      },
      collectSkippedActive: () => [],
      collectFailedMove: () => [],
    } as unknown as ReturnType<typeof useArchiveMutations>);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it("shows the branch archive action for master", async () => {
    const user = userEvent.setup();
    renderDashboard();

    const archiveButtons = await screen.findAllByRole("button", {
      name: "Archive branch",
    });
    await user.click(archiveButtons[0]);

    expect(
      await screen.findByText('Archive branch "master"?')
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Archive" }));

    await waitFor(() => {
      expect(archiveBranchMutate).toHaveBeenCalledWith({
        branch: "master",
        archived: true,
      });
    });
  });

  it("allows master cells to be selected for bulk archive", async () => {
    const user = userEvent.setup();
    renderDashboard();

    const checkboxes = await screen.findAllByRole("checkbox");
    expect(checkboxes[0]).toBeEnabled();
    await user.click(checkboxes[0]);

    expect(await screen.findByText("1 run selected")).toBeInTheDocument();
    for (const checkbox of checkboxes) {
      expect(checkbox).toBeEnabled();
    }
  });
});
