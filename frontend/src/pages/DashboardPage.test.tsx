import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getAllRuns, getLatestMatrix } from "../api/results";
import { getQueueState } from "../api/runs";
import { getCurrentUser } from "../api/user";
import { useArchiveMutations } from "../hooks/useArchiveMutations";
import { installLocalStorageMock, makeRun } from "../test/fixtures";
import { DashboardPage } from "./DashboardPage";

vi.mock("../api/runs", () => ({
  getQueueState: vi.fn(),
  cancelQueuedRun: vi.fn(),
}));

vi.mock("../api/results", () => ({
  getAllRuns: vi.fn(),
  getLatestMatrix: vi.fn(),
}));

vi.mock("../api/user", () => ({ getCurrentUser: vi.fn() }));

vi.mock("../hooks/useArchiveMutations", () => ({
  useArchiveMutations: vi.fn(),
}));

vi.mock("../components/TrendsPanel", () => ({
  TrendsPanel: ({ archs }: { archs: string[] }) => (
    <div data-testid="trends-panel">{archs.join(",")}</div>
  ),
}));

vi.mock("../components/StatsPanel", () => ({
  StatsPanel: () => <div data-testid="stats-panel" />,
}));

installLocalStorageMock();

const archiveResult = {
  changed: 0,
  skipped_active: [],
  not_found: [],
  failed_move: [],
};

let archiveCellsMutate: ReturnType<typeof vi.fn>;

const DAY = 24 * 3600 * 1000;

function cell(branch: string, arch: string, runCount: number, daysAgo = 2) {
  const started_at = new Date(Date.now() - daysAgo * DAY).toISOString();
  return { run: makeRun({ branch, arch, run_id: `${arch}-run`, started_at }), run_count: runCount };
}

function renderDashboard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/"]}>
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("DashboardPage", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.mocked(getQueueState).mockResolvedValue({ machines: [] });
    vi.mocked(getCurrentUser).mockResolvedValue({ username: "demo-user" });
    vi.mocked(getAllRuns).mockResolvedValue({
      runs: [makeRun({ branch: "feature/archive", run_id: "recent-run" })],
      total: 1,
    });
    vi.mocked(getLatestMatrix).mockResolvedValue([
      {
        branch: "master",
        last_activity: "2026-05-18T10:00:00Z",
        cells: {
          "cpu-serial": cell("master", "cpu-serial", 1),
          "cuda-daint": cell("master", "cuda-daint", 4),
        },
      },
      {
        branch: "feature/archive",
        last_activity: "2026-05-18T10:00:00Z",
        cells: { "cpu-serial": cell("feature/archive", "cpu-serial", 1) },
      },
    ]);
    archiveCellsMutate = vi.fn(async () => [archiveResult]);
    vi.mocked(useArchiveMutations).mockReturnValue({
      archiveBranch: { mutateAsync: vi.fn(), isPending: false },
      archiveCells: { mutateAsync: archiveCellsMutate, isPending: false },
      hardDeleteCells: { mutateAsync: vi.fn(), isPending: false },
      collectSkippedActive: () => [],
      collectFailedMove: () => [],
    } as unknown as ReturnType<typeof useArchiveMutations>);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it("shows recent runs above the branch matrix", async () => {
    renderDashboard();
    expect(await screen.findByRole("heading", { name: "Recent runs" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: /Branches/ })).toBeInTheDocument();
    // [0] is the desktop table; the mobile list repeats the row.
    const [recentLink] = await screen.findAllByRole("link", { name: "feature/archive · cpu-serial" });
    expect(recentLink).toHaveAttribute("href", "/results/feature%2Farchive/cpu-serial/recent-run");
    // Trends get master's archs, most-run first.
    expect(screen.getByTestId("trends-panel")).toHaveTextContent("cuda-daint,cpu-serial");
  });

  it("leaves master archs without a run in the last 30 days out of the trends", async () => {
    vi.mocked(getLatestMatrix).mockResolvedValue([
      {
        branch: "master",
        last_activity: "2026-05-18T10:00:00Z",
        cells: {
          "cpu-serial": cell("master", "cpu-serial", 1),
          "cuda-ampere80": cell("master", "cuda-ampere80", 13, 120),
        },
      },
    ]);
    renderDashboard();
    expect(await screen.findByTestId("trends-panel")).toHaveTextContent(/^cpu-serial$/);
  });

  it("archives every build of a selected branch, master included", async () => {
    renderDashboard();
    await userEvent.click(await screen.findByRole("button", { name: "Select" }));
    await userEvent.click(screen.getByLabelText("Select all builds of master"));
    expect(screen.getByText("2 selected")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Archive" }));
    expect(screen.getByText("Archive 2 branch/build cells?")).toBeInTheDocument();
    const confirm = screen.getAllByRole("button", { name: "Archive" }).at(-1)!;
    await userEvent.click(confirm);

    await waitFor(() =>
      expect(archiveCellsMutate).toHaveBeenCalledWith({
        cells: [
          { branch: "master", arch: "cpu-serial" },
          { branch: "master", arch: "cuda-daint" },
        ],
        archived: true,
      })
    );
  });
});
