from __future__ import annotations

from modern_opalx_regsuite.data_model import (
    RegressionSimulation,
    RegressionTestsReport,
    RunIndexEntry,
    RunMeta,
    SkipConfigSnapshot,
    UnitTestCase,
    UnitTestsReport,
)


def test_unit_report_total_excludes_skipped_cases() -> None:
    report = UnitTestsReport(
        tests=[
            UnitTestCase(name="TestFast", status="passed"),
            UnitTestCase(name="TestBroken", status="failed"),
            UnitTestCase(name="TestOrbitThreader", status="skipped"),
        ]
    )
    assert report.total == 2
    assert report.failed == 1
    assert report.skipped == 1


def test_regression_report_counts_skipped_simulations() -> None:
    report = RegressionTestsReport(
        simulations=[
            RegressionSimulation(name="FodoCell", state="passed"),
            RegressionSimulation(name="DBA-COF-Gauss", state="skipped"),
        ]
    )
    assert report.skipped == 1
    assert report.total == 0  # metric-based; skipped sims carry no metrics


def test_legacy_meta_and_index_entries_default_skip_fields() -> None:
    legacy = {
        "branch": "master",
        "arch": "cpu-serial",
        "run_id": "old",
        "started_at": "2026-04-01T00:00:00",
        "finished_at": None,
        "status": "passed",
        "run_options": {"skip_unit": False, "skip_regression": False},
    }
    meta = RunMeta.model_validate(legacy)
    entry = RunIndexEntry.model_validate(legacy)
    assert meta.unit_tests_skipped == 0
    assert meta.regression_skipped == 0
    assert meta.run_options.skip_config is None
    assert entry.regression_skipped == 0


def test_run_options_round_trip_skip_snapshot() -> None:
    snapshot = SkipConfigSnapshot(
        id="slow-cpu",
        name="Slow on CPU",
        unit_tests=["TestOrbitThreader"],
        regression_tests=["DBA-COF-Gauss"],
    )
    meta = RunMeta.model_validate(
        {
            "branch": "master",
            "arch": "cpu-serial",
            "run_id": "r1",
            "started_at": "2026-10-14T00:00:00+00:00",
            "run_options": {"skip_config": snapshot.model_dump()},
        }
    )
    assert meta.run_options.skip_config == snapshot
