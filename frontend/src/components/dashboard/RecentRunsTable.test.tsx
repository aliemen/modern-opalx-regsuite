import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getAllRuns } from "../../api/results";
import { cancelQueuedRun, type MachineStatus } from "../../api/runs";
import { getCurrentUser } from "../../api/user";
import { installLocalStorageMock, makeRun } from "../../test/fixtures";
import { RecentRunsTable } from "./RecentRunsTable";

vi.mock("../../api/results", () => ({ getAllRuns: vi.fn() }));
vi.mock("../../api/user", () => ({ getCurrentUser: vi.fn() }));
vi.mock("../../api/runs", () => ({ cancelQueuedRun: vi.fn(async () => undefined) }));

installLocalStorageMock();

const machines: MachineStatus[] = [
  {
    machine_id: "local",
    active_run: {
      run_id: "live-1",
      branch: "fix/x",
      arch: "cuda-daint",
      status: "running",
      phase: "build",
      started_at: new Date().toISOString(),
      machine_id: "local",
      triggered_by: "bob",
    },
    queue: [
      { queue_id: "q-me", run_id: "q1", branch: "master", arch: "cpu-serial", queued_at: "2026-10-21T09:00:00Z", triggered_by: "alice" },
      { queue_id: "q-bob", run_id: "q2", branch: "master", arch: "cpu-serial", queued_at: "2026-10-21T09:01:00Z", triggered_by: "bob" },
    ],
  },
];

function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="location">{`${loc.pathname}${loc.search}|${JSON.stringify(loc.state)}`}</div>;
}

function renderTable(ms: MachineStatus[] = machines) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<RecentRunsTable machines={ms} lastDurations={new Map()} />} />
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

// The desktop table; the mobile list renders the same rows a second time.
async function table() {
  return within(await screen.findByRole("table"));
}

describe("RecentRunsTable", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.mocked(getCurrentUser).mockResolvedValue({ username: "alice" });
    vi.mocked(getAllRuns).mockResolvedValue({
      runs: [makeRun({ branch: "v1-fix/decay", arch: "cuda-daint", run_id: "done-1" })],
      total: 1,
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("lists live rows before finished ones with the right link targets", async () => {
    renderTable();
    await (await table()).findByText("v1-fix/decay");
    const rows = (await table()).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getAllByText(/running|queued|passed/)[0].textContent)).toEqual([
      "running",
      "queued",
      "queued",
      "passed",
    ]);
    expect(within(rows[0]).getByRole("link", { name: /fix\/x/ })).toHaveAttribute("href", "/live/live-1");
    expect(within(rows[3]).getByRole("link", { name: /v1-fix\/decay/ })).toHaveAttribute(
      "href",
      "/results/v1-fix%2Fdecay/cuda-daint/done-1"
    );
    // Queued rows have no navigation target.
    expect(within(rows[1]).queryByRole("link", { name: /master/ })).toBeNull();
  });

  it("passes branch and arch as router state to the live page", async () => {
    renderTable();
    await userEvent.click(await (await table()).findByRole("link", { name: /fix\/x/ }));
    expect(screen.getByTestId("location")).toHaveTextContent(
      '/live/live-1|{"branch":"fix/x","arch":"cuda-daint"}'
    );
  });

  it("offers cancel only on the viewer's own queued runs", async () => {
    renderTable();
    await (await table()).findByText("v1-fix/decay");
    const cancels = (await table()).getAllByRole("button", { name: /from queue/ });
    expect(cancels).toHaveLength(1);
    await userEvent.click(cancels[0]);
    await waitFor(() => expect(cancelQueuedRun).toHaveBeenCalled());
    expect(vi.mocked(cancelQueuedRun).mock.calls[0][0]).toBe("q-me");
    expect(screen.queryByTestId("location")).toBeNull();
  });

  it("Mine filters live rows and finished runs by the signed-in user", async () => {
    renderTable();
    await (await table()).findByText("v1-fix/decay");
    expect(getAllRuns).toHaveBeenLastCalledWith(6, 0, "active", null);

    await userEvent.click(screen.getByRole("button", { name: "Mine" }));
    await waitFor(() => expect(getAllRuns).toHaveBeenLastCalledWith(6, 0, "active", "alice"));
    expect((await table()).queryByText("fix/x")).toBeNull(); // bob's running run
    expect((await table()).getAllByText("queued")).toHaveLength(1);
    expect(screen.getByRole("link", { name: /View all in Activity/ })).toHaveAttribute(
      "href",
      "/activity?user=alice"
    );
    expect(window.localStorage.getItem("opalx-recent-scope")).toBe("mine");
  });
});
