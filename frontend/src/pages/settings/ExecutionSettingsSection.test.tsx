import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  saveExecutionSettings,
  type ExecutionSettings,
} from "../../api/executionProfiles";
import { ExecutionSection } from "./ExecutionSection";
import { ExecutionSettingsSection } from "./ExecutionSettingsSection";

const apiMocks = vi.hoisted(() => ({
  getExecutionSettings: vi.fn(),
  saveExecutionSettings: vi.fn(),
  resetExecutionSettingsFromConfig: vi.fn(),
}));

vi.mock("../../api/executionProfiles", async () => {
  const actual = await vi.importActual<typeof import("../../api/executionProfiles")>(
    "../../api/executionProfiles"
  );
  return {
    ...actual,
    getExecutionSettings: apiMocks.getExecutionSettings,
    saveExecutionSettings: apiMocks.saveExecutionSettings,
    resetExecutionSettingsFromConfig: apiMocks.resetExecutionSettingsFromConfig,
  };
});

vi.mock("./RunProfilesSection", () => ({
  RunProfilesSection: () => <div>Run profile mock</div>,
}));

function settingsFixture(): ExecutionSettings {
  return {
    version: 1,
    build_presets: [
      {
        id: "cpu-serial",
        name: "CPU Serial",
        description: null,
        cmake_args: ["-DBUILD_TYPE=Release", "-DPLATFORMS=SERIAL"],
        build_jobs: 8,
        mpi_ranks: 1,
        max_mpi_ranks: 8,
        opalx_info_level: null,
        generated: true,
      },
    ],
    machine_presets: [
      {
        id: "local",
        name: "Local",
        description: "Run locally",
        kind: "local",
        host: null,
        port: 22,
        gateway: null,
        queue_key: "local",
        generated: true,
      },
    ],
    env_presets: [
      {
        id: "modules-env",
        name: "Modules",
        description: null,
        env: {
          style: "modules",
          lmod_init: "/usr/share/lmod/lmod/init/bash",
          module_use_paths: ["/opt/modulefiles"],
          module_loads: ["module load gcc/15"],
          prologue: null,
        },
        generated: true,
      },
    ],
    slurm_presets: [
      {
        id: "cuda-slurm",
        name: "CUDA Slurm",
        description: null,
        slurm: {
          partition: "debug",
          nodes: null,
          tasks_per_node: 1,
          cpus_per_task: 16,
          gpus: null,
          gpus_per_task: 1,
          account: "c41",
          cluster: null,
          time: "00:30:00",
          extra_args: [],
        },
        slurm_args: [],
        command_timeout: 0,
        salloc_timeout: 0,
        generated: true,
      },
    ],
    created_at: "2026-05-31T10:00:00Z",
    modified_at: "2026-05-31T10:00:00Z",
  };
}

function renderWithClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

function renderPublicSettings() {
  apiMocks.getExecutionSettings.mockResolvedValue(settingsFixture());
  apiMocks.saveExecutionSettings.mockImplementation(async (body: ExecutionSettings) => body);
  return renderWithClient(<ExecutionSettingsSection />);
}

function lastSavedSettings(): ExecutionSettings {
  const call = vi.mocked(saveExecutionSettings).mock.calls.at(-1);
  if (!call) throw new Error("saveExecutionSettings was not called");
  return call[0] as ExecutionSettings;
}

