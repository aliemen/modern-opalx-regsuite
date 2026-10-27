"""Round trip: draw with the old SVG writer, recover with migration.svg_series."""
import math

import numpy as np
import pytest

from modern_opalx_regsuite.migration.svg_series import SvgFormatError, parse_stat_svg
from legacy_plotting import _write_stat_plot


def _draw(tmp_path, s, cur, rs, ref, name="plot.svg"):
    out = tmp_path / name
    _write_stat_plot(s, cur, rs, ref, out, "Test", "rms_x", "m")
    return parse_stat_svg(out.read_text())


def _max_misfit(curve, xs, ys):
    """Worst distance of recovered points from the true curve, relative to its value range."""
    rng = max(ys) - min(ys)
    pts = [(x, y) for x, y in zip(curve.x, curve.y) if y is not None]
    return max(abs(y - np.interp(x, xs, ys)) for x, y in pts) / rng


def test_recovers_current_reference_and_difference(tmp_path):
    s = list(np.linspace(0.0, 2.0, 5000))
    cur = [2e-3 + 1e-3 * math.sin(3 * v) for v in s]
    ref = [2e-3 + 1.02e-3 * math.sin(3 * v) for v in s]
    plot = _draw(tmp_path, s, cur, s, ref)

    assert _max_misfit(plot.current, s, cur) < 1e-4
    assert _max_misfit(plot.reference, s, ref) < 1e-4
    assert abs(plot.current.last - cur[-1]) < 1e-6 * plot.y_span
    assert abs(plot.current.x[-1] - s[-1]) < 1e-6
    # matplotlib already simplified the path, so far fewer points than rows
    assert 2 < len(plot.current.x) < len(s)
    diff = [a - b for a, b in zip(cur, ref)]
    assert plot.difference is not None
    assert _max_misfit(plot.difference, s, diff) < 1e-4


def test_axis_with_offset_text(tmp_path):
    s = list(np.linspace(0.0, 1.0, 400))
    cur = [100.0 + 1e-6 * math.sin(5 * v) for v in s]
    plot = _draw(tmp_path, s, cur, s, cur)
    assert plot.y.has_offset
    assert _max_misfit(plot.current, s, cur) < 1e-4


def test_no_common_s_means_no_difference(tmp_path):
    s = [i * 0.01 for i in range(200)]
    rs = [v + 0.005 for v in s]
    y = [v * v for v in s]
    plot = _draw(tmp_path, s, y, rs, y)
    assert plot.difference is None
    assert plot.current is not None and plot.reference is not None


def test_nan_gap_becomes_none(tmp_path):
    s = [i * 0.01 for i in range(300)]
    cur = [math.cos(v) for v in s]
    cur[100:110] = [float("nan")] * 10
    ref = [math.cos(v) for v in s]
    plot = _draw(tmp_path, s, cur, s, ref)
    assert None in plot.current.y
    assert None not in plot.reference.y


def test_rejects_other_svgs():
    with pytest.raises(SvgFormatError):
        parse_stat_svg('<svg xmlns="http://www.w3.org/2000/svg"><g id="figure_1"></g></svg>')
