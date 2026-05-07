import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FlakinessCard } from "./FlakinessCard";
import { getFlakiness, getLatestMaster } from "../../api/stats";

vi.mock("../../api/stats", () => ({
  getLatestMaster: vi.fn(),
  getFlakiness: vi.fn(),
}));

function renderCard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <FlakinessCard />
    </QueryClientProvider>
  );
}

describe("FlakinessCard", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders flaky simulation summaries", async () => {
    vi.mocked(getLatestMaster).mockResolvedValue({
      cells: [
        {
          arch: "cpu-serial",
          run_id: "demo",
          status: "passed",
          started_at: "2026-04-01T00:00:00+00:00",
          finished_at: "2026-04-01T00:01:00+00:00",
          duration_seconds: 60,
          unit_total: 1,
          unit_failed: 0,
          regression_total: 1,
          regression_passed: 1,
          regression_failed: 0,
          regression_broken: 0,
        },
        {
          arch: "gpu",
          run_id: "demo-gpu",
          status: "passed",
          started_at: "2026-04-01T00:00:00+00:00",
          finished_at: "2026-04-01T00:01:00+00:00",
          duration_seconds: 60,
          unit_total: 1,
          unit_failed: 0,
          regression_total: 5,
          regression_passed: 5,
          regression_failed: 0,
          regression_broken: 0,
        },
      ],
    });
    vi.mocked(getFlakiness).mockResolvedValue({
      branch: "master",
      arch: "gpu",
      regtests_branch: "master",
      limit: 20,
      min_observations: 3,
      runs_considered: 3,
      simulations: [
        {
          name: "SometimesBad",
          observations: 3,
          passed: 2,
          failed: 1,
          broken: 0,
          crashed: 0,
          latest_status: "passed",
          latest_run_id: "demo",
        },
      ],
    });

    renderCard();

    expect(await screen.findByText("SometimesBad")).toBeInTheDocument();
    expect(screen.getByText("2 pass / 1 bad")).toBeInTheDocument();
    await waitFor(() => {
      expect(getFlakiness).toHaveBeenCalledWith("master", "gpu", "master", 20);
    });
  });
});
