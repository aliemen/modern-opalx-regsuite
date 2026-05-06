#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modern_opalx_regsuite.artifacts import write_artifact_manifest
from modern_opalx_regsuite.data_model import (
    RegressionTestsReport,
    RunIndexEntry,
    RunMeta,
    UnitTestsReport,
)


SOURCE_RUNS = [
    (
        "master",
        "cpu-serial",
        "20260428-152941",
        "demo-pass",
        ["Dist-fromfile", "FodoCell-multibeam-fromfile"],
    ),
    (
        "master",
        "cpu-serial",
        "20260426-090645",
        "demo-fail",
        ["Dist-flattop", "FodoCell-multibeam-fromfile"],
    ),
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _production_root() -> Path:
    return _repo_root().parent / "opalx-regsuite-test-data"


def _clean_text(text: str) -> str:
    replacements = {
        "aliemen": "demo-user",
        "opalx": "demo-user",
        "merlin6-gwendolen": "demo-remote",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _copy_text_file(src: Path, dst: Path, *, max_chars: int = 8000) -> None:
    if not src.is_file():
        return
    text = src.read_text(encoding="utf-8", errors="replace")
    if len(text) > max_chars:
        text = text[:max_chars] + "\n[demo-data] log truncated\n"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(_clean_text(text), encoding="utf-8")


def _copy_binary_file(src: Path, dst: Path) -> None:
    if not src.is_file():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _referenced_files(report: RegressionTestsReport) -> set[str]:
    refs: set[str] = {"logs/pipeline.log"}
    for sim in report.simulations:
        for value in (sim.log_file, sim.beamline_plot, sim.beamline_3d_data):
            if value:
                refs.add(value)
        for container in sim.containers:
            for metric in container.metrics:
                if metric.plot:
                    refs.add(metric.plot)
    return refs


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)


def _build_run(
    source_root: Path,
    target_root: Path,
    branch: str,
    arch: str,
    run_id: str,
    demo_run_id: str,
    keep_sims: list[str],
) -> RunIndexEntry:
    src = source_root / "runs" / branch / arch / run_id
    dst = target_root / "runs" / branch / arch / demo_run_id
    dst.mkdir(parents=True, exist_ok=True)

    meta = RunMeta.model_validate(json.loads((src / "run-meta.json").read_text()))
    unit = UnitTestsReport.model_validate(json.loads((src / "unit-tests.json").read_text()))
    regression = RegressionTestsReport.model_validate(
        json.loads((src / "regression-tests.json").read_text())
    )

    unit.tests = unit.tests[:5]
    regression.simulations = [
        sim for sim in regression.simulations if sim.name in set(keep_sims)
    ]

    meta.run_id = demo_run_id
    meta.triggered_by = "demo-user"
    meta.connection_name = "local"
    meta.public = False
    meta.unit_tests_total = unit.total
    meta.unit_tests_failed = unit.failed
    meta.regression_total = regression.total
    meta.regression_passed = regression.passed
    meta.regression_failed = regression.failed
    meta.regression_broken = regression.broken
    meta.status = "failed" if regression.failed or regression.broken else "passed"

    _write_json(dst / "run-meta.json", meta.model_dump(mode="json"))
    _write_json(dst / "unit-tests.json", unit.model_dump(mode="json"))
    _write_json(dst / "regression-tests.json", regression.model_dump(mode="json"))

    for rel in _referenced_files(regression):
        src_file = src / rel
        dst_file = dst / rel
        if rel.startswith("logs/"):
            _copy_text_file(src_file, dst_file)
        else:
            _copy_binary_file(src_file, dst_file)
    _copy_text_file(src / "logs" / "pipeline.log", dst / "logs" / "pipeline.log")
    write_artifact_manifest(dst)

    return RunIndexEntry(
        branch=meta.branch,
        arch=meta.arch,
        run_id=meta.run_id,
        started_at=meta.started_at,
        finished_at=meta.finished_at,
        status=meta.status,
        connection_name=meta.connection_name,
        triggered_by=meta.triggered_by,
        regtest_branch=meta.regtest_branch,
        unit_tests_total=meta.unit_tests_total,
        unit_tests_failed=meta.unit_tests_failed,
        regression_total=meta.regression_total,
        regression_passed=meta.regression_passed,
        regression_failed=meta.regression_failed,
        regression_broken=meta.regression_broken,
        archived=False,
        public=False,
        run_options=meta.run_options,
        rerun_of=meta.rerun_of,
    )


def _build_corrupt_run(target_root: Path) -> RunIndexEntry:
    branch = "demo-corrupt"
    arch = "cpu-serial"
    run_id = "demo-corrupt"
    dst = target_root / "runs" / branch / arch / run_id
    dst.mkdir(parents=True, exist_ok=True)
    meta = RunMeta(
        branch=branch,
        arch=arch,
        run_id=run_id,
        started_at="2026-04-01T00:00:00+00:00",
        finished_at="2026-04-01T00:01:00+00:00",
        status="failed",
        connection_name="local",
        triggered_by="demo-user",
        regtest_branch="master",
    )
    _write_json(dst / "run-meta.json", meta.model_dump(mode="json"))
    _write_json(dst / "unit-tests.json", {"tests": []})
    (dst / "regression-tests.json").write_text("{ invalid json\n", encoding="utf-8")
    return RunIndexEntry(
        branch=branch,
        arch=arch,
        run_id=run_id,
        started_at=meta.started_at,
        finished_at=meta.finished_at,
        status=meta.status,
        connection_name=meta.connection_name,
        triggered_by=meta.triggered_by,
        regtest_branch=meta.regtest_branch,
        unit_tests_total=0,
        unit_tests_failed=0,
        regression_total=0,
        regression_passed=0,
        regression_failed=0,
        regression_broken=0,
    )


def main() -> None:
    target = _repo_root() / "demo-data"
    source = _production_root()
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    entries_by_arch: dict[tuple[str, str], list[RunIndexEntry]] = {}
    for branch, arch, run_id, demo_run_id, keep_sims in SOURCE_RUNS:
        entry = _build_run(source, target, branch, arch, run_id, demo_run_id, keep_sims)
        entries_by_arch.setdefault((entry.branch, entry.arch), []).append(entry)
    corrupt = _build_corrupt_run(target)
    entries_by_arch.setdefault((corrupt.branch, corrupt.arch), []).append(corrupt)

    branches: dict[str, list[str]] = {}
    for (branch, arch), entries in sorted(entries_by_arch.items()):
        entries.sort(key=lambda e: e.started_at, reverse=True)
        idx_path = target / "runs-index" / branch / f"{arch}.json"
        _write_json(idx_path, [e.model_dump(mode="json") for e in entries])
        branches.setdefault(branch, []).append(arch)
    _write_json(
        target / "branches.json",
        {branch: sorted(set(archs)) for branch, archs in branches.items()},
    )
    _write_json(target / "schedules.json", [])
    print(f"demo-data written to {target}")


if __name__ == "__main__":
    main()
