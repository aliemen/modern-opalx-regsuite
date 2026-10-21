"""Dashboard data sources: ``GET /api/results/latest-matrix`` and the queue snapshot."""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modern_opalx_regsuite.api import results, state
from modern_opalx_regsuite.api.deps import get_config, require_auth
from modern_opalx_regsuite.data_model import (
    BuildPresetSnapshot,
    ExecutionSnapshot,
    MachinePresetSnapshot,
)


def _entry(branch: str, arch: str, run_id: str, started: str, *, archived: bool = False) -> dict:
    return {
        "branch": branch,
        "arch": arch,
        "run_id": run_id,
        "started_at": started,
        "finished_at": started,
        "status": "passed",
        "archived": archived,
    }


def _seed(data_root: Path, index: dict[str, dict[str, list[dict]]]) -> None:
    (data_root / "branches.json").write_text(
        json.dumps({b: list(archs) for b, archs in index.items()})
    )
    for branch, archs in index.items():
        for arch, entries in archs.items():
            idx = data_root / "runs-index" / branch / f"{arch}.json"
            idx.parent.mkdir(parents=True, exist_ok=True)
            idx.write_text(json.dumps(entries))


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    _seed(
        tmp_path,
        {
            "master": {
                # Deliberately oldest-first: the endpoint must not rely on order.
                "cpu-serial": [
                    _entry("master", "cpu-serial", "m-old", "2026-10-01T10:00:00Z"),
                    _entry("master", "cpu-serial", "m-new", "2026-10-03T10:00:00Z"),
                ],
                "cuda-daint": [
                    _entry("master", "cuda-daint", "m-arch", "2026-10-02T10:00:00Z", archived=True),
                ],
            },
            "fix/slashed": {
                "cpu-serial": [_entry("fix/slashed", "cpu-serial", "s1", "2026-10-04T10:00:00Z")],
            },
            "gone": {
                "cpu-serial": [_entry("gone", "cpu-serial", "g1", "2026-09-01T10:00:00Z", archived=True)],
            },
        },
    )
    app = FastAPI()
    app.include_router(results.router)
    app.dependency_overrides[get_config] = lambda: SimpleNamespace(resolved_data_root=tmp_path)
    app.dependency_overrides[require_auth] = lambda: "tester"
    return TestClient(app)


def _rows(client: TestClient, view: str) -> dict[str, dict]:
    r = client.get("/api/results/latest-matrix", params={"view": view})
    assert r.status_code == 200
    return {row["branch"]: row for row in r.json()["rows"]}


def test_active_matrix_picks_newest_and_omits_archived(client: TestClient) -> None:
    rows = _rows(client, "active")
    assert set(rows) == {"master", "fix/slashed"}  # "gone" has only archived runs
    master = rows["master"]
    assert set(master["cells"]) == {"cpu-serial"}  # archived-only cell omitted
    assert master["cells"]["cpu-serial"]["run"]["run_id"] == "m-new"
    assert master["cells"]["cpu-serial"]["run_count"] == 2
    assert master["last_activity"].startswith("2026-10-03")
    assert rows["fix/slashed"]["cells"]["cpu-serial"]["run"]["run_id"] == "s1"


def test_all_view_includes_archived_cells(client: TestClient) -> None:
    rows = _rows(client, "all")
    assert set(rows) == {"master", "fix/slashed", "gone"}
    assert rows["master"]["cells"]["cuda-daint"]["run"]["run_id"] == "m-arch"


def test_queue_snapshot_exposes_user_and_preset_names(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = ExecutionSnapshot(
        build=BuildPresetSnapshot(id="b", name="CUDA Release"),
        machine=MachinePresetSnapshot(id="m", name="Daint", kind="ssh"),
    )
    active = state.ActiveRun(
        run_id="r1", branch="master", arch="cuda-daint", machine_id="daint",
        connection_name="daint", triggered_by="alice", execution_snapshot=snapshot,
    )
    queued = state.QueuedRun(
        queue_id="q1", run_id="r2", branch="fix/x", arch="cpu-serial",
        machine_id="daint", connection_name="daint", triggered_by="",
    )
    monkeypatch.setattr(
        state,
        "_machines",
        {"daint": state.MachineQueue(machine_id="daint", active_run=active, queue=deque([queued]))},
    )

    [machine] = state.get_queue_snapshot()
    assert machine["active_run"]["triggered_by"] == "alice"
    assert machine["active_run"]["build_name"] == "CUDA Release"
    assert machine["active_run"]["machine_name"] == "Daint"
    [q] = machine["queue"]
    assert q["triggered_by"] is None  # empty username normalised to None
    assert q["build_name"] is None and q["machine_name"] is None
