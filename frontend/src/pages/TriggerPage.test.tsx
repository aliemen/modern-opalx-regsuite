import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { parseCustomCmakeArgs, TriggerPage } from "./TriggerPage";
import {
  getOpalxBranches,
  getRegtestsBranches,
  triggerRun,
} from "../api/runs";
import {
  getExecutionSettings,
  getRunProfilesForTrigger,
  type ExecutionSettings,
  type RunProfileSummary,
} from "../api/executionProfiles";

function profileSummary(
  overrides: Partial<RunProfileSummary> = {},
): RunProfileSummary {
  const arch = overrides.arch ?? "cpu-serial";
  const id = overrides.id ?? `local-${arch}`;
  return {
    id,
    name: overrides.name ?? `Local ${arch}`,
    description: overrides.description ?? null,
    arch,
    build_preset_id: overrides.build_preset_id ?? arch,
    build_preset_name: overrides.build_preset_name ?? arch,
    machine_preset_id: overrides.machine_preset_id ?? "local",
    machine_preset_name: overrides.machine_preset_name ?? "Local",
    machine_kind: overrides.machine_kind ?? "local",
    env_preset_id: overrides.env_preset_id ?? null,
    env_preset_name: overrides.env_preset_name ?? null,
    env_style: overrides.env_style ?? "none",
    slurm_preset_id: overrides.slurm_preset_id ?? null,
    slurm_preset_name: overrides.slurm_preset_name ?? null,
    default_mpi_ranks: overrides.default_mpi_ranks ?? 1,
    max_mpi_ranks: overrides.max_mpi_ranks ?? 4,
    default_opalx_info_level: overrides.default_opalx_info_level ?? 2,
    slurm_enabled: overrides.slurm_enabled ?? false,
    slurm_overrides_supported: overrides.slurm_overrides_supported ?? false,
    slurm_defaults: overrides.slurm_defaults ?? null,
    interactive_gateway: overrides.interactive_gateway ?? false,
    generated: overrides.generated ?? false,
    valid: overrides.valid ?? true,
    validation_errors: overrides.validation_errors ?? [],
  };
}

function executionSettingsFixture(
  cmakeQuickSelections: string[] = [],
): ExecutionSettings {
  return {
    version: 1,
    cmake_quick_selections: cmakeQuickSelections,
    build_presets: [],
    machine_presets: [],
    env_presets: [],
    slurm_presets: [],
    created_at: null,
    modified_at: null,
  };
}

vi.mock("../api/runs", async () => {
  const actual = await vi.importActual<typeof import("../api/runs")>("../api/runs");
  return {
    ...actual,
    getOpalxBranches: vi.fn(async () => ["master"]),
    getRegtestsBranches: vi.fn(async () => ["master"]),
    getArchConfigs: vi.fn(async () => ["cpu-serial"]),
    triggerRun: vi.fn(),
  };
});

