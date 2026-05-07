import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CatalogPage } from "./CatalogPage";
import { getCatalogTests } from "../api/catalog";

vi.mock("../api/catalog", () => ({
  getCatalogTests: vi.fn(),
}));

vi.mock("../api/runs", () => ({
  getRegtestsBranches: vi.fn(async () => ["master"]),
  getOpalxBranches: vi.fn(async () => ["master"]),
  getArchConfigs: vi.fn(async () => ["cpu-serial"]),
}));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CatalogPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("CatalogPage", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("filters catalog rows by search text", async () => {
    vi.mocked(getCatalogTests).mockResolvedValue({
      branch: "master",
      commit: "abcdef123456",
      commit_url: "https://github.com/OPALX-project/regression-tests-x/commit/abcdef123456",
      tests: [
        {
          name: "Dist-flattop",
          enabled: true,
          path: "RegressionTests/Dist-flattop",
          description: "flattop emission",
          metrics: [{ metric: "rms_s", mode: "last", eps: 1e-5 }],
          has_input: true,
          has_local: true,
          reference_stat_count: 1,
          multi_container_refs: [],
          warnings: [],
          last_status: "failed",
          last_run_id: "run-failed",
          flaky: true,
        },
        {
          name: "RFCavity",
          enabled: true,
          path: "RegressionTests/RFCavity",
          description: "cavity",
          metrics: [{ metric: "energy", mode: "last", eps: 1e-5 }],
          has_input: true,
          has_local: true,
          reference_stat_count: 1,
          multi_container_refs: [],
          warnings: [],
          last_status: "passed",
          last_run_id: "run-passed",
          flaky: false,
        },
      ],
    });

    renderPage();
    expect(await screen.findByText("Dist-flattop")).toBeInTheDocument();
    expect(screen.getByText("RFCavity")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: /Enabled filter/i })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "abcdef1234" })).toHaveAttribute(
      "href",
      "https://github.com/OPALX-project/regression-tests-x/commit/abcdef123456"
    );
    expect(screen.getByRole("link", { name: "Dist-flattop" })).toHaveAttribute(
      "href",
      "/results/master/cpu-serial/run-failed"
    );

    await userEvent.type(screen.getByPlaceholderText("Search tests or metrics"), "rms_s");

    await waitFor(() => {
      expect(screen.getByText("Dist-flattop")).toBeInTheDocument();
      expect(screen.queryByText("RFCavity")).not.toBeInTheDocument();
    });
  });
});