describe("Execution public settings UI", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders public settings as a sub-tab with the three primary cards", async () => {
    apiMocks.getExecutionSettings.mockResolvedValue(settingsFixture());
    const user = userEvent.setup();
    renderWithClient(<ExecutionSection />);

    expect(screen.getByText("Run profile mock")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Public Settings/i }));

    expect(
      screen.getByText(/DANGER: If you don't know what you're doing/)
    ).toBeInTheDocument();
    expect(screen.queryByText("Build Presets")).not.toBeInTheDocument();
    const continueButton = screen.getByRole("button", { name: "Continue" });
    expect(continueButton).toBeDisabled();
    await user.click(screen.getByLabelText("Yes I know what I'm doing"));
    expect(continueButton).toBeEnabled();
    await user.click(continueButton);
    expect(await screen.findByText("Build Presets")).toBeInTheDocument();
    expect(screen.getByText("Machine Presets")).toBeInTheDocument();
    expect(screen.getByText("Environment Presets")).toBeInTheDocument();
  });

  it("adds a build preset and converts CMake args from one line per argument", async () => {
    const user = userEvent.setup();
    renderPublicSettings();

    await user.click(await screen.findByRole("button", { name: /Add build/i }));
    await user.type(screen.getByLabelText("ID"), "cuda-test");
    await user.type(screen.getByLabelText("Name"), "CUDA Test");
    await user.clear(screen.getByLabelText("Build jobs"));
    await user.type(screen.getByLabelText("Build jobs"), "16");
    await user.clear(screen.getByLabelText("Default MPI ranks"));
    await user.type(screen.getByLabelText("Default MPI ranks"), "2");
    await user.type(screen.getByLabelText("Max MPI ranks"), "4");
    await user.type(screen.getByLabelText("OPALX info level"), "3");
    await user.type(
      screen.getByLabelText("CMake args"),
      "-DBUILD_TYPE=Debug\n-DPLATFORMS=CUDA"
    );
    await user.click(screen.getByRole("button", { name: /Save build/i }));

    await waitFor(() => expect(saveExecutionSettings).toHaveBeenCalled());
    expect(lastSavedSettings()).toEqual(
      expect.objectContaining({
        build_presets: expect.arrayContaining([
          expect.objectContaining({
            id: "cuda-test",
            name: "CUDA Test",
            cmake_args: ["-DBUILD_TYPE=Debug", "-DPLATFORMS=CUDA"],
            build_jobs: 16,
            mpi_ranks: 2,
            max_mpi_ranks: 4,
            opalx_info_level: 3,
          }),
        ]),
      })
    );
  });

  it("adds an SSH machine with an interactive gateway", async () => {
    const user = userEvent.setup();
    renderPublicSettings();

    await user.click(await screen.findByRole("button", { name: /Add machine/i }));
    await user.type(screen.getByLabelText("ID"), "merlin6");
    await user.type(screen.getByLabelText("Name"), "Merlin 6");
    await user.type(screen.getByLabelText("Host"), "merlin-l-001.psi.ch");
    await user.clear(screen.getByLabelText("Queue key"));
    await user.type(screen.getByLabelText("Queue key"), "merlin-l-001.psi.ch");
    await user.click(screen.getByLabelText("Use SSH gateway"));
    await user.type(screen.getByLabelText("Gateway host"), "hopx.psi.ch");
    await user.selectOptions(screen.getByLabelText("Gateway auth"), "interactive");
    await user.click(screen.getByRole("button", { name: /Save machine/i }));

    await waitFor(() => expect(saveExecutionSettings).toHaveBeenCalled());
    expect(lastSavedSettings()).toEqual(
      expect.objectContaining({
        machine_presets: expect.arrayContaining([
          expect.objectContaining({
            id: "merlin6",
            kind: "ssh",
            host: "merlin-l-001.psi.ch",
            queue_key: "merlin-l-001.psi.ch",
            gateway: {
              host: "hopx.psi.ch",
              port: 22,
              auth_method: "interactive",
            },
          }),
        ]),
      })
    );
  });

  it("saves modules, prologue, and uenv environment preset shapes", async () => {
    const user = userEvent.setup();
    renderPublicSettings();

    await user.click(await screen.findByRole("button", { name: /Add environment/i }));
    await user.type(screen.getByLabelText("ID"), "modules-test");
    await user.type(screen.getByLabelText("Name"), "Modules Test");
    await user.clear(screen.getByLabelText("Module commands"));
    await user.type(
      screen.getByLabelText("Module commands"),
      "module load gcc/15\nmodule swap cuda/12.1 cuda/12.4",
    );
    await user.click(screen.getByRole("button", { name: /Save environment/i }));

    await waitFor(() => expect(saveExecutionSettings).toHaveBeenCalledTimes(1));
    expect(lastSavedSettings()).toEqual(
      expect.objectContaining({
        env_presets: expect.arrayContaining([
          expect.objectContaining({
            id: "modules-test",
            env: expect.objectContaining({
              style: "modules",
              module_loads: [
                "module load gcc/15",
                "module swap cuda/12.1 cuda/12.4",
              ],
            }),
          }),
        ]),
      })
    );

    await user.click(screen.getByRole("button", { name: /Add environment/i }));
    await user.type(screen.getByLabelText("ID"), "prologue-test");
    await user.type(screen.getByLabelText("Name"), "Prologue Test");
    await user.selectOptions(screen.getByLabelText("Style"), "prologue");
    await user.type(screen.getByLabelText("Prologue command"), "source /opt/env.sh");
    await user.click(screen.getByRole("button", { name: /Save environment/i }));

    await waitFor(() => expect(saveExecutionSettings).toHaveBeenCalledTimes(2));
    expect(lastSavedSettings()).toEqual(
      expect.objectContaining({
        env_presets: expect.arrayContaining([
          expect.objectContaining({
            id: "prologue-test",
            env: expect.objectContaining({
              style: "prologue",
              prologue: "source /opt/env.sh",
            }),
          }),
        ]),
      })
    );

    await user.click(screen.getByRole("button", { name: /Add environment/i }));
    await user.type(screen.getByLabelText("ID"), "uenv-test");
    await user.type(screen.getByLabelText("Name"), "uenv Test");
    await user.selectOptions(screen.getByLabelText("Style"), "uenv");
    await user.type(
      screen.getByLabelText("uenv arguments"),
      "--view=default /capstor/uenv.squashfs"
    );
    await user.click(screen.getByRole("button", { name: /Save environment/i }));

    await waitFor(() => expect(saveExecutionSettings).toHaveBeenCalledTimes(3));
    expect(lastSavedSettings()).toEqual(
      expect.objectContaining({
        env_presets: expect.arrayContaining([
          expect.objectContaining({
            id: "uenv-test",
            env: expect.objectContaining({
              style: "uenv",
              prologue: "--view=default /capstor/uenv.squashfs",
            }),
          }),
        ]),
      })
    );
  });

  it("saves typed Slurm presets from the machine card", async () => {
    const user = userEvent.setup();
    renderPublicSettings();

    await user.click(await screen.findByRole("button", { name: /Add Slurm/i }));
    await user.type(screen.getByLabelText("ID"), "debug-slurm");
    await user.type(screen.getByLabelText("Name"), "Debug Slurm");
    await user.type(screen.getByLabelText("Partition"), "debug");
    await user.type(screen.getByLabelText("Account"), "c41");
    await user.type(screen.getByLabelText("Time"), "00:30:00");
    await user.type(screen.getByLabelText("Tasks per node"), "1");
    await user.type(screen.getByLabelText("CPUs per task"), "16");
    await user.type(screen.getByLabelText("GPUs per task"), "1");
    await user.click(screen.getByRole("button", { name: /Save Slurm/i }));

    await waitFor(() => expect(saveExecutionSettings).toHaveBeenCalled());
    expect(lastSavedSettings()).toEqual(
      expect.objectContaining({
        slurm_presets: expect.arrayContaining([
          expect.objectContaining({
            id: "debug-slurm",
            slurm_args: [],
            slurm: expect.objectContaining({
              partition: "debug",
              account: "c41",
              time: "00:30:00",
              tasks_per_node: 1,
              cpus_per_task: 16,
              gpus_per_task: 1,
            }),
          }),
        ]),
      })
    );
  });

  it("saves raw Slurm args and clears typed Slurm resources", async () => {
    const user = userEvent.setup();
    renderPublicSettings();

    await user.click(await screen.findByRole("button", { name: /Add Slurm/i }));
    await user.type(screen.getByLabelText("ID"), "raw-slurm");
    await user.type(screen.getByLabelText("Name"), "Raw Slurm");
    await user.selectOptions(screen.getByLabelText("Mode"), "raw");
    await user.type(screen.getByLabelText("Raw Slurm args"), "--partition=debug\n--time=00:30:00");
    await user.click(screen.getByRole("button", { name: /Save Slurm/i }));

    await waitFor(() => expect(saveExecutionSettings).toHaveBeenCalled());
    expect(lastSavedSettings()).toEqual(
      expect.objectContaining({
        slurm_presets: expect.arrayContaining([
          expect.objectContaining({
            id: "raw-slurm",
            slurm: null,
            slurm_args: ["--partition=debug", "--time=00:30:00"],
          }),
        ]),
      })
    );
  });

  it("validates ids and rank ranges before saving", async () => {
    const user = userEvent.setup();
    renderPublicSettings();

    await user.click(await screen.findByRole("button", { name: /Add build/i }));
    await user.type(screen.getByLabelText("ID"), "bad id");
    await user.type(screen.getByLabelText("Name"), "Bad Build");
    await user.click(screen.getByRole("button", { name: /Save build/i }));

    expect(await screen.findByText(/ID must start/)).toBeInTheDocument();
    expect(saveExecutionSettings).not.toHaveBeenCalled();

    await user.clear(screen.getByLabelText("ID"));
    await user.type(screen.getByLabelText("ID"), "bad-ranks");
    await user.type(screen.getByLabelText("Max MPI ranks"), "0");
    await user.click(screen.getByRole("button", { name: /Save build/i }));

    expect(await screen.findByText(/Max MPI ranks must be an integer >= 1/)).toBeInTheDocument();
    expect(saveExecutionSettings).not.toHaveBeenCalled();
  });

  it("shows the saved settings JSON as read-only export", async () => {
    const user = userEvent.setup();
    renderPublicSettings();

    await user.click(await screen.findByText("JSON export"));

    expect(screen.getByText(/"version": 1/)).toBeInTheDocument();
    expect(screen.getByText(/"build_presets":/)).toBeInTheDocument();
    expect(screen.queryByDisplayValue(/"version": 1/)).not.toBeInTheDocument();
  });
});
