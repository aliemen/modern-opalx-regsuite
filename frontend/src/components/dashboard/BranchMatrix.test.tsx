import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import type { MatrixRow } from "../../api/results";
import { useRunSelection } from "../../hooks/useRunSelection";
import { makeRun } from "../../test/fixtures";
import { BranchMatrix, MATRIX_INITIAL_ROWS } from "./BranchMatrix";

function row(branch: string, lastActivity: string, archs: string[]): MatrixRow {
  return {
    branch,
    last_activity: lastActivity,
    cells: Object.fromEntries(
      archs.map((arch) => [
        arch,
        { run: makeRun({ branch, arch, run_id: `${arch}-run`, started_at: lastActivity }), run_count: 1 },
      ])
    ),
  };
}

function Harness({ rows }: { rows: MatrixRow[] }) {
  const selection = useRunSelection();
  return (
    <>
      <span data-testid="count">{selection.count}</span>
      <BranchMatrix rows={rows} runningCells={new Set(["master::cuda-daint"])} selection={selection} />
    </>
  );
}

function renderMatrix(rows: MatrixRow[]) {
  return render(
    <MemoryRouter>
      <Harness rows={rows} />
    </MemoryRouter>
  );
}

function branchOrder(): string[] {
  return screen.getAllByRole("rowheader").map((th) => within(th).getAllByText(/./)[0].textContent ?? "");
}

const rows = [
  row("older", "2026-10-01T00:00:00Z", ["cpu-serial"]),
  row("master", "2026-09-01T00:00:00Z", ["cpu-serial", "cuda-daint"]),
  row("v1-fix/decay", "2026-10-20T00:00:00Z", ["cuda-daint"]),
];

describe("BranchMatrix", () => {
  afterEach(cleanup);

  it("pins master first, then sorts by recent activity or name", async () => {
    renderMatrix(rows);
    expect(branchOrder()).toEqual(["master", "v1-fix/decay", "older"]);
    await userEvent.selectOptions(screen.getByLabelText("Sort branches"), "name");
    expect(branchOrder()).toEqual(["master", "older", "v1-fix/decay"]);
  });

  it("links cells to the encoded run detail and marks running cells", () => {
    renderMatrix(rows);
    const link = screen.getByTitle(/^v1-fix\/decay \/ cuda-daint: passed/);
    expect(link).toHaveAttribute("href", "/results/v1-fix%2Fdecay/cuda-daint/cuda-daint-run");
    expect(screen.getAllByLabelText("running now")).toHaveLength(1);
  });

  it("filters rows and collapses long lists behind Show all", async () => {
    const many = Array.from({ length: MATRIX_INITIAL_ROWS + 2 }, (_, i) =>
      row(`b${String(i).padStart(2, "0")}`, `2026-10-${String(i + 1).padStart(2, "0")}T00:00:00Z`, ["cpu-serial"])
    );
    renderMatrix(many);
    expect(screen.getAllByRole("rowheader")).toHaveLength(MATRIX_INITIAL_ROWS);
    await userEvent.click(screen.getByRole("button", { name: `Show all (${many.length})` }));
    expect(screen.getAllByRole("rowheader")).toHaveLength(many.length);

    await userEvent.type(screen.getByLabelText("Filter branches"), "b03");
    expect(branchOrder()).toEqual(["b03"]);
  });

  it("selects every cell of a row in Select mode, including master", async () => {
    renderMatrix(rows);
    expect(screen.queryByLabelText("Select all builds of master")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Select" }));
    await userEvent.click(screen.getByLabelText("Select all builds of master"));
    expect(screen.getByTestId("count")).toHaveTextContent("2");
    await userEvent.click(screen.getByLabelText("Select master / cuda-daint"));
    expect(screen.getByTestId("count")).toHaveTextContent("1");
    // Leaving Select mode clears the selection.
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.getByTestId("count")).toHaveTextContent("0");
  });
});
