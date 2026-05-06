from __future__ import annotations

import shutil
from pathlib import Path

from modern_opalx_regsuite.artifacts import check_run_integrity, write_artifact_manifest


ROOT = Path(__file__).resolve().parents[1]


def test_demo_pass_integrity_ok() -> None:
    report = check_run_integrity(ROOT / "demo-data/runs/master/cpu-serial/demo-pass")
    assert report.status == "ok"
    assert report.issues == []
    assert report.manifest is not None


def test_demo_corrupt_integrity_errors() -> None:
    report = check_run_integrity(
        ROOT / "demo-data/runs/demo-corrupt/cpu-serial/demo-corrupt"
    )
    assert report.status == "error"
    codes = {issue.code for issue in report.issues}
    assert "json-invalid" in codes
    assert "required-file-missing" in codes


def test_rebuild_manifest_repairs_missing_manifest(tmp_path: Path) -> None:
    src = ROOT / "demo-data/runs/master/cpu-serial/demo-pass"
    dst = tmp_path / "run"
    shutil.copytree(src, dst)
    (dst / "artifact-manifest.json").unlink()

    before = check_run_integrity(dst)
    assert before.status == "warning"
    assert any(issue.code == "manifest-missing" for issue in before.issues)

    manifest = write_artifact_manifest(dst)
    assert manifest.files

    after = check_run_integrity(dst)
    assert after.status == "ok"
