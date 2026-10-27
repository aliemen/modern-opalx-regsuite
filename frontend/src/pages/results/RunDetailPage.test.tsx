import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RunDetailPage } from "./RunDetailPage";
import { getRunDetail, getRunSeries, type RunDetail } from "../../api/results";
import { getRunIntegrity } from "../../api/integrity";

vi.mock("../../api/results", async () => {
  const actual = await vi.importActual<typeof import("../../api/results")>(
    "../../api/results"
  );
  return {
    ...actual,
    getRunDetail: vi.fn(),
    getRunSeries: vi.fn(),
    archiveRun: vi.fn(),
    restoreRun: vi.fn(),
    deleteRun: vi.fn(),
    setRunVisibility: vi.fn(),
  };
});

// uPlot needs a canvas, which jsdom lacks; the chart itself is not under test here.
vi.mock("../../components/SeriesPlot", () => ({
  SeriesPlot: ({ metric, curves }: { metric: string; curves: { x: number[] } }) => (
    <div data-testid="series-plot">{`${metric}:${curves.x.length}`}</div>
  ),
}));

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

function detailFixture(): RunDetail {
  return {
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
        mpi_ranks: 2,
        opalx_info_level: 4,
        slurm_resources: {
          partition: "debug",
          nodes: 1,
          tasks_per_node: 2,
          cpus_per_task: 16,
          gpus: 1,
          gpus_per_task: null,
        },
      },
      execution_snapshot: {
        build: {
          id: "cpu-serial",
          name: "CPU serial",
          cmake_args: ["-DBUILD_TYPE=Release"],
          build_jobs: 8,
          mpi_ranks: 1,
          max_mpi_ranks: 4,
          opalx_info_level: 2,
        },
        machine: {
          id: "local",
          name: "Local",
          kind: "local",
          host: null,
          port: 22,
          gateway_host: null,
          gateway_port: null,
          gateway_auth_method: null,
          queue_key: "local",
        },
        environment: null,
        slurm: null,
      },
      rerun_of: null,
    },
    unit: { tests: [] },
    regression: { simulations: [] },
    archived_on_cold_storage: false,
  };
}

describe("RunDetailPage", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("links Run again with source run parameters", async () => {
    vi.mocked(getRunDetail).mockResolvedValue(detailFixture());
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
    expect(href).toContain("build_preset_id=cpu-serial");
    expect(href).toContain("machine_preset_id=local");
    expect(href).toContain("env_preset_id=");
    expect(href).toContain("slurm_preset_id=");
    expect(href).toContain("skip_unit=true");
    expect(href).toContain("clean_build=true");
    expect(href).toContain("mpi_ranks=2");
    expect(href).toContain("opalx_info_level=4");
    expect(href).toContain("slurm_nodes=1");
    expect(href).toContain("slurm_tasks_per_node=2");
    expect(href).toContain("slurm_gpus=1");
    expect(href).toContain("slurm_gpus_per_task=");
    expect(href).toContain("rerun_id=source");
    expect(href).not.toContain("custom_cmake_args");
    expect(await screen.findByText("Custom CMake Args")).toBeInTheDocument();
    expect(screen.getByText("-DIPPL_GIT_TAG=master")).toBeInTheDocument();
    expect(screen.getByText("master · CPU serial")).toBeInTheDocument();
  });

  it("shows skip config details and prefills it on Run again", async () => {
    const detail = detailFixture();
    detail.meta.run_options.skip_config = {
      id: "slow",
      name: "Slow on CPU",
      unit_tests: ["TestOrbitThreader"],
      regression_tests: ["DBA-COF-Gauss"],
    };
    detail.meta.unit_tests_skipped = 1;
    detail.meta.regression_skipped = 1;
    detail.unit = {
      tests: [
        {
          name: "TestOrbitThreader",
          status: "skipped",
          duration_seconds: null,
          output_snippet: null,
        },
        { name: "TestFast", status: "passed", duration_seconds: 0.1, output_snippet: null },
      ],
    };
    detail.regression = {
      simulations: [
        {
          name: "DBA-COF-Gauss",
          description: null,
          state: "skipped",
          log_file: null,
          containers: [],
          duration_seconds: null,
          beamline_plot: null,
          beamline_3d_data: null,
          exit_code: null,
          crash_signal: null,
          crash_summary: null,
        },
      ],
    };
    vi.mocked(getRunDetail).mockResolvedValue(detail);
    vi.mocked(getRunIntegrity).mockResolvedValue({
      status: "ok",
      issues: [],
      manifest: null,
    });

    renderPage();
    const link = await screen.findByRole("link", { name: /Run again/i });

    expect(link.getAttribute("href") ?? "").toContain("skip_config_id=slow");
    expect(screen.getByText("Test Skip Config")).toBeInTheDocument();
    expect(screen.getByText("Slow on CPU")).toBeInTheDocument();
    expect(screen.getByText("Skipped (1)")).toBeInTheDocument();
    expect(screen.getAllByText(/· 1 skipped/)).toHaveLength(2); // unit + regression headers
  });

  it("draws metrics from series.json.gz and falls back to the legacy SVG", async () => {
    const detail = detailFixture();
    detail.regression = {
      simulations: [
        {
          name: "Drift",
          description: null,
          state: "passed",
          log_file: null,
          containers: [
            {
              id: null,
              state: "passed",
              revision: null,
              metrics: [
                { metric: "rms_x", mode: "last", eps: 1e-6, delta: 0, state: "passed",
                  reference_value: 1, current_value: 1, plot: "plots/Drift_rms_x.svg", series: true },
                { metric: "energy", mode: "avg", eps: 1e-3, delta: 0, state: "passed",
                  reference_value: 1, current_value: 1, plot: "plots/Drift_energy.svg" },
              ],
            },
          ],
          duration_seconds: 1,
          beamline_plot: null,
          beamline_3d_data: null,
          exit_code: 0,
          crash_signal: null,
          crash_summary: null,
        },
      ],
    };
    vi.mocked(getRunDetail).mockResolvedValue(detail);
    vi.mocked(getRunIntegrity).mockResolvedValue({ status: "ok", issues: [], manifest: null });
    vi.mocked(getRunSeries).mockResolvedValue({
      schema: 2,
      source: "svg",
      max_points: 100,
      sims: { Drift: { _: { m: { rms_x: { s: [0, 1, 2], cur: [1, 2, 3], rs: [0, 1, 2], ref: [1, 2, 3] } } } } },
    });

    renderPage();
    (await screen.findByText("Drift")).click();

    expect(await screen.findByTestId("series-plot")).toHaveTextContent("rms_x:3");
    expect(getRunSeries).toHaveBeenCalledWith("master", "cpu-serial", "source");
    const img = screen.getByAltText("Drift energy");
    expect(img.getAttribute("src")).toBe("/data/runs/master/cpu-serial/source/plots/Drift_energy.svg");
    expect(screen.queryByAltText("Drift rms_x")).not.toBeInTheDocument();
  });
});
