import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { resultsPath } from "./paths";

function Params() {
  const { branch, arch, runId } = useParams();
  return <span>{`${branch}|${arch}|${runId ?? ""}`}</span>;
}

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/results/:branch/:arch" element={<Params />} />
        <Route path="/results/:branch/:arch/:runId" element={<Params />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("resultsPath", () => {
  it("round-trips a branch containing a slash through the router", () => {
    renderAt(resultsPath("v1-fix/decay-daughter-frame", "cuda-daint", "r1"));
    expect(screen.getByText("v1-fix/decay-daughter-frame|cuda-daint|r1")).toBeTruthy();
  });

  it("builds the run-list route without a run id", () => {
    expect(resultsPath("fix/a", "cpu-serial")).toBe("/results/fix%2Fa/cpu-serial");
    renderAt(resultsPath("fix/a", "cpu-serial"));
    expect(screen.getByText("fix/a|cpu-serial|")).toBeTruthy();
  });
});
