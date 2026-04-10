"""Parsers for OPALX element position and type data.

Two data sources are combined:
  1. ``*_ElementPositions.txt`` — produced by OPALX during a run; gives the
     s-position range [start, end] for every element.
  2. OPAL ``.in`` (or ``.local``) input file — gives the OPAL element type
     (e.g. ``RFCavity``, ``Solenoid``, ``Drift``) for each element name.
"""
from __future__ import annotations

import re
from pathlib import Path

from .elements import BeamlineElement

# ---------------------------------------------------------------------------
# ElementPositions.txt parser
# ---------------------------------------------------------------------------

# Lines look like:
#   "BEGIN: GUN"    0.0    0.0    0.0
#   "END: GUN"      0.29270745    0.0    0.0
_RE_POSITIONS = re.compile(
    r'"(BEGIN|END):\s*(\w+)"\s+([\d.eE+\-]+)',
    re.IGNORECASE,
)


def parse_element_positions(txt_path: Path) -> dict[str, tuple[float, float]]:
    """Return ``{element_name: (s_start, s_end)}`` from an ElementPositions.txt file."""
    begins: dict[str, float] = {}
    ends: dict[str, float] = {}

    text = txt_path.read_text(encoding="utf-8", errors="replace")
    for match in _RE_POSITIONS.finditer(text):
        marker, name, s_str = match.group(1).upper(), match.group(2).upper(), match.group(3)
        s = float(s_str)
        if marker == "BEGIN":
            begins[name] = s
        else:
            ends[name] = s

    result: dict[str, tuple[float, float]] = {}
    for name in begins:
        if name in ends:
            result[name] = (begins[name], ends[name])

    return result


# ---------------------------------------------------------------------------
# OPAL input file parser
# ---------------------------------------------------------------------------

# Strip single-line C++ comments and C-style block comments before matching.
_RE_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_RE_LINE_COMMENT = re.compile(r"//[^\n]*")

# Element definition pattern: NAME: TYPE, ...
# The colon separates the element label from the OPAL type keyword.
_RE_ELEMENT_DEF = re.compile(
    r"^\s*([A-Za-z_]\w*)\s*:\s*([A-Za-z_]\w*)\s*[,;]",
    re.MULTILINE,
)

# Keywords that appear in assignment statements (not element definitions)
# and should be ignored.
_NON_ELEMENT_KEYWORDS = frozenset(
    {
        "OPTION", "TITLE", "LINE", "VALUE", "REAL", "INTEGER", "BOOL", "STRING",
        "BOOL", "IF", "ELSE", "FOR", "WHILE", "PRINT", "SURVEY",
    }
)


def parse_element_types(in_path: Path) -> dict[str, str]:
    """Return ``{ELEMENT_NAME: OpalType}`` parsed from an OPAL ``.in`` file.

    Keys are uppercased for case-insensitive lookup.  Values preserve the
    original capitalisation found in the file (e.g. ``"RFCavity"``,
    ``"Solenoid"``).
    """
    text = in_path.read_text(encoding="utf-8", errors="replace")

    # Strip block and line comments to avoid false matches
    text = _RE_BLOCK_COMMENT.sub(" ", text)
    text = _RE_LINE_COMMENT.sub("", text)

    result: dict[str, str] = {}
    for match in _RE_ELEMENT_DEF.finditer(text):
        name, opal_type = match.group(1), match.group(2)
        if name.upper() in _NON_ELEMENT_KEYWORDS or opal_type.upper() in _NON_ELEMENT_KEYWORDS:
            continue
        result[name.upper()] = opal_type

    return result


# ---------------------------------------------------------------------------
# Combined builder
# ---------------------------------------------------------------------------


def build_elements(
    txt_path: Path,
    in_path: Path | None = None,
) -> list[BeamlineElement]:
    """Build a list of :class:`BeamlineElement` objects from the two data sources.

    Elements with zero length are discarded.  The list is sorted by start
    position, then by descending length (longest elements first at the same
    starting point).
    """
    positions = parse_element_positions(txt_path)
    types = parse_element_types(in_path) if in_path is not None and in_path.exists() else {}

    elements: list[BeamlineElement] = []
    for name, (start, end) in positions.items():
        if end <= start:
            continue
        elem_type = types.get(name.upper(), "_default")
        elements.append(BeamlineElement(name=name, elem_type=elem_type, start=start, end=end))

    elements.sort(key=lambda e: (e.start, -(e.end - e.start)))
    return elements
