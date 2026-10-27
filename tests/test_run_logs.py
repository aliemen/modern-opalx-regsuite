"""Gzipped run logs: post-run compression, reading, serving, integrity, series endpoint."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modern_opalx_regsuite import series
from modern_opalx_regsuite.api import results
from modern_opalx_regsuite.api.app import RunDataFiles
from modern_opalx_regsuite.api.deps import get_config, require_auth
from modern_opalx_regsuite.artifacts import MANIFEST_NAME, check_run_integrity
from modern_opalx_regsuite.run_logs import finalize_run_files, gzip_log, read_log_text


def _run(root: Path, branch="master", arch="cpu-serial", run_id="r1") -> Path:
    run = root / "runs" / branch / arch / run_id
    (run / "logs").mkdir(parents=True)
    (run / "logs" / "pipeline.log").write_text("== PHASE: done status=passed ==\ncleanup\n")
    (run / "logs" / "Drift-RT.log").write_text("x" * 10_000)
    meta = {"branch": branch, "arch": arch, "run_id": run_id, "started_at": "2026-10-27T10:00:00Z",
            "status": "passed"}
    (run / "run-meta.json").write_text(json.dumps(meta))
    (run / "unit-tests.json").write_text(json.dumps({"tests": []}))
    reg = {"simulations": [{"name": "Drift", "log_file": "logs/Drift-RT.log", "containers": [
        {"id": None, "metrics": [{"metric": "rms_x", "mode": "last", "state": "passed", "series": True}]}]}]}
    (run / "regression-tests.json").write_text(json.dumps(reg))
    series.write_series(run / series.SERIES_FILE, {"Drift": {}}, source="runner", max_points=100)
    return run


def test_gzip_log_roundtrip_and_append_after_gzip(tmp_path):
    log = tmp_path / "pipeline.log"
    log.write_text("first\n")
    assert gzip_log(log)
    assert not log.exists() and read_log_text(log) == "first\n"
    log.write_text("late line\n")  # something appended after the gzip
    assert gzip_log(log)
    assert read_log_text(log) == "first\nlate line\n"
    assert not gzip_log(log)  # nothing plain left
    assert [p.name for p in tmp_path.iterdir()] == ["pipeline.log.gz"]


def test_finalize_gzips_logs_and_manifest_lists_them(tmp_path):
    run = _run(tmp_path)
    finalize_run_files(run)
    assert sorted(p.name for p in (run / "logs").iterdir()) == ["Drift-RT.log.gz", "pipeline.log.gz"]
    manifest = json.loads((run / MANIFEST_NAME).read_text())
    paths = {f["path"]: f["kind"] for f in manifest["files"]}
    assert paths["logs/pipeline.log.gz"] == "log" and paths[series.SERIES_FILE] == "plot"
    report = check_run_integrity(run)
    assert report.status == "ok", report.issues


def test_integrity_flags_missing_series_file(tmp_path):
    run = _run(tmp_path)
    (run / series.SERIES_FILE).unlink()
    finalize_run_files(run)
    codes = {(i.code, i.path) for i in check_run_integrity(run).issues}
    assert ("referenced-artifact-missing", series.SERIES_FILE) in codes


def test_data_mount_serves_gzipped_log_as_text(tmp_path):
    run = _run(tmp_path)
    finalize_run_files(run)
    (tmp_path / "plain.log").write_text("still plain\n")
    app = FastAPI()
    app.mount("/data", RunDataFiles(directory=str(tmp_path)), name="data")
    client = TestClient(app)

    r = client.get("/data/runs/master/cpu-serial/r1/logs/pipeline.log")
    assert r.status_code == 200
    assert r.headers["content-encoding"] == "gzip"
    assert r.headers["content-type"].startswith("text/plain")
    assert r.text == "== PHASE: done status=passed ==\ncleanup\n"  # client undid the encoding
    assert client.get("/data/plain.log").text == "still plain\n"
    assert client.get("/data/runs/master/cpu-serial/r1/logs/missing.log").status_code == 404
    assert client.get("/data/../etc/passwd.log").status_code == 404


@pytest.fixture
def api(tmp_path):
    def make(archived=False, archive_root=None):
        _run(tmp_path)
        idx = tmp_path / "runs-index" / "master" / "cpu-serial.json"
        idx.parent.mkdir(parents=True, exist_ok=True)
        idx.write_text(json.dumps([{"branch": "master", "arch": "cpu-serial", "run_id": "r1",
                                    "started_at": "2026-10-27T10:00:00Z", "finished_at": None,
                                    "status": "passed", "archived": archived}]))
        cfg = SimpleNamespace(resolved_data_root=tmp_path, resolved_archive_root=archive_root)
        app = FastAPI()
        app.include_router(results.router)
        app.dependency_overrides[get_config] = lambda: cfg
        app.dependency_overrides[require_auth] = lambda: "tester"
        return TestClient(app)
    return make


def test_series_endpoint_serves_gzip_encoded_json(api):
    client = api()
    r = client.get("/api/results/branches/master/archs/cpu-serial/runs/r1/series")
    assert r.status_code == 200
    assert r.headers["content-encoding"] == "gzip"
    assert r.json()["sims"] == {"Drift": {}}
    assert client.get("/api/results/branches/master/archs/cpu-serial/runs/nope/series").status_code == 404


def test_series_endpoint_hides_cold_stored_runs(api, tmp_path):
    client = api(archived=True, archive_root=tmp_path / "archive")
    assert client.get("/api/results/branches/master/archs/cpu-serial/runs/r1/series").status_code == 404


def test_series_endpoint_requires_auth(tmp_path):
    cfg = SimpleNamespace(resolved_data_root=tmp_path, resolved_archive_root=None)
    app = FastAPI()
    app.include_router(results.router)
    app.dependency_overrides[get_config] = lambda: cfg
    r = TestClient(app).get("/api/results/branches/master/archs/cpu-serial/runs/r1/series")
    assert r.status_code == 401


def test_read_log_text_reads_plain_or_gzip(tmp_path):
    p = tmp_path / "a.log"
    with gzip.open(tmp_path / "a.log.gz", "wb") as f:
        f.write("ü gz\n".encode())
    assert read_log_text(p) == "ü gz\n"
    p.write_text("plain\n")
    assert read_log_text(p) == "plain\n"
    with pytest.raises(FileNotFoundError):
        read_log_text(tmp_path / "none.log")
