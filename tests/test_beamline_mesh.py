import base64
import json
import struct
import zlib

import pytest

from modern_opalx_regsuite.beamline_viz.mesh_extractor import EmptyMeshError, extract_beamline_json


def _script(tmp_path, elements):
    """An ``*_ElementPositions.py`` stand-in: the module globals OPALX writes, nothing else."""
    flat = [v for verts, _tris in elements for v in verts]
    packed = base64.b64encode(zlib.compress(struct.pack(f"={len(flat)}d", *flat))).decode()
    path = tmp_path / "Sim_ElementPositions.py"
    path.write_text(
        f"vertices_base64 = {packed!r}\n"
        f"numVertices = {[len(v) // 3 for v, _t in elements]!r}\n"
        f"triangles = {[t for _v, t in elements]!r}\n"
        f"color = {[2] * len(elements)!r}\n"
    )
    return path


TRIANGLE = ([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 2.0], [0, 1, 2])


def test_drops_empty_elements_and_writes_finite_bounds(tmp_path):
    out = tmp_path / "mesh.json"
    extract_beamline_json(_script(tmp_path, [([], []), TRIANGLE]), out)
    mesh = json.loads(out.read_text())  # strict JSON: no Infinity tokens
    assert len(mesh["elements"]) == 1
    assert mesh["bounds"] == {"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 2.0]}


@pytest.mark.parametrize("elements", [
    [([], []), ([], [])],  # OPALX wrote elements without vertices
    [([0.0, 0.0, 0.3, 0.0, 0.0, 1.0, 0.0, 0.0, 7.4], [0, 1, 2])],  # every vertex on the axis
])
def test_mesh_without_surface_raises_and_writes_nothing(tmp_path, elements):
    out = tmp_path / "mesh.json"
    with pytest.raises(EmptyMeshError):
        extract_beamline_json(_script(tmp_path, elements), out)
    assert not out.exists()
