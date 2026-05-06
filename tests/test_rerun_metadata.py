from __future__ import annotations

from modern_opalx_regsuite.data_model import RunIndexEntry, RunMeta


def test_legacy_run_meta_defaults_run_options() -> None:
    meta = RunMeta.model_validate(
        {
            "branch": "master",
            "arch": "cpu-serial",
            "run_id": "legacy",
            "started_at": "2026-04-01T00:00:00+00:00",
            "finished_at": "2026-04-01T00:01:00+00:00",
            "status": "passed",
        }
    )
    assert meta.run_options.skip_unit is False
    assert meta.run_options.skip_regression is False
    assert meta.run_options.clean_build is False
    assert meta.rerun_of is None


def test_run_index_entry_accepts_rerun_reference() -> None:
    entry = RunIndexEntry.model_validate(
        {
            "branch": "feature",
            "arch": "cpu-serial",
            "run_id": "rerun",
            "started_at": "2026-04-01T00:00:00+00:00",
            "finished_at": "2026-04-01T00:01:00+00:00",
            "status": "passed",
            "run_options": {
                "skip_unit": True,
                "skip_regression": False,
                "clean_build": True,
            },
            "rerun_of": {
                "branch": "master",
                "arch": "cpu-serial",
                "run_id": "source",
            },
        }
    )
    assert entry.run_options.skip_unit is True
    assert entry.run_options.clean_build is True
    assert entry.rerun_of is not None
    assert entry.rerun_of.run_id == "source"
