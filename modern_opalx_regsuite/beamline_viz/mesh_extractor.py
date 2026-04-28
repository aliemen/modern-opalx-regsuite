"""Extract a compact mesh JSON from a `*_ElementPositions.py` script.

OPALX writes a self-contained Python script per test that bundles the
beamline mesh as module-level globals plus exporter functions
(``exportVTK``, ``exportWeb``, ``showVTK``, ``projectToPlane``).  We sidestep
the exporters entirely and read the data directly: the script populates
``vertices_base64`` (zlib + base64-packed doubles), ``numVertices``,
``triangles``, and ``color`` at import time, before ``argparse`` runs under
``__main__``, so importing the module is side-effect-free for our purposes.

The emitted JSON is consumed by the React three.js viewer in the regression
test website.  Schema::

    {
      "elements": [
        {"vertices": [x0,y0,z0, x1,y1,z1, ...], "indices": [..], "colorIndex": int},
        ...
      ],
      "bounds": {"min": [x,y,z], "max": [x,y,z]}
    }
"""
from __future__ import annotations

import base64
import importlib.util
import json
import math
import struct
import sys
import zlib
from pathlib import Path


def extract_beamline_json(script_path: Path, out_path: Path) -> None:
    """Read mesh data from *script_path* and write it to *out_path* as JSON."""
    module_name = f"_opalx_mesh_{abs(hash(str(script_path)))}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load script as module: {script_path}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec so any internal imports resolve correctly.
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)

    vertices_base64: str = module.vertices_base64
    num_vertices = list(module.numVertices)
    triangles = list(module.triangles)
    color = list(module.color)

    # Decode the packed-double vertex buffer once. Each element gets
    # ``numVertices[i] * 3`` doubles (8 bytes each).
    raw = zlib.decompress(base64.b64decode(vertices_base64))
    elements: list[dict] = []
    cursor = 0
    bounds_min = [math.inf, math.inf, math.inf]
    bounds_max = [-math.inf, -math.inf, -math.inf]
    for i, n in enumerate(num_vertices):
        floats_count = 3 * n
        end = cursor + 8 * floats_count
        floats = struct.unpack(f"={floats_count}d", raw[cursor:end])
        cursor = end

        # Update bounds along each axis (vertices are interleaved x,y,z).
        for axis in range(3):
            axis_vals = floats[axis::3]
            if axis_vals:
                lo = min(axis_vals)
                hi = max(axis_vals)
                if lo < bounds_min[axis]:
                    bounds_min[axis] = lo
                if hi > bounds_max[axis]:
                    bounds_max[axis] = hi

        elements.append({
            "vertices": list(floats),
            "indices": [int(t) for t in triangles[i]],
            "colorIndex": int(color[i]),
        })

    if not elements:
        bounds_min = [0.0, 0.0, 0.0]
        bounds_max = [0.0, 0.0, 0.0]

    payload = {
        "elements": elements,
        "bounds": {"min": bounds_min, "max": bounds_max},
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload), encoding="utf-8")
