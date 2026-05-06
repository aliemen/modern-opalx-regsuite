import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TriggerPage } from "./TriggerPage";

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
});
