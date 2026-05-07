import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RunDetailPage } from "./RunDetailPage";
import { getRunDetail } from "../../api/results";
import { getRunIntegrity } from "../../api/integrity";

vi.mock("../../api/results", async () => {
  const actual = await vi.importActual<typeof import("../../api/results")>(
    "../../api/results"
  );
  return {
    ...actual,
    getRunDetail: vi.fn(),
    archiveRun: vi.fn(),
    restoreRun: vi.fn(),
    deleteRun: vi.fn(),
    setRunVisibility: vi.fn(),
  };
});

vi.mock("../../api/integrity", () => ({
  getRunIntegrity: vi.fn(),
}));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/results/master/cpu-serial/source"]}>
        <Routes>
          <Route
            path="/results/:branch/:arch/:runId"
            element={<RunDetailPage />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("RunDetailPage", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("links Run again with source run parameters", async () => {
    vi.mocked(getRunDetail).mockResolvedValue({
      meta: {
        branch: "master",
        arch: "cpu-serial",
        run_id: "source",
        started_at: "2026-04-01T00:00:00+00:00",
        finished_at: "2026-04-01T00:01:00+00:00",
        status: "passed",
        opalx_commit: "abc",
        tests_repo_commit: "def",
        regtest_branch: "master",
        connection_name: "local",
        triggered_by: "demo-user",
        unit_tests_total: 1,
        unit_tests_failed: 0,
        regression_total: 1,
        regression_passed: 1,
        regression_failed: 0,
        regression_broken: 0,
        archived: false,
        public: false,
        run_options: {
          skip_unit: true,
          skip_regression: false,
          clean_build: true,
          custom_cmake_args: ["-DIPPL_GIT_TAG=master"],
        },
        rerun_of: null,
      },
      unit: { tests: [] },
      regression: { simulations: [] },
      archived_on_cold_storage: false,
    });
    vi.mocked(getRunIntegrity).mockResolvedValue({
      status: "ok",
      issues: [],
      manifest: null,
    });

    renderPage();
    const link = await screen.findByRole("link", { name: /Run again/i });
    const href = link.getAttribute("href") ?? "";

    expect(href).toContain("/trigger?");
    expect(href).toContain("branch=master");
    expect(href).toContain("arch=cpu-serial");
    expect(href).toContain("skip_unit=true");
    expect(href).toContain("clean_build=true");
    expect(href).toContain("rerun_id=source");
    expect(href).not.toContain("custom_cmake_args");
    expect(await screen.findByText("Custom CMake Args")).toBeInTheDocument();
    expect(screen.getByText("-DIPPL_GIT_TAG=master")).toBeInTheDocument();
  });
});
