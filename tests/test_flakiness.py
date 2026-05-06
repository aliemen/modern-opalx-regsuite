from __future__ import annotations

import json
from pathlib import Path

from modern_opalx_regsuite.flakiness import compute_flakiness


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)


def _run(data_root: Path, run_id: str, state: str, started: str) -> dict:
    branch = "master"
    arch = "cpu-serial"
    root = data_root / "runs" / branch / arch / run_id
    _write_json(
        root / "run-meta.json",
        {
            "branch": branch,
            "arch": arch,
            "run_id": run_id,
            "started_at": started,
            "finished_at": started,
            "status": "failed" if state != "passed" else "passed",
            "regtest_branch": "master",
        },
    )
    _write_json(
        root / "unit-tests.json",
        {"tests": []},
    )
    _write_json(
        root / "regression-tests.json",
        {
            "simulations": [
                {
                    "name": "SometimesBad",
                    "state": state,
                    "containers": [
                        {
                            "id": None,
                            "state": state,
                            "metrics": [
                                {
                                    "metric": "suite",
                                    "mode": "aggregate",
                                    "state": state,
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    )
    return {
        "branch": branch,
        "arch": arch,
        "run_id": run_id,
        "started_at": started,
        "finished_at": started,
        "status": "failed" if state != "passed" else "passed",
        "regtest_branch": "master",
    }


def test_flakiness_requires_mixed_outcomes_in_same_context(tmp_path: Path) -> None:
    entries = [
        _run(tmp_path, "r3", "passed", "2026-04-03T00:00:00+00:00"),
        _run(tmp_path, "r2", "failed", "2026-04-02T00:00:00+00:00"),
        _run(tmp_path, "r1", "passed", "2026-04-01T00:00:00+00:00"),
    ]
    entries.sort(key=lambda e: e["started_at"], reverse=True)
    _write_json(tmp_path / "branches.json", {"master": ["cpu-serial"]})
    _write_json(tmp_path / "runs-index" / "master" / "cpu-serial.json", entries)

    report = compute_flakiness(
        tmp_path,
        "master",
        "cpu-serial",
        "master",
        limit=20,
        min_observations=3,
    )

    assert report.runs_considered == 3
    assert [sim.name for sim in report.simulations] == ["SometimesBad"]
    assert report.simulations[0].passed == 2
    assert report.simulations[0].failed == 1
