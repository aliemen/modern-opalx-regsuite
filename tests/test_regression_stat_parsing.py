from __future__ import annotations

import time
from pathlib import Path

from modern_opalx_regsuite.runner.parsing.regression import (
    _compute_delta,
    _read_stat_data,
)
from modern_opalx_regsuite.runner.plotting import _common_s_differences
from modern_opalx_regsuite.runner.regression_results import _build_simulation


def _stat_text(rows: list[tuple[float, float, float]]) -> str:
    body = "\n".join(f"{t} {s} {rms_s}" for t, s, rms_s in rows)
    return f"""SDDS1
&parameter name=revision, type=string, &end
&column name=t, units=s, type=double, &end
&column name=s, units=m, type=double, &end
&column name=rms_s, units=m, type=double, &end
&data mode=ascii, &end
OPAL-X git rev. #abcdef123456
{body}
"""


def _stat_without_time_text(rows: list[tuple[float, float]]) -> str:
    body = "\n".join(f"{s} {rms_s}" for s, rms_s in rows)
    return f"""SDDS1
&column name=s, units=m, type=double, &end
&column name=rms_s, units=m, type=double, &end
&data mode=ascii, &end
{body}
"""


def test_read_stat_data_skips_negative_time_emission_rows(tmp_path: Path) -> None:
    stat = tmp_path / "Dist-opalflattop.stat"
    stat.write_text(
        _stat_text(
            [
                (-2.0e-12, 0.0, 0.001),
                (-1.0e-12, 0.0, 0.002),
                (0.0, 0.0, 0.003),
                (1.0e-12, 0.1, 0.004),
            ]
        ),
        encoding="utf-8",
    )

    revision, s_vals, values, unit = _read_stat_data(stat, "rms_s")

    assert revision == "OPAL-X git rev. abcdef1"
    assert s_vals == [0.0, 0.1]
    assert values == [0.003, 0.004]
    assert unit == "m"


def test_read_stat_data_keeps_all_rows_without_time_column(tmp_path: Path) -> None:
    stat = tmp_path / "Legacy.stat"
    stat.write_text(
        _stat_without_time_text([(0.0, 0.001), (0.1, 0.002)]),
        encoding="utf-8",
    )

    _revision, s_vals, values, _unit = _read_stat_data(stat, "rms_s")

    assert s_vals == [0.0, 0.1]
    assert values == [0.001, 0.002]


def test_last_delta_ignores_series_length_difference() -> None:
    assert _compute_delta("last", [1.0, 2.0, 3.0], [0.0, 3.5]) == 0.5
    assert _compute_delta("avg", [1.0, 2.0, 3.0], [0.0, 3.5]) is None


def test_common_s_differences_use_matching_coordinates() -> None:
    s_vals = [0.0, 1.0, 2.0]
    values = [10.0, 20.0, 30.0]
    ref_s_vals = [0.0, 2.0]
    ref_values = [9.0, 25.0]

    diff_s, diffs = _common_s_differences(s_vals, values, ref_s_vals, ref_values)

    assert diff_s == [0.0, 2.0]
    assert diffs == [1.0, 5.0]


def test_build_simulation_warns_on_stat_sample_mismatch(tmp_path: Path) -> None:
    test_name = "Dist-opalflattop"
    work_dir = tmp_path / "work"
    reference_dir = tmp_path / "reference"
    plots_dir = tmp_path / "plots"
    log_path = tmp_path / "logs" / f"{test_name}-RT.log"
    work_dir.mkdir()
    reference_dir.mkdir()

    (tmp_path / f"{test_name}.rt").write_text(
        '"Flat top distribution."\nstat "rms_s" last 1E-12\n',
        encoding="utf-8",
    )
    (work_dir / f"{test_name}.stat").write_text(
        _stat_text(
            [
                (0.0, 0.0, 0.003),
                (1.0e-12, 0.1, 0.004),
                (2.0e-12, 0.2, 0.005),
            ]
        ),
        encoding="utf-8",
    )
    (reference_dir / f"{test_name}.stat").write_text(
        _stat_text(
            [
                (0.0, 0.0, 0.003),
                (2.0e-12, 0.2, 0.004),
            ]
        ),
        encoding="utf-8",
    )

    sim = _build_simulation(
        test_name=test_name,
        rc=0,
        rt_file=tmp_path / f"{test_name}.rt",
        work_test_dir=work_dir,
        reference_dir=reference_dir,
        plots_dir=plots_dir,
        pipeline_log_path=tmp_path / "pipeline.log",
        test_start=time.monotonic(),
        log_path=log_path,
    )

    metric = sim.containers[0].metrics[0]
    assert metric.delta is not None
    assert abs(metric.delta - 0.001) < 1e-15
    warning = log_path.read_text(encoding="utf-8")
    assert "WARNING" in warning
    assert "stat sample grid mismatch" in warning
    assert "current samples=3, reference samples=2" in warning
    assert "common s samples=2" in warning


def test_build_simulation_compares_nonnegative_time_rows(tmp_path: Path) -> None:
    test_name = "Dist-opalflattop"
    work_dir = tmp_path / "work"
    reference_dir = tmp_path / "reference"
    plots_dir = tmp_path / "plots"
    work_dir.mkdir()
    reference_dir.mkdir()

    (tmp_path / f"{test_name}.rt").write_text(
        '"Flat top distribution."\nstat "rms_s" avg 1E-12\n',
        encoding="utf-8",
    )
    (work_dir / f"{test_name}.stat").write_text(
        _stat_text(
            [
                (-2.0e-12, 0.0, 0.001),
                (-1.0e-12, 0.0, 0.002),
                (0.0, 0.0, 0.003),
            ]
        ),
        encoding="utf-8",
    )
    (reference_dir / f"{test_name}.stat").write_text(
        _stat_text([(0.0, 0.0, 0.003)]),
        encoding="utf-8",
    )

    sim = _build_simulation(
        test_name=test_name,
        rc=0,
        rt_file=tmp_path / f"{test_name}.rt",
        work_test_dir=work_dir,
        reference_dir=reference_dir,
        plots_dir=plots_dir,
        pipeline_log_path=tmp_path / "pipeline.log",
        test_start=time.monotonic(),
    )

    metric = sim.containers[0].metrics[0]
    assert metric.state == "passed"
    assert metric.delta == 0.0
    assert metric.current_value == 0.003
    assert metric.reference_value == 0.003