vi.mock("../api/executionProfiles", async () => {
  const actual = await vi.importActual<typeof import("../api/executionProfiles")>(
    "../api/executionProfiles"
  );
  return {
    ...actual,
    getRunProfilesForTrigger: vi.fn(async () => [profileSummary()]),
    getExecutionSettings: vi.fn(async () => executionSettingsFixture()),
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
    vi.mocked(getExecutionSettings).mockResolvedValue(executionSettingsFixture());
  });

  it("falls back to an available profile for a legacy missing connection query", async () => {
    renderPage(
      "/trigger?branch=master&regtests_branch=master&arch=cpu-serial&connection_name=missing-remote&clean_build=true"
    );

    expect(await screen.findByText("cpu-serial / Local")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start Run/i })).toBeEnabled();
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

  it("quick-adds CMake keys while keeping basic settings and overrides visible", async () => {
    vi.mocked(getExecutionSettings).mockResolvedValue(
      executionSettingsFixture(["IPPL_GIT_TAG"]),
    );
    vi.mocked(triggerRun).mockResolvedValue({
      run_id: "20260507-120000",
      queued: true,
      queue_id: "queue-1",
      position: 1,
    });
    const user = userEvent.setup();

    renderPage("/trigger?branch=master&regtests_branch=master&arch=cpu-serial");

    const advancedToggle = await screen.findByLabelText(/Show advanced options/);
    expect(screen.getByLabelText("Clean build")).toBeVisible();
    await user.click(advancedToggle);

    const addButton = await screen.findByRole("button", {
      name: "Add CMake argument IPPL_GIT_TAG",
    });
    await user.click(addButton);
    const textarea = screen.getByLabelText("Custom CMake args");
    expect(textarea).toHaveValue("-DIPPL_GIT_TAG=");
    await waitFor(() => expect(textarea).toHaveFocus());
    await user.type(textarea, "master");
    expect(
      screen.getByRole("button", { name: "IPPL_GIT_TAG already added" }),
    ).toBeDisabled();
    expect(screen.getByLabelText("Clean build")).toBeChecked();
    expect(screen.getByLabelText("Clean build")).toBeDisabled();

    await user.click(advancedToggle);
    expect(screen.queryByLabelText("Custom CMake args")).not.toBeInTheDocument();
    expect(screen.getByText("1 override active")).toBeVisible();
    expect(screen.getByText("Required by custom CMake args.")).toBeVisible();

    await user.click(advancedToggle);
    const reopenedTextarea = screen.getByLabelText("Custom CMake args");
    expect(reopenedTextarea).toHaveValue("-DIPPL_GIT_TAG=master");
    await user.clear(reopenedTextarea);
    await user.type(reopenedTextarea, "-DIPPL_GIT_TAG:STRING=feature");
    expect(
      screen.getByRole("button", { name: "IPPL_GIT_TAG already added" }),
    ).toBeDisabled();

    await user.click(screen.getByRole("button", { name: /Start Run/i }));
    await waitFor(() => {
      expect(triggerRun).toHaveBeenCalledWith(
        expect.objectContaining({
          clean_build: true,
          custom_cmake_args: ["-DIPPL_GIT_TAG:STRING=feature"],
        }),
      );
    });
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

    await user.click(screen.getByLabelText(/Show advanced options/));
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

  it("keeps manual run dispatch available when quick selections cannot load", async () => {
    vi.mocked(getExecutionSettings).mockRejectedValue(
      new Error("settings unavailable"),
    );
    vi.mocked(triggerRun).mockResolvedValue({
      run_id: "20260507-120000",
      queued: true,
      queue_id: "queue-1",
      position: 1,
    });
    const user = userEvent.setup();

    renderPage("/trigger?branch=master&regtests_branch=master&arch=cpu-serial");

    await user.click(await screen.findByLabelText(/Show advanced options/));
    expect(screen.queryByText("Quick add")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Custom CMake args")).toBeEnabled();
    await user.click(screen.getByRole("button", { name: /Start Run/i }));

    await waitFor(() => expect(triggerRun).toHaveBeenCalledTimes(1));
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

    await screen.findByDisplayValue("4");
    expect(screen.queryByLabelText("MPI ranks")).not.toBeInTheDocument();
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

  it("keeps manually edited MPI ranks for local runs", async () => {
    vi.mocked(triggerRun).mockResolvedValue({
      run_id: "20260507-120000",
      queued: true,
      queue_id: "queue-1",
      position: 1,
    });
    const user = userEvent.setup();

    renderPage("/trigger?branch=master&regtests_branch=master&arch=cpu-serial");

    await user.click(await screen.findByLabelText(/Show advanced options/));
    const ranksInput = screen.getByLabelText("MPI ranks");
    fireEvent.change(ranksInput, { target: { value: "3" } });
    expect(ranksInput).toHaveValue(3);

    await user.click(screen.getByRole("button", { name: /Start Run/i }));

    await waitFor(() => {
      expect(triggerRun).toHaveBeenCalledWith(
        expect.objectContaining({
          arch: "cpu-serial",
          profile_id: "local-cpu-serial",
          mpi_ranks: 3,
        })
      );
    });
  });

  it("sends manual Slurm resource overrides from the advanced tab", async () => {
    vi.mocked(getRunProfilesForTrigger).mockResolvedValue([
      profileSummary({
        id: "daint-cuda-daint",
        name: "Daint CUDA",
        arch: "cuda-daint",
        build_preset_id: "cuda-daint",
        build_preset_name: "cuda-daint",
        machine_preset_id: "daint",
        machine_preset_name: "Daint",
        machine_kind: "ssh",
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
      }),
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

    await user.click(await screen.findByLabelText(/Show advanced options/));
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
          profile_id: "daint-cuda-daint",
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
    vi.mocked(getRunProfilesForTrigger).mockResolvedValue([
      profileSummary({
        id: "daint-cuda-daint",
        name: "Daint CUDA",
        arch: "cuda-daint",
        build_preset_id: "cuda-daint",
        build_preset_name: "cuda-daint",
        machine_preset_id: "daint",
        machine_preset_name: "Daint",
        machine_kind: "ssh",
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
      }),
    ]);
    vi.mocked(triggerRun).mockResolvedValue({
      run_id: "20260507-120000",
      queued: true,
      queue_id: "queue-1",
      position: 1,
    });
    const user = userEvent.setup();

    renderPage("/trigger?branch=master&regtests_branch=master&arch=cuda-daint");

    await user.click(await screen.findByLabelText(/Show advanced options/));
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
