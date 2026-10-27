import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RegressionMetric, RegressionSimulation, RunSeries } from "../../api/results";
import { RegressionTestsBrowser } from "./RegressionTestsBrowser";

// jsdom has neither canvas nor WebGL; the charts and the 3D view are not under test here.
vi.mock("../../components/SeriesPlot", () => ({
  SeriesPlot: ({ metric }: { metric: string }) => <div data-testid="series-plot">{metric}</div>,
}));
vi.mock("../../components/BeamlineViewer", () => ({
  BeamlineViewer: () => <div data-testid="beamline-3d" />,
}));

function metric(name: string, state = "passed", series = true): RegressionMetric {
  return {
    metric: name, mode: "last", eps: 1e-6, delta: state === "passed" ? 0 : 1, state,
    reference_value: 1, current_value: 1, plot: null, series,
  };
}

function sim(name: string, state: string, metrics: RegressionMetric[], extra: Partial<RegressionSimulation> = {}): RegressionSimulation {
  return {
    name, description: null, state, log_file: null, duration_seconds: 1,
    containers: [{ id: null, state, revision: null, metrics }],
    beamline_plot: null, beamline_3d_data: null, exit_code: 0, crash_signal: null, crash_summary: null,
    ...extra,
  };
}

const SERIES: RunSeries = { schema: 2, source: "runner", max_points: 100, sims: {} };

function Search() {
  return <output data-testid="search">{useLocation().search}</output>;
}

function renderBrowser(simulations: RegressionSimulation[], url = "/run") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route
            path="/run"
            element={
              <>
                <RegressionTestsBrowser
                  simulations={simulations}
                  runPath="runs/master/cpu/r1"
                  series={{ queryKey: ["s"], load: () => Promise.resolve(SERIES) }}
                />
                <Search />
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const detailHeading = () => screen.getByRole("heading", { level: 3 });

describe("RegressionTestsBrowser", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("opens the first failing test and switches through the list", () => {
    renderBrowser([
      sim("Alpha", "passed", [metric("rms_x")]),
      sim("Beta", "failed", [metric("rms_x", "failed")]),
      sim("Gamma", "passed", [metric("rms_x")]),
    ]);
    expect(detailHeading()).toHaveTextContent("Beta");

    const nav = screen.getByRole("navigation", { name: "Regression tests" });
    expect(within(nav).getByRole("link", { current: true })).toHaveTextContent("Beta");
    fireEvent.click(within(nav).getByRole("link", { name: /Gamma/ }));
    expect(detailHeading()).toHaveTextContent("Gamma");
    expect(screen.getByTestId("search")).toHaveTextContent("?test=Gamma");

    fireEvent.click(screen.getAllByRole("button", { name: "Previous test" })[0]);
    expect(detailHeading()).toHaveTextContent("Beta");
  });

  it("filters the list by name and by status", () => {
    renderBrowser([
      sim("Alpha", "passed", [metric("rms_x")]),
      sim("Beta", "failed", [metric("rms_x", "failed")]),
    ], "/run?test=Alpha");
    const nav = screen.getByRole("navigation", { name: "Regression tests" });
    expect(within(nav).getAllByRole("link")).toHaveLength(2);

    fireEvent.click(within(nav).getByRole("button", { name: "Not passed (1)" }));
    expect(within(nav).getAllByRole("link").map((a) => a.textContent)).toEqual([expect.stringContaining("Beta")]);
    expect(detailHeading()).toHaveTextContent("Alpha"); // the selection survives the filter

    fireEvent.click(within(nav).getByRole("button", { name: "All (2)" }));
    fireEvent.change(within(nav).getByRole("searchbox", { name: "Filter tests by name" }), { target: { value: "alp" } });
    expect(within(nav).getAllByRole("link")).toHaveLength(1);
  });

  it("shows only the checks of a test without plots, never its beamline", () => {
    renderBrowser([
      sim("Dist-gauss", "passed", [metric("rms_x", "passed", false)], { beamline_plot: "plots/Dist-gauss_beamline.svg" }),
    ]);
    expect(screen.getByRole("table", { name: "Checks of Dist-gauss" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Beamline" })).not.toBeInTheDocument();
    expect(screen.queryByAltText(/beamline/)).not.toBeInTheDocument();
  });

  it("falls back to the 2D diagram when the 3D mesh has nothing to draw", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{"elements": [{"vertices": [], "indices": [], "colorIndex": 6}], "bounds": {"min": [Infinity, 0, 0], "max": [-Infinity, 0, 0]}}')
    );
    vi.stubGlobal("fetch", fetchMock);
    renderBrowser([
      sim("RFCavity", "passed", [metric("rms_x")], {
        beamline_plot: "plots/RFCavity_beamline.svg",
        beamline_3d_data: "plots/RFCavity_beamline.json",
      }),
    ]);
    const img = await screen.findByAltText("RFCavity beamline diagram");
    expect(img.getAttribute("src")).toBe("/data/runs/master/cpu/r1/plots/RFCavity_beamline.svg");
    expect(fetchMock).toHaveBeenCalledWith("/data/runs/master/cpu/r1/plots/RFCavity_beamline.json");
    expect(screen.queryByRole("button", { name: "3D" })).not.toBeInTheDocument();
  });

  it("offers 3D and 2D when the mesh is usable", async () => {
    const mesh = { elements: [{ vertices: [0, 0, 0, 1, 0, 0, 0, 1, 1], indices: [0, 1, 2], colorIndex: 2 }] };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(mesh))));
    renderBrowser([
      sim("Quad", "passed", [metric("rms_x")], {
        beamline_plot: "plots/Quad_beamline.svg",
        beamline_3d_data: "plots/Quad_beamline.json",
      }),
    ]);
    expect(await screen.findByTestId("beamline-3d")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "2D" }));
    expect(screen.getByAltText("Quad beamline diagram")).toBeInTheDocument();
  });

  it("lists skipped tests apart from the executed ones", () => {
    renderBrowser([sim("Alpha", "passed", [metric("rms_x")]), sim("Slow", "skipped", [])]);
    expect(screen.getByText("Skipped (1)")).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Regression tests" });
    expect(within(nav).queryByRole("link", { name: /Slow/ })).not.toBeInTheDocument();
  });
});
