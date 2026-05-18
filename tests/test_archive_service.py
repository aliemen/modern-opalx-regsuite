from __future__ import annotations

import json
from pathlib import Path

from modern_opalx_regsuite.archive_service import (
    hard_delete_arch_archived,
    hard_delete_runs,
    set_archived_for_arch,
    set_archived_for_branch,
)


def _entry(branch: str, arch: str, run_id: str, *, archived: bool = False) -> dict:
    return {
        "branch": branch,
        "arch": arch,
        "run_id": run_id,
        "started_at": "2026-05-18T10:00:00Z",
        "finished_at": "2026-05-18T10:01:00Z",
        "status": "passed",
        "regtest_branch": "master",
        "unit_tests_total": 1,
        "unit_tests_failed": 0,
        "regression_total": 1,
        "regression_passed": 1,
        "regression_failed": 0,
        "regression_broken": 0,
        "archived": archived,
        "public": False,
    }


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_run(
    data_root: Path, branch: str, arch: str, run_id: str, *, archived: bool = False
) -> None:
    run_root = data_root / "runs" / branch / arch / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    _write_json(run_root / "run-meta.json", _entry(branch, arch, run_id, archived=archived))


def _write_cell(
    data_root: Path,
    branch: str,
    arch: str,
    run_ids: list[str],
    *,
    archived_ids: set[str] | None = None,
) -> None:
    archived_ids = archived_ids or set()
    for run_id in run_ids:
        _write_run(data_root, branch, arch, run_id, archived=run_id in archived_ids)
    entries = [
        _entry(branch, arch, run_id, archived=run_id in archived_ids)
        for run_id in run_ids
    ]
    _write_json(data_root / "runs-index" / branch / f"{arch}.json", entries)


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_branch_archive_allows_master_and_updates_index_and_metadata(
    tmp_path: Path,
) -> None:
    _write_json(tmp_path / "branches.json", {"master": ["cpu-serial", "gpu"]})
    _write_cell(tmp_path, "master", "cpu-serial", ["cpu-run"])
    _write_cell(tmp_path, "master", "gpu", ["gpu-run"])

    result = set_archived_for_branch(tmp_path, "master", archived=True)

    assert result.changed == 2
    assert result.skipped_active == []
    for arch, run_id in (("cpu-serial", "cpu-run"), ("gpu", "gpu-run")):
        entries = _read_json(tmp_path / "runs-index" / "master" / f"{arch}.json")
        assert entries[0]["archived"] is True
        meta = _read_json(tmp_path / "runs" / "master" / arch / run_id / "run-meta.json")
        assert meta["archived"] is True


def test_arch_archive_still_skips_protected_run_ids_on_master(tmp_path: Path) -> None:
    _write_json(tmp_path / "branches.json", {"master": ["cpu-serial"]})
    _write_cell(tmp_path, "master", "cpu-serial", ["ready-run", "running-run"])

    result = set_archived_for_arch(
        tmp_path,
        "master",
        "cpu-serial",
        archived=True,
        protect_run_ids=["running-run"],
    )

    assert result.changed == 1
    assert result.skipped_active == ["running-run"]
    entries = _read_json(tmp_path / "runs-index" / "master" / "cpu-serial.json")
    archived_by_id = {entry["run_id"]: entry["archived"] for entry in entries}
    assert archived_by_id == {"ready-run": True, "running-run": False}
    protected_meta = _read_json(
        tmp_path / "runs" / "master" / "cpu-serial" / "running-run" / "run-meta.json"
    )
    assert protected_meta["archived"] is False


def test_archive_tab_hard_delete_allows_archived_master_cells(tmp_path: Path) -> None:
    _write_json(tmp_path / "branches.json", {"master": ["cpu-serial"]})
    _write_cell(
        tmp_path,
        "master",
        "cpu-serial",
        ["archived-run", "active-run"],
        archived_ids={"archived-run"},
    )

    result = hard_delete_arch_archived(tmp_path, "master", "cpu-serial")

    assert result.changed == 1
    assert not (tmp_path / "runs" / "master" / "cpu-serial" / "archived-run").exists()
    assert (tmp_path / "runs" / "master" / "cpu-serial" / "active-run").is_dir()
    entries = _read_json(tmp_path / "runs-index" / "master" / "cpu-serial.json")
    assert [entry["run_id"] for entry in entries] == ["active-run"]


def test_explicit_hard_delete_allows_archived_master_runs(tmp_path: Path) -> None:
    _write_json(tmp_path / "branches.json", {"master": ["cpu-serial"]})
    _write_cell(
        tmp_path,
        "master",
        "cpu-serial",
        ["archived-run", "other-run"],
        archived_ids={"archived-run", "other-run"},
    )

    result = hard_delete_runs(tmp_path, "master", "cpu-serial", ["archived-run"])

    assert result.changed == 1
    assert result.not_found == []
    assert not (tmp_path / "runs" / "master" / "cpu-serial" / "archived-run").exists()
    assert (tmp_path / "runs" / "master" / "cpu-serial" / "other-run").is_dir()
    entries = _read_json(tmp_path / "runs-index" / "master" / "cpu-serial.json")
    assert [entry["run_id"] for entry in entries] == ["other-run"]
