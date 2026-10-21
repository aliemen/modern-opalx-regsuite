"""Routing of branch names that contain ``/`` (e.g. ``v1-fix/decay-daughter-frame``).

Git branch names may contain slashes, and the data layout stores them as
nested directories (``runs-index/v1-fix/decay-daughter-frame/<arch>.json``).
The HTTP routes must therefore accept a multi-segment ``branch`` and still
dispatch to the right handler.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modern_opalx_regsuite.api import archive, integrity, results
from modern_opalx_regsuite.api.deps import get_config, require_auth

SLASHED = "v1-fix/decay-daughter-frame"
ARCH = "cuda-daint"


def _entry(branch: str, arch: str, run_id: str, *, archived: bool = False) -> dict:
    return {
        "branch": branch,
        "arch": arch,
        "run_id": run_id,
        "started_at": "2026-10-01T10:00:00Z",
        "finished_at": "2026-10-01T10:01:00Z",
        "status": "passed",
        "archived": archived,
        "public": False,
    }


def _seed(data_root: Path, branch: str, arch: str, run_ids: list[str]) -> None:
    branches_path = data_root / "branches.json"
    branches = (
        json.loads(branches_path.read_text()) if branches_path.is_file() else {}
    )
    branches.setdefault(branch, []).append(arch)
    branches_path.write_text(json.dumps(branches))
    idx = data_root / "runs-index" / branch / f"{arch}.json"
    idx.parent.mkdir(parents=True, exist_ok=True)
    idx.write_text(json.dumps([_entry(branch, arch, rid) for rid in run_ids]))
    for rid in run_ids:
        rdir = data_root / "runs" / branch / arch / rid
        rdir.mkdir(parents=True)
        (rdir / "run-meta.json").write_text(json.dumps(_entry(branch, arch, rid)))


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    _seed(tmp_path, SLASHED, ARCH, ["r1", "r2"])
    _seed(tmp_path, "master", ARCH, ["m1"])
    cfg = SimpleNamespace(resolved_data_root=tmp_path, resolved_archive_root=None)
    app = FastAPI()
    app.include_router(results.router)
    app.include_router(archive.router)
    app.include_router(integrity.router)
    app.dependency_overrides[get_config] = lambda: cfg
    app.dependency_overrides[require_auth] = lambda: "tester"
    return TestClient(app)


def _index(client: TestClient, branch: str) -> list[dict]:
    data_root = client.app.dependency_overrides[get_config]().resolved_data_root
    return json.loads((data_root / "runs-index" / branch / f"{ARCH}.json").read_text())


@pytest.mark.parametrize("branch_in_url", [SLASHED, quote(SLASHED, safe="")])
def test_list_runs_for_slashed_branch(client: TestClient, branch_in_url: str) -> None:
    r = client.get(f"/api/results/branches/{branch_in_url}/archs/{ARCH}/runs")
    assert r.status_code == 200
    assert [e["run_id"] for e in r.json()] == ["r1", "r2"]


def test_get_run_for_slashed_branch(client: TestClient) -> None:
    b = quote(SLASHED, safe="")
    r = client.get(f"/api/results/branches/{b}/archs/{ARCH}/runs/r1")
    assert r.status_code == 200
    assert r.json()["meta"]["run_id"] == "r1"
    r = client.get(f"/api/integrity/runs/{b}/{ARCH}/r1")
    assert r.status_code == 200


def test_archive_branch_with_slash(client: TestClient) -> None:
    r = client.post(f"/api/archive/branches/{quote(SLASHED, safe='')}")
    assert r.status_code == 200
    assert r.json()["changed"] == 2
    assert all(e["archived"] for e in _index(client, SLASHED))
    assert not any(e["archived"] for e in _index(client, "master"))


def test_arch_scope_route_is_not_swallowed_by_branch_scope(client: TestClient) -> None:
    """``/branches/master/archs/x`` must hit the arch handler, not archive a
    branch literally named ``master/archs/x``."""
    r = client.post(f"/api/archive/branches/master/archs/{ARCH}")
    assert r.status_code == 200
    assert r.json()["changed"] == 1
    assert all(e["archived"] for e in _index(client, "master"))


def test_archive_and_restore_runs_for_slashed_branch(client: TestClient) -> None:
    b = quote(SLASHED, safe="")
    r = client.post(f"/api/archive/branches/{b}/archs/{ARCH}/runs", json={"run_ids": ["r1"]})
    assert r.status_code == 200 and r.json()["changed"] == 1
    r = client.post(f"/api/archive/branches/{b}/archs/{ARCH}/runs/r1/restore")
    assert r.status_code == 200 and r.json()["changed"] == 1


@pytest.mark.parametrize(
    "bad", ["..", "../master", "a/../b", "a//b", "./a", "/abs", "a/"]
)
def test_traversal_like_branch_names_are_rejected(client: TestClient, bad: str) -> None:
    # 404 when the client normalizes a bare ``..`` away before sending, 422
    # when it reaches the BranchPath validator; never handled.
    r = client.get(f"/api/results/branches/{quote(bad, safe='')}/archs/{ARCH}/runs")
    assert r.status_code in (404, 422)
    r = client.post(f"/api/archive/branches/{quote(bad, safe='')}")
    assert r.status_code in (404, 422)
    assert not any(e["archived"] for e in _index(client, "master"))


def test_archive_summary_counts_slashed_branch(client: TestClient) -> None:
    client.post(f"/api/archive/branches/{quote(SLASHED, safe='')}")
    r = client.get("/api/results/archive-summary")
    assert r.status_code == 200
    assert r.json()["by_branch"] == {SLASHED: 2}
