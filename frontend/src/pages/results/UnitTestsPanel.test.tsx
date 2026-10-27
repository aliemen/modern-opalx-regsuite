import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { UnitTestCase } from "../../api/results";
import { UnitTestsPanel } from "./UnitTestsPanel";

const test = (name: string, status: string): UnitTestCase => ({ name, status, duration_seconds: 0.5, output_snippet: null });

const TESTS = [
  test("TestAlpha", "passed"),
  test("TestSlow", "skipped"),
  test("TestBeta", "failed"),
  ...Array.from({ length: 20 }, (_, i) => test(`TestField${i}`, "passed")),
];

function open() {
  render(<UnitTestsPanel tests={TESTS} summary="22/23 passed" />);
  const toggle = screen.getByRole("button", { name: /Unit Tests/ });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  return screen.getByRole("region", { name: "Unit test results" });
}

const names = (region: HTMLElement) =>
  within(region).getAllByRole("row").slice(1).map((r) => r.querySelector("td")?.textContent);

describe("UnitTestsPanel", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("lists problems first and skipped tests last in a focusable scroll region", () => {
    const region = open();
    expect(region).toHaveAttribute("tabindex", "0");
    const rows = names(region);
    expect(rows[0]).toBe("TestBeta");
    expect(rows.at(-1)).toBe("TestSlow");
  });

  it("filters by name and by status and announces the count", () => {
    vi.useFakeTimers();
    const region = open();
    fireEvent.change(screen.getByRole("searchbox", { name: "Filter unit tests by name" }), { target: { value: "field1" } });
    expect(names(region)).toEqual(["TestField1", ...Array.from({ length: 10 }, (_, i) => `TestField${10 + i}`)]);
    act(() => vi.advanceTimersByTime(500));
    expect(screen.getByRole("status")).toHaveTextContent("11 of 23 tests");

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Not passed (1)" }));
    expect(names(region)).toEqual(["TestBeta"]);

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "nothing" } });
    expect(within(region).getByText("No unit tests match.")).toBeInTheDocument();
  });
});
