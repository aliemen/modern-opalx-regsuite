/** One beamline element as triangles: flat [x0,y0,z0, x1,...] vertices and an index list. */
export interface BeamlineElement {
  vertices: number[];
  indices: number[];
  /** Element type, an index into the viewer's palette (OPALX MeshGenerator order). */
  colorIndex: number;
}

export interface BeamlineMesh {
  elements: BeamlineElement[];
  bounds: { min: [number, number, number]; max: [number, number, number] };
}

/**
 * Parse a `plots/<test>_beamline.json` mesh, keeping only elements that can be drawn.
 *
 * Returns null when nothing visible is left, so the caller shows the 2D diagram. Older
 * runs hold files with `Infinity` bounds (not valid JSON), elements without vertices,
 * or every vertex on the beam axis; bounds are therefore recomputed from the vertices.
 */
export function parseBeamlineMesh(text: string): BeamlineMesh | null {
  let raw: unknown;
  try {
    raw = JSON.parse(text.replace(/-?\bInfinity\b/g, "null"));
  } catch {
    return null;
  }
  const source = (raw as { elements?: unknown } | null)?.elements;
  if (!Array.isArray(source)) return null;

  const min: [number, number, number] = [Infinity, Infinity, Infinity];
  const max: [number, number, number] = [-Infinity, -Infinity, -Infinity];
  const elements: BeamlineElement[] = [];
  for (const e of source as Partial<BeamlineElement>[]) {
    const { vertices, indices } = e ?? {};
    if (!Array.isArray(vertices) || !Array.isArray(indices)) continue;
    if (vertices.length < 9 || indices.length < 3 || !vertices.every(Number.isFinite)) continue;
    vertices.forEach((v, i) => {
      const axis = i % 3;
      if (v < min[axis]) min[axis] = v;
      if (v > max[axis]) max[axis] = v;
    });
    elements.push({ vertices, indices, colorIndex: Number.isInteger(e.colorIndex) ? e.colorIndex! : 0 });
  }
  // Triangles need extent along at least two axes to have any area.
  const extended = [0, 1, 2].filter((axis) => max[axis] > min[axis]).length;
  if (elements.length === 0 || extended < 2) return null;
  return { elements, bounds: { min, max } };
}
