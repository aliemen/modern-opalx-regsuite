import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { parseCustomCmakeArgs, TriggerPage } from "./TriggerPage";
import {
  getOpalxBranches,
  getRegtestsBranches,
  getRunConfigs,
  triggerRun,
} from "../api/runs";

vi.mock("../api/runs", async () => {
  const actual = await vi.importActual<typeof import("../api/runs")>("../api/runs");
  return {
    ...actual,
    getOpalxBranches: vi.fn(async () => ["master"]),
    getRegtestsBranches: vi.fn(async () => ["master"]),
    getArchConfigs: vi.fn(async () => ["cpu-serial"]),
    getRunConfigs: vi.fn(async () => [
      {
        arch: "cpu-serial",
        default_mpi_ranks: 1,
        max_mpi_ranks: 4,
        default_opalx_info_level: 2,
        slurm_enabled: false,
        slurm_overrides_supported: false,
        slurm_defaults: null,
      },
    ]),
    triggerRun: vi.fn(),
  };
});

vi.mock("../api/connections", async () => {
  const actual = await vi.importActual<typeof import("../api/connections")>(
    "../api/connections"
  );
  return {
    ...actual,
    listConnections: vi.fn(async () => []),
  };
});

function renderPage(url: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <TriggerPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("TriggerPage rerun prefill", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("blocks a prefilled missing connection until the user chooses another", async () => {
    renderPage(
      "/trigger?branch=master&regtests_branch=master&arch=cpu-serial&connection_name=missing-remote&clean_build=true"
    );

    expect(
      await screen.findByText(/This saved connection is not available/)
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start Run/i })).toBeDisabled();
    expect(screen.getByLabelText("Clean build")).toBeChecked();
  });

  it("falls back removed prefilled branches to master", async () => {
    vi.mocked(getOpalxBranches).mockResolvedValue(["feature/current", "master"]);
    vi.mocked(getRegtestsBranches).mockResolvedValue(["master", "rt/current"]);

    renderPage(
      "/trigger?branch=deleted-opalx&regtests_branch=deleted-regtests&arch=cpu-serial"
    );

    await waitFor(() => {
      const [opalxSelect, regtestsSelect] = screen.getAllByRole("combobox");
      expect(opalxSelect).toHaveValue("master");
      expect(regtestsSelect).toHaveValue("master");
    });
  });

  it("parses custom cmake args from non-empty non-comment lines", () => {
    expect(parseCustomCmakeArgs("\n# note\n-DIPPL_GIT_TAG=master\n  -DFOO=bar  ")).toEqual([
      "-DIPPL_GIT_TAG=master",
      "-DFOO=bar",
    ]);
  });

  it("sends advanced cmake args and forces clean build", async () => {
    vi.mocked(triggerRun).mockResolvedValue({
      run_id: "20260507-120000",
      queued: true,
      queue_id: "queue-1",
      position: 1,
    });
    const user = userEvent.setup();

    renderPage("/trigger?branch=master&regtests_branch=master&arch=cpu-serial");

    await user.click(screen.getByRole("button", { name: "Advanced" }));
    await user.type(
      screen.getByLabelText("Custom CMake args"),
      "# try current IPPL\n-DIPPL_GIT_TAG=master\n\n-DKokkos_VERSION=git.4.7.01"
    );
    await user.click(screen.getByRole("button", { name: /Start Run/i }));

    await waitFor(() => {
      expect(triggerRun).toHaveBeenCalledWith(
        expect.objectContaining({
          clean_build: true,
          custom_cmake_args: [
            "-DIPPL_GIT_TAG=master",
            "-DKokkos_VERSION=git.4.7.01",
          ],
        })
      );
    });
  });

  it("sends MPI ranks and OPALX info level overrides", async () => {
    vi.mocked(triggerRun).mockResolvedValue({
      run_id: "20260507-120000",
      queued: true,
      queue_id: "queue-1",
      position: 1,
    });
    const user = userEvent.setup();

    renderPage(
      "/trigger?branch=master&regtests_branch=master&arch=cpu-serial&mpi_ranks=2&opalx_info_level=4"
    );

    await screen.findByDisplayValue("2");
    await user.click(screen.getByRole("button", { name: /Start Run/i }));

    await waitFor(() => {
      expect(triggerRun).toHaveBeenCalledWith(
        expect.objectContaining({
          mpi_ranks: 2,
          opalx_info_level: 4,
        })
      );
    });
  });

  it("sends manual Slurm resource overrides from the advanced tab", async () => {
    vi.mocked(getRunConfigs).mockResolvedValue([
      {
        arch: "cuda-daint",
        default_mpi_ranks: 1,
        max_mpi_ranks: 4,
        default_opalx_info_level: 2,
        slurm_enabled: true,
        slurm_overrides_supported: true,
        slurm_defaults: {
          partition: "debug",
          nodes: null,
          tasks_per_node: 1,
          cpus_per_task: 16,
          gpus: null,
          gpus_per_task: 1,
        },
      },
    ]);
    vi.mocked(triggerRun).mockResolvedValue({
      run_id: "20260507-120000",
      queued: true,
      queue_id: "queue-1",
      position: 1,
    });
    const user = userEvent.setup();

    renderPage(
      "/trigger?branch=master&regtests_branch=master&arch=cuda-daint&mpi_ranks=2"
    );

    await user.click(await screen.findByRole("button", { name: "Advanced" }));
    await user.clear(screen.getByLabelText("Nodes"));
    await user.type(screen.getByLabelText("Nodes"), "1");
    await user.clear(screen.getByLabelText("Tasks per node"));
    await user.type(screen.getByLabelText("Tasks per node"), "2");
    await user.clear(screen.getByLabelText("GPUs"));
    await user.type(screen.getByLabelText("GPUs"), "1");
    await user.clear(screen.getByLabelText("GPUs per task"));
    await user.click(screen.getByRole("button", { name: /Start Run/i }));

    await waitFor(() => {
      expect(triggerRun).toHaveBeenCalledWith(
        expect.objectContaining({
          arch: "cuda-daint",
          mpi_ranks: 2,
          slurm_resources: {
            partition: "debug",
            nodes: 1,
            tasks_per_node: 2,
            cpus_per_task: 16,
            gpus: 1,
            gpus_per_task: null,
          },
        })
      );
    });
  });

  it("resets Slurm resource edits back to defaults", async () => {
    vi.mocked(getRunConfigs).mockResolvedValue([
      {
        arch: "cuda-daint",
        default_mpi_ranks: 2,
        max_mpi_ranks: 4,
        default_opalx_info_level: 2,
        slurm_enabled: true,
        slurm_overrides_supported: true,
        slurm_defaults: {
          partition: "debug",
          nodes: 1,
          tasks_per_node: 2,
          cpus_per_task: 16,
          gpus: 1,
          gpus_per_task: null,
        },
      },
    ]);
    vi.mocked(triggerRun).mockResolvedValue({
      run_id: "20260507-120000",
      queued: true,
      queue_id: "queue-1",
      position: 1,
    });
    const user = userEvent.setup();

    renderPage("/trigger?branch=master&regtests_branch=master&arch=cuda-daint");

    await user.click(await screen.findByRole("button", { name: "Advanced" }));
    await user.clear(screen.getByLabelText("Nodes"));
    await user.type(screen.getByLabelText("Nodes"), "2");
    await user.click(screen.getByRole("button", { name: /Reset to defaults/i }));
    expect(screen.getByLabelText("Nodes")).toHaveValue(1);

    await user.click(screen.getByRole("button", { name: /Start Run/i }));

    await waitFor(() => {
      expect(triggerRun).toHaveBeenCalledWith(
        expect.not.objectContaining({ slurm_resources: expect.anything() })
      );
    });
  });
});
