"""Parsing of regression-test .rt check files and lookup of JSON check values.

Shared by the runner (``runner/parsing/regression.py``) and the catalog. Kept free
of package imports so the catalog can use it without importing the runner.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


_STAT_LINE = re.compile(r'^stat\s+"([^"]+)"\s+(\S+)\s+(\S+)$')
# The file must be a plain name: the remote runner fetches it into the local
# work and reference directories by that name, so "/" and ".." are rejected.
_JSON_LINE = re.compile(r'^([A-Za-z0-9._-]+\.json)\s+"?([^"\s]+)"?\s+(\S+)$')


@dataclass
class RtChecks:
    """Checks of one .rt file: the first non-empty line is the description,
    every further line is one check, and ``#`` starts a comment.

    - ``stat``: ``stat "<column>" last|avg <eps>`` as (column, mode, eps)
    - ``json``: ``<file>.json <path> <eps>`` as (file, path, eps); the path is
      dotted from ``root`` (see :func:`json_value`)
    - ``invalid``: lines that are neither, reported as broken checks so a typo
      never drops a check silently

    The same rules as opalx-regression's ``tools/pack_run.py``, so both sites
    evaluate the same checks.
    """

    description: Optional[str] = None
    stat: list[tuple[str, str, float]] = field(default_factory=list)
    json: list[tuple[str, str, float]] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)


def parse_rt_text(text: Optional[str]) -> RtChecks:
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    if not lines:
        return RtChecks()
    rt = RtChecks(description=lines[0].strip('"'))
    for raw in lines[1:]:
        line = raw.split("#")[0].strip()
        if not line:
            continue
        m = _STAT_LINE.match(line) or _JSON_LINE.match(line)
        try:
            check = (m.group(1), m.group(2), float(m.group(3)))
        except (AttributeError, ValueError):  # no match, or eps is not a number
            rt.invalid.append(raw)
            continue
        (rt.stat if m.re is _STAT_LINE else rt.json).append(check)
    return rt


def load_json(path: Path) -> Any:
    """The parsed document, or None if the file is missing or not valid JSON."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def json_value(doc: Any, path: str) -> Optional[float]:
    """The number at a dotted path such as ``root.orbits.0.optics.full_tunes.vertical``.

    ``root`` is the document; each further segment is an object key or a list
    index. Returns None if the path does not resolve or the value is not a
    finite number (true/false do not count; NaN would break the API, whose
    JSON responses forbid it).
    """
    keys = path.split(".")
    if keys[0] != "root":
        return None
    node = doc
    for k in keys[1:]:
        if isinstance(node, dict) and k in node:
            node = node[k]
        elif isinstance(node, list) and k.isdecimal() and int(k) < len(node):
            node = node[int(k)]
        else:
            return None
    if isinstance(node, bool) or not isinstance(node, (int, float)):
        return None
    value = float(node)
    return value if math.isfinite(value) else None
