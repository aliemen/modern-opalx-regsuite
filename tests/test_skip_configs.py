from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from modern_opalx_regsuite.config import SuiteConfig
from modern_opalx_regsuite.data_model import (
    RegressionSimulation,
    RegressionTestsReport,
    RunIndexEntry,
    RunMeta,
    SkipConfigSnapshot,
    UnitTestCase,
    UnitTestsReport,
)
from modern_opalx_regsuite.skip_configs import (
    SkipConfigInput,
    create_skip_config,
    ctest_command_with_excludes,
    delete_skip_config,
    load_skip_configs,
    skip_config_snapshot,
    skip_configs_path,
    update_skip_config,
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



def _cfg(tmp_path: Path) -> SuiteConfig:
    return SuiteConfig(
        opalx_repo_root=tmp_path / "opalx",
        builds_root=tmp_path / "builds",
        data_root=tmp_path / "data",
        users_root=tmp_path / "users",
        regtests_repo_root=tmp_path / "regtests",
    )


def test_input_normalizes_and_validates_test_names() -> None:
    body = SkipConfigInput(
        name="  Slow on CPU ",
        regression_tests=[" DBA-COF-Gauss", "", "DBA-COF-Gauss", "AWAGun-1"],
        unit_tests=["TestOrbitThreader"],
    )
    assert body.name == "Slow on CPU"
    assert body.regression_tests == ["AWAGun-1", "DBA-COF-Gauss"]
    with pytest.raises(ValidationError):
        SkipConfigInput(name="bad", unit_tests=["Test Orbit; rm -rf /"])
    with pytest.raises(ValidationError):
        SkipConfigInput(name="   ")


def test_store_create_update_delete_and_snapshot(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    created = create_skip_config(
        cfg, SkipConfigInput(name="Slow on CPU", regression_tests=["DBA-COF-Gauss"])
    )
    assert created.id == "Slow-on-CPU"
    assert skip_configs_path(cfg).is_file()

    second = create_skip_config(cfg, SkipConfigInput(name="Slow-on-CPU"))
    assert second.id == "Slow-on-CPU-2"

    with pytest.raises(ValueError):
        create_skip_config(cfg, SkipConfigInput(name="slow on cpu"))

    updated = update_skip_config(
        cfg,
        created.id,
        SkipConfigInput(name="Slow on CPU", unit_tests=["TestOrbitThreader"]),
    )
    assert updated.unit_tests == ["TestOrbitThreader"]
    assert updated.regression_tests == []

    snap = skip_config_snapshot(cfg, created.id)
    assert snap.name == "Slow on CPU"
    assert snap.unit_tests == ["TestOrbitThreader"]

    with pytest.raises(KeyError):
        update_skip_config(cfg, "missing", SkipConfigInput(name="x"))
    with pytest.raises(KeyError):
        skip_config_snapshot(cfg, "missing")

    assert delete_skip_config(cfg, second.id) is True
    assert delete_skip_config(cfg, second.id) is False
    assert [c.id for c in load_skip_configs(cfg).configs] == ["Slow-on-CPU"]


def test_corrupt_store_file_loads_as_empty(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    path = skip_configs_path(cfg)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert load_skip_configs(cfg).configs == []


def test_ctest_excludes_are_anchored_escaped_and_quoted() -> None:
    cmd = ctest_command_with_excludes(
        "ctest --output-on-failure", ["TestOrbitThreader", "Test.Scaling+FFA"]
    )
    assert cmd == (
        "ctest --output-on-failure -E "
        "'^(TestOrbitThreader|Test\\.Scaling\\+FFA)$'"
    )


def test_ctest_excludes_merge_existing_exclude_regex() -> None:
    cmd = ctest_command_with_excludes("ctest -E Slow --output-on-failure", ["TestA"])
    assert cmd == "ctest -E '(Slow)|^(TestA)$' --output-on-failure"


def test_ctest_excludes_return_none_for_non_ctest_commands() -> None:
    assert ctest_command_with_excludes("FOO=1 ctest", ["TestA"]) is None
    assert ctest_command_with_excludes("cd build && ctest", ["TestA"]) is None
    assert ctest_command_with_excludes("./run-unit.sh", ["TestA"]) is None
    assert ctest_command_with_excludes("/usr/bin/ctest", ["TestA"]) == (
        "/usr/bin/ctest -E '^(TestA)$'"
    )
    assert ctest_command_with_excludes("./run-unit.sh", []) == "./run-unit.sh"
