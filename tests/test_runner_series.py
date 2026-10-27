"""The runner writes series.json.gz instead of SVGs."""
from __future__ import annotations

import math
import time
from pathlib import Path

from modern_opalx_regsuite import series
from modern_opalx_regsuite.runner.regression_results import _build_simulation


def _stat(rows: list[tuple[float, float, float]]) -> str:
    body = "\n".join(f"{s} {rms_x} {energy}" for s, rms_x, energy in rows)
    return f"""SDDS1
&column name=s, units=m, type=double, &end
&column name=rms_x, units=m, type=double, &end
&column name=energy, units=MeV, type=double, &end
&data mode=ascii, &end
{body}
"""


def _simulation(tmp_path: Path, cur_rows, ref_rows, *, writer, name="Drift"):
    work, ref = tmp_path / "work", tmp_path / "reference"
    work.mkdir(exist_ok=True)
    ref.mkdir(exist_ok=True)
    (tmp_path / f"{name}.rt").write_text(
        f'"{name}"\nstat "rms_x" last 1E-6\nstat "energy" avg 1E-3\n', encoding="utf-8"
    )
    (work / f"{name}.stat").write_text(_stat(cur_rows), encoding="utf-8")
    (ref / f"{name}.stat").write_text(_stat(ref_rows), encoding="utf-8")
    return _build_simulation(
        test_name=name, rc=0, rt_file=tmp_path / f"{name}.rt", work_test_dir=work,
        reference_dir=ref, plots_dir=tmp_path / "plots", pipeline_log_path=tmp_path / "pipeline.log",
        test_start=time.monotonic(), log_path=tmp_path / f"{name}-RT.log", series=writer,
    )


def test_build_simulation_writes_thinned_series_and_no_svgs(tmp_path):
    rows = [(i * 1e-3, 1e-3 + 1e-4 * math.sin(i / 50), 100.0 + i * 1e-4) for i in range(3000)]
    ref_rows = [(s, x * 1.001, e) for s, x, e in rows]
    ref_rows[1500] = (ref_rows[1500][0], ref_rows[1500][1] + 1e-2, ref_rows[1500][2])  # one-row spike
    writer = series.RunSeriesWriter(tmp_path / series.SERIES_FILE, max_points=100)
    sim = _simulation(tmp_path, rows, ref_rows, writer=writer)

    metrics = {m.metric: m for m in sim.containers[0].metrics}
    assert all(m.series and m.plot is None for m in metrics.values())
    assert metrics["energy"].unit == "MeV"
    assert not (tmp_path / "plots").exists() or not list((tmp_path / "plots").glob("*.svg"))

    doc = series.read_series(tmp_path / series.SERIES_FILE)
    assert doc["source"] == "runner" and doc["max_points"] == 100
    c = doc["sims"]["Drift"]["_"]
    assert len(c["s"]) <= 100 and c["s"] == c["rs"]
    rms = c["m"]["rms_x"]
    assert len(rms["cur"]) == len(c["s"]) and rms["cur"][-1] == rows[-1][1]
    # the spike in the difference survives the reduction to 100 points
    assert min(rms["d"]["v"]) < -9e-3
    assert len(rms["d"]["s"]) <= 100


def test_zero_max_points_keeps_all_rows(tmp_path):
    rows = [(i * 0.01, float(i), 1.0) for i in range(500)]
    writer = series.RunSeriesWriter(tmp_path / series.SERIES_FILE, max_points=0)
    _simulation(tmp_path, rows, rows, writer=writer)
    c = series.read_series(tmp_path / series.SERIES_FILE)["sims"]["Drift"]["_"]
    assert len(c["s"]) == 500 and len(c["m"]["rms_x"]["d"]["v"]) == 500


def test_series_file_grows_per_simulation(tmp_path):
    rows = [(i * 0.1, float(i), 1.0) for i in range(20)]
    writer = series.RunSeriesWriter(tmp_path / series.SERIES_FILE, max_points=100)
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    _simulation(tmp_path / "a", rows, rows, writer=writer, name="First")
    assert set(series.read_series(tmp_path / series.SERIES_FILE)["sims"]) == {"First"}
    _simulation(tmp_path / "b", rows, rows, writer=writer, name="Second")
    assert set(series.read_series(tmp_path / series.SERIES_FILE)["sims"]) == {"First", "Second"}


def test_metric_with_its_own_grid_gets_per_metric_x(tmp_path):
    w = series.RunSeriesWriter(tmp_path / series.SERIES_FILE, max_points=10)
    w.add("T", None, "a", [0.0, 1.0, 2.0], [1.0, 2.0, 3.0], [0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    w.add("T", None, "b", [0.0, 0.5], [5.0, 6.0], [0.0, 0.5], [5.0, float("nan")])
    w.flush("T")
    c = series.read_series(tmp_path / series.SERIES_FILE)["sims"]["T"]["_"]
    assert c["s"] == [0.0, 1.0, 2.0] and "s" not in c["m"]["a"]
    assert c["m"]["b"]["s"] == [0.0, 0.5] and c["m"]["b"]["ref"] == [5.0, None]
