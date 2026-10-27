import { describe, expect, it } from "vitest";
import { parseBeamlineMesh } from "./beamlineMesh";

const triangle = { vertices: [0, 0, 0, 1, 0, 0, 0, 1, 2], indices: [0, 1, 2], colorIndex: 2 };

describe("parseBeamlineMesh", () => {
  it("drops empty elements and recomputes bounds", () => {
    const text =
      '{"elements": [{"vertices": [], "indices": [], "colorIndex": 6}, ' +
      JSON.stringify(triangle) +
      '], "bounds": {"min": [Infinity, Infinity, Infinity], "max": [-Infinity, -Infinity, -Infinity]}}';
    expect(parseBeamlineMesh(text)).toEqual({
      elements: [triangle],
      bounds: { min: [0, 0, 0], max: [1, 1, 2] },
    });
  });

  it("rejects meshes with nothing to draw", () => {
    const empty =
      '{"elements": [{"vertices": [], "indices": [], "colorIndex": 1}], ' +
      '"bounds": {"min": [Infinity, Infinity, Infinity], "max": [-Infinity, -Infinity, -Infinity]}}';
    const onAxis = JSON.stringify({
      elements: [{ vertices: [0, 0, 0.3, 0, 0, 1, 0, 0, 7.4], indices: [0, 1, 2], colorIndex: 6 }],
    });
    expect(parseBeamlineMesh(empty)).toBeNull();
    expect(parseBeamlineMesh(onAxis)).toBeNull();
    expect(parseBeamlineMesh("not json")).toBeNull();
    expect(parseBeamlineMesh("{}")).toBeNull();
  });
});
