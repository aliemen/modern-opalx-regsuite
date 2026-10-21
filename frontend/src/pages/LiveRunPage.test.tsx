import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LiveRunPage } from "./LiveRunPage";

vi.mock("../api/runs", () => ({
  getQueueState: vi.fn(async () => ({ machines: [] })),
  cancelRunById: vi.fn(),
}));

vi.mock("../components/LogViewer", () => ({
  LogViewer: () => <div data-testid="log-viewer" />,
}));

describe("LiveRunPage", () => {
  afterEach(cleanup);

  it("uses branch and arch from router state when the run already left the queue", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter
          initialEntries={[{ pathname: "/live/r1", state: { branch: "fix/x", arch: "cuda-daint" } }]}
        >
          <Routes>
            <Route path="/live/:runId" element={<LiveRunPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );
    expect(await screen.findByRole("heading", { name: "fix/x / cuda-daint" })).toBeInTheDocument();
  });
});
