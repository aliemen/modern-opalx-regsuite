"""Beamline visualization subpackage for the OPALX regression test suite.

Public API
----------
generate_beamline_svg(element_positions_path, input_file_path, output_path)
    Parse element positions and types then render an SVG diagram.

Exposed types
-------------
BeamlineElement   — dataclass holding one element's name, type, and s-range
ELEMENT_STYLES    — registry mapping OPAL type names to colour/label; extend
                    this dict to add support for new element types.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .elements import ELEMENT_STYLES, BeamlineElement
from .mesh_extractor import extract_beamline_json
from .parser import build_elements
from .renderer import render_beamline

__all__ = [
    "generate_beamline_svg",
    "extract_beamline_json",
    "BeamlineElement",
    "ELEMENT_STYLES",
]


def generate_beamline_svg(
    element_positions_path: Path,
    input_file_path: Optional[Path],
    output_path: Path,
) -> None:
    """Generate a beamline diagram SVG.

    Parameters
    ----------
    element_positions_path:
        Path to the ``*_ElementPositions.txt`` file produced by OPALX.
    input_file_path:
        Path to the OPAL ``.in`` (or ``.local``) input file.  Used to look up
        element types.  Pass ``None`` to skip type resolution (all elements
        will be rendered with the default style).
    output_path:
        Destination SVG file path.  Parent directories are created if needed.
    """
    elements = build_elements(element_positions_path, input_file_path)
    if elements:
        render_beamline(elements, output_path)
