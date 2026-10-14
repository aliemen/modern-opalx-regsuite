import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TestSkipConfigsSection } from "./TestSkipConfigsSection";

const apiMocks = vi.hoisted(() => ({
  listSkipConfigs: vi.fn(),
  getSkipCandidates: vi.fn(),
  createSkipConfig: vi.fn(),
  updateSkipConfig: vi.fn(),
  deleteSkipConfig: vi.fn(),
}));

vi.mock("../../api/skipConfigs", async () => {
  const actual = await vi.importActual<typeof import("../../api/skipConfigs")>(
    "../../api/skipConfigs",
  );
  return { ...actual, ...apiMocks };
});

function renderSection() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <TestSkipConfigsSection />
    </QueryClientProvider>,
  );
}

describe("TestSkipConfigsSection", () => {
  beforeEach(() => {
    apiMocks.listSkipConfigs.mockResolvedValue([]);
    apiMocks.getSkipCandidates.mockResolvedValue({
      regression: [
        { name: "DBA-COF-Gauss", median_seconds: 289 },
        { name: "FodoCell", median_seconds: 10 },
      ],
      unit: [{ name: "TestOrbitThreader", median_seconds: 46 }],
    });
    apiMocks.createSkipConfig.mockImplementation(async (body) => ({ id: "slow", ...body }));
  });
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("creates a config from checked candidates and an unlisted name", async () => {
    const user = userEvent.setup();
    renderSection();

    await user.click(await screen.findByRole("button", { name: "New skip config" }));
    await user.type(screen.getByLabelText("Name"), "Slow on CPU");
    expect(await screen.findByText("289 s")).toBeInTheDocument();
    await user.click(screen.getByLabelText("Skip DBA-COF-Gauss"));
    await user.click(screen.getByLabelText("Skip TestOrbitThreader"));
    await user.type(screen.getByLabelText("Add unit test name"), "TestScalingFFAMagnet");
    await user.click(screen.getByRole("button", { name: "Add unit test" }));
    expect(screen.getByText("not seen recently")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(apiMocks.createSkipConfig).toHaveBeenCalledTimes(1));
    expect(apiMocks.createSkipConfig.mock.calls[0][0]).toEqual({
      name: "Slow on CPU",
      description: null,
      regression_tests: ["DBA-COF-Gauss"],
      unit_tests: ["TestOrbitThreader", "TestScalingFFAMagnet"],
    });
  });

  it("rejects invalid unlisted names without saving", async () => {
    const user = userEvent.setup();
    renderSection();

    await user.click(await screen.findByRole("button", { name: "New skip config" }));
    await user.type(screen.getByLabelText("Add unit test name"), "bad name;");
    await user.click(screen.getByRole("button", { name: "Add unit test" }));

    expect(screen.getByText(/Use letters, digits/)).toBeInTheDocument();
    expect(apiMocks.createSkipConfig).not.toHaveBeenCalled();
  });

  it("deletes a config after confirmation", async () => {
    apiMocks.listSkipConfigs.mockResolvedValue([
      {
        id: "slow",
        name: "Slow on CPU",
        description: null,
        unit_tests: [],
        regression_tests: ["DBA-COF-Gauss"],
      },
    ]);
    apiMocks.deleteSkipConfig.mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderSection();

    expect(await screen.findByText("skips 1 regression")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete Slow on CPU" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(apiMocks.deleteSkipConfig).toHaveBeenCalledWith("slow"));
  });
});
