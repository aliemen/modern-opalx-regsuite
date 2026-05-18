import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { listSshKeys } from "../../api/keys";
import { SshKeysSection } from "./SshKeysSection";

vi.mock("../../api/keys", async () => {
  const actual = await vi.importActual<typeof import("../../api/keys")>(
    "../../api/keys"
  );
  return {
    ...actual,
    listSshKeys: vi.fn(async () => [
      {
        name: "cscs-key",
        created_at: "2026-05-18T08:00:00Z",
        fingerprint: "SHA256:test",
      },
    ]),
    uploadSshKey: vi.fn(),
    replaceSshKey: vi.fn(),
    deleteSshKey: vi.fn(),
  };
});

function renderSection() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <SshKeysSection />
    </QueryClientProvider>
  );
}

describe("SshKeysSection", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.restoreAllMocks();
  });

  it("keeps refresh-key scrolling scoped to the SSH key form", async () => {
    const scrollTo = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
    const user = userEvent.setup();

    renderSection();

    await screen.findByText("cscs-key");
    await user.click(
      screen.getByRole("button", {
        name: "Replace cscs-key",
      })
    );

    expect(listSshKeys).toHaveBeenCalled();
    expect(screen.getByText(/Replacing key/)).toBeInTheDocument();
    expect(scrollTo).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(scrollIntoView).toHaveBeenCalledWith({
        behavior: "smooth",
        block: "nearest",
      });
    });
  });
});
