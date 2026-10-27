"""Recover plot data from the metric SVGs of runs made before ``series.json.gz`` existed.

Only valid for SVGs written by the old ``runner/plotting.py::_write_stat_plot`` with
Matplotlib 3.10 defaults (every production SVG, checked 2026-10-27):

* ``axes_1`` holds current (stroke ``#1f77b4``, width 2) and reference (``#ff7f0e``, width 2)
  against s; the twin ``axes_2`` holds the dashed grey (``#808080``) difference.
* Tick positions are ``<use x= y=>`` inside ``xtick_N``/``ytick_N`` groups and the label
  string survives as an XML comment (``<!-- 0.25 -->``, minus as U+2212). The axis group
  may end with an offset text such as ``1e−9``, ``+1e3`` or ``1e−11+1.000463999e2``
  (value = label * scale + offset).
* Curves are ``line2d_N`` paths of M/L commands in pt with 6 decimals; matplotlib's path
  simplification already dropped points that did not change the drawing, and it repeats
  the last vertex. A new ``M`` after the first starts a new segment (a NaN gap).

The pixel-to-data map of each axis is a least-squares fit over its ticks. Recovered values
are display copies: the last point is verified against ``regression-tests.json`` by the
caller (``migration/series_migration.py``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_OFFSET_RE = re.compile(r"(1e[-+]?\d+)?\s*([-+](?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?)?")
_CURRENT, _REFERENCE, _DIFFERENCE = "#1f77b4", "#ff7f0e", "#808080"


class SvgFormatError(ValueError):
    """The SVG is not a stat plot this module understands."""


@dataclass
class Curve:
    """x and y in data units; a ``None`` y marks a break between path segments."""

    x: list[float]
    y: list[Optional[float]]

    @property
    def last(self) -> Optional[float]:
        return next((v for v in reversed(self.y) if v is not None), None)


@dataclass
class AxisMap:
    """value = a * pixel + b, fitted over the ticks of one axis."""

    a: float
    b: float
    has_offset: bool  # offset text adds a constant (e.g. ``+1.000463999e2``)
    residual: float  # worst tick misfit relative to the tick value range

    def __call__(self, px: float) -> float:
        return self.a * px + self.b


@dataclass
class StatPlot:
    current: Optional[Curve]
    reference: Optional[Curve]
    difference: Optional[Curve]
    y: AxisMap
    y_span: float  # data range covered by the plot area's height on the value axis


def parse_stat_svg(text: str) -> StatPlot:
    """Recover current, reference and difference curves; raises :class:`SvgFormatError`."""
    axes1 = _group(text, "axes_1")
    if axes1 is None:
        raise SvgFormatError("no axes_1 group")
    plot_area = axes1.split('<g id="legend_1">')[0]
    x_axis = _group(axes1, "matplotlib.axis_1")
    y_axis = _group(axes1, "matplotlib.axis_2")
    if x_axis is None or y_axis is None:
        raise SvgFormatError("axes_1 has no x or y axis group")
    xmap, ymap = _axis_map(x_axis, "x"), _axis_map(y_axis, "y")
    box = _plot_box_height(axes1)

    current = _curve(plot_area, _CURRENT, "stroke-width: 2", xmap, ymap)
    reference = _curve(plot_area, _REFERENCE, "stroke-width: 2", xmap, ymap)
    if current is None and reference is None:
        raise SvgFormatError("no current or reference curve")

    difference = None
    axes2 = _group(text, "axes_2")
    if axes2 is not None and _DIFFERENCE in axes2:
        m = re.search(r'<g id="(matplotlib\.axis_\d+)">', axes2)
        d_axis = _group(axes2, m.group(1)) if m else None
        if d_axis is None:
            raise SvgFormatError("axes_2 has a difference curve but no axis group")
        difference = _curve(axes2.split('<g id="legend_2">')[0], _DIFFERENCE, "", xmap, _axis_map(d_axis, "y"))
    return StatPlot(current, reference, difference, ymap, abs(ymap.a) * box)


def _group(text: str, gid: str) -> Optional[str]:
    """Text of ``<g id="gid">`` up to its balanced ``</g>``."""
    start = text.find(f'<g id="{gid}">')
    if start < 0:
        return None
    depth = 0
    for m in re.finditer(r"<g\b|</g>", text[start:]):
        depth += 1 if m.group(0) == "<g" else -1
        if depth == 0:
            return text[start : start + m.end()]
    return None


def _number(label: str) -> float:
    return float(label.replace("−", "-"))


def _parse_offset(label: str) -> Optional[tuple[float, float]]:
    """``(scale, offset)`` of an axis offset text, or ``None`` if *label* is not one."""
    s = label.replace("−", "-").strip()
    m = _OFFSET_RE.fullmatch(s)
    if not s or not m or not (m.group(1) or m.group(2)):
        return None
    return (float(m.group(1)) if m.group(1) else 1.0), (float(m.group(2)) if m.group(2) else 0.0)


def _axis_map(axis: str, coord: str) -> AxisMap:
    ticks: list[tuple[float, float]] = []
    tick_starts = list(re.finditer(r'<g id="[xy]tick_\d+">', axis))
    for i, m in enumerate(tick_starts):
        end = tick_starts[i + 1].start() if i + 1 < len(tick_starts) else len(axis)
        seg = axis[m.end() : end]
        use = re.search(rf'<use xlink:href="#[^"]+" x="({_NUM})" y="({_NUM})"', seg)
        label = re.search(r"<!-- (.*?) -->", seg)
        if use is None or label is None:
            continue
        try:
            ticks.append((float(use.group(1 if coord == "x" else 2)), _number(label.group(1))))
        except ValueError:
            raise SvgFormatError(f"unparsable tick label {label.group(1)!r}") from None
    if len(ticks) < 2:
        raise SvgFormatError(f"{coord} axis has fewer than 2 ticks")

    scale, offset = 1.0, 0.0
    tail = axis[tick_starts[-1].end() :] if tick_starts else axis
    for label in re.findall(r'<g id="text_\d+">\s*<!-- (.*?) -->', tail):
        parsed = _parse_offset(label)
        if parsed is not None:
            scale, offset = parsed
    pts = [(p, v * scale + offset) for p, v in ticks]

    n = len(pts)
    sp = sum(p for p, _ in pts)
    sv = sum(v for _, v in pts)
    spp = sum(p * p for p, _ in pts)
    spv = sum(p * v for p, v in pts)
    det = n * spp - sp * sp
    if det == 0:
        raise SvgFormatError(f"{coord} axis ticks share one position")
    a = (n * spv - sp * sv) / det
    b = (sv - a * sp) / n
    vrange = max(v for _, v in pts) - min(v for _, v in pts)
    resid = max(abs(a * p + b - v) for p, v in pts) / vrange if vrange else 0.0
    return AxisMap(a, b, offset != 0.0, resid)


def _plot_box_height(axes: str) -> float:
    """Height in pt of the axes background patch (the first ``patch_N`` in the axes group)."""
    m = re.search(r'<g id="patch_\d+">\s*<path d="([^"]*)"', axes)
    if m is None:
        raise SvgFormatError("axes has no background patch")
    ys = [float(y) for _, y in re.findall(rf"[ML] ({_NUM}) ({_NUM})", m.group(1))]
    if not ys:
        raise SvgFormatError("empty axes background patch")
    return max(ys) - min(ys)


def _curve(area: str, color: str, extra: str, xmap: AxisMap, ymap: AxisMap) -> Optional[Curve]:
    paths = [
        d
        for d, style in re.findall(r'<g id="line2d_\d+">\s*<path d="([^"]*)"[^>]*style="([^"]*)"', area)
        if f"stroke: {color}" in style and extra in style
    ]
    if not paths:
        return None
    if len(paths) > 1:
        raise SvgFormatError(f"{len(paths)} curves with stroke {color}")
    x: list[float] = []
    y: list[Optional[float]] = []
    prev: Optional[tuple[float, float]] = None
    for cmd, px, py in re.findall(rf"([ML]) ({_NUM}) ({_NUM})", paths[0]):
        pt = (float(px), float(py))
        if pt == prev:
            continue
        if cmd == "M" and x:
            # Gap row halfway between the segments, so the chart does not bridge a NaN gap.
            x.append((x[-1] + xmap(pt[0])) / 2)
            y.append(None)
        x.append(xmap(pt[0]))
        y.append(ymap(pt[1]))
        prev = pt
    return Curve(x, y)
