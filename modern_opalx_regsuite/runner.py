from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from .config import SuiteConfig
from .data_model import (
    RunMeta,
    UnitTestsReport,
    RegressionTestsReport,
    RunIndexEntry,
    branches_index_path,
    runs_index_path,
    run_dir,
)


@dataclass
class RunPaths:
    root: Path
    logs_dir: Path
    plots_dir: Path
    pipeline_log_path: Path
    meta_path: Path
    unit_json_path: Path
    unit_log_path: Path
    reg_json_path: Path
    reg_log_path: Path


def _ensure_run_paths(data_root: Path, branch: str, arch: str, run_id: str) -> RunPaths:
    root = run_dir(data_root, branch, arch, run_id)
    logs_dir = root / "logs"
    plots_dir = root / "plots"
    logs_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)
    return RunPaths(
        root=root,
        logs_dir=logs_dir,
        plots_dir=plots_dir,
        pipeline_log_path=logs_dir / "pipeline.log",
        meta_path=root / "run-meta.json",
        unit_json_path=root / "unit-tests.json",
        unit_log_path=logs_dir / "unit-tests.log",
        reg_json_path=root / "regression-tests.json",
        reg_log_path=logs_dir / "regression-tests.log",
    )


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=str)


def _append_pipeline_line(pipeline_log_path: Path, line: str) -> None:
    pipeline_log_path.parent.mkdir(parents=True, exist_ok=True)
    with pipeline_log_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _git_update_repo(repo_path: Path, branch: str, pipeline_log_path: Path) -> None:
    """Fetch, checkout, and pull a given branch if this looks like a git repo."""
    git_dir = repo_path / ".git"
    if not git_dir.exists():
        _append_pipeline_line(
            pipeline_log_path,
            f"[git] Skipping update; {repo_path} is not a git repository.",
        )
        return

    def run_git(args: str) -> None:
        cmd = f"git {args}"
        _append_pipeline_line(pipeline_log_path, f"[git] {cmd}")
        _run_command(
            cmd,
            cwd=repo_path,
            log_path=pipeline_log_path,  # per-command output is fine in pipeline log
            pipeline_log_path=pipeline_log_path,
        )

    run_git(f"fetch origin {branch}")
    run_git(f"checkout {branch}")
    run_git(f"pull --ff-only origin {branch}")


def _run_command(
    cmd: str, cwd: Path, log_path: Path, pipeline_log_path: Path | None = None
) -> Tuple[int, str]:  # returncode, output
    cmd_list = shlex.split(cmd)
    proc = subprocess.Popen(
        cmd_list,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    lines: list[str] = []
    with log_path.open("w", encoding="utf-8") as log_file, (
        pipeline_log_path.open("a", encoding="utf-8")
        if pipeline_log_path is not None
        else open(os.devnull, "a", encoding="utf-8")
    ) as pipe_log:
        for line in proc.stdout:
            log_file.write(line)
            if pipeline_log_path is not None:
                pipe_log.write(line)
            lines.append(line)
    proc.wait()
    return proc.returncode, "".join(lines)


def _parse_unit_output(output: str) -> UnitTestsReport:
    # Minimal placeholder parser: treat whole run as a single test.
    # You can replace this with a CTest log parser that yields per-test results.
    status = "passed"
    lowered = output.lower()
    if "failed" in lowered or "error" in lowered:
        status = "failed"
    return UnitTestsReport(
        tests=[
            {
                "name": "unit-suite",
                "status": status,
                "output_snippet": output[-4000:],
            }
        ]
    )  # type: ignore[arg-type]


def _parse_regression_output(output: str) -> RegressionTestsReport:
    # Placeholder: mark a single simulation/metric based on whether "failed" appears.
    from .data_model import RegressionSimulation, RegressionMetric, RegressionTestsReport

    state = "passed"
    if "failed" in output.lower() or "error" in output.lower():
        state = "failed"
    sim = RegressionSimulation(
        name="regression-suite",
        description="Aggregated regression tests.",
        metrics=[
            RegressionMetric(
                metric="suite",
                mode="aggregate",
                state=state,
                eps=None,
                delta=None,
                reference_value=None,
                current_value=None,
                plot=None,
            )
        ],
    )
    return RegressionTestsReport(simulations=[sim])


def run_pipeline(
    cfg: SuiteConfig,
    branch: str,
    arch: str,
    run_id: Optional[str] = None,
    skip_unit: bool = False,
    skip_regression: bool = False,
) -> RunMeta:
    """Run the full pipeline for a given branch/architecture.

    This function is intentionally conservative and only assumes that:
    - There is an existing build directory for (branch, arch), or the user
      prepares it outside this function.
    - Unit tests and regression tests can be executed via configured shell
      commands inside that build tree.
    """
    if run_id is None:
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    data_root = cfg.resolved_data_root
    paths = _ensure_run_paths(data_root, branch, arch, run_id)

    meta = RunMeta(
        branch=branch,
        arch=arch,
        run_id=run_id,
        started_at=datetime.utcnow(),
        status="running",
    )
    _write_json(paths.meta_path, meta.model_dump())

    # Resolve repositories.
    opalx_repo = cfg.resolved_opalx_repo_root
    regtests_repo = cfg.resolved_regtests_repo_root

    # Determine build directory.
    build_dir = cfg.resolved_builds_root / branch / arch / "build"
    build_dir.mkdir(parents=True, exist_ok=True)

    # Update and check out repositories.
    _append_pipeline_line(
        paths.pipeline_log_path, f"== Updating OPALX repo at {opalx_repo} =="
    )
    _git_update_repo(
        repo_path=opalx_repo,
        branch=branch,
        pipeline_log_path=paths.pipeline_log_path,
    )
    _append_pipeline_line(
        paths.pipeline_log_path,
        f"== Updating regression-tests repo at {regtests_repo} (branch {cfg.regtests_branch}) ==",
    )
    _git_update_repo(
        repo_path=regtests_repo,
        branch=cfg.regtests_branch,
        pipeline_log_path=paths.pipeline_log_path,
    )

    # Configure and build with CMake and make.
    cmake_cmd = " ".join(
        ["cmake", *cfg.cmake_args, str(opalx_repo)]
    )
    _append_pipeline_line(
        paths.pipeline_log_path, f"== Configuring build: {cmake_cmd} =="
    )
    _run_command(
        cmake_cmd,
        cwd=build_dir,
        log_path=paths.logs_dir / "cmake.log",
        pipeline_log_path=paths.pipeline_log_path,
    )

    build_cmd = cfg.build_command
    _append_pipeline_line(
        paths.pipeline_log_path, f"== Building: {build_cmd} =="
    )
    _run_command(
        build_cmd,
        cwd=build_dir,
        log_path=paths.logs_dir / "build.log",
        pipeline_log_path=paths.pipeline_log_path,
    )

    unit_report = UnitTestsReport()
    reg_report = RegressionTestsReport()

    # Unit tests
    if not skip_unit and cfg.unit_test_command:
        rc, output = _run_command(
            cfg.unit_test_command,
            cwd=build_dir,
            log_path=paths.unit_log_path,
            pipeline_log_path=paths.pipeline_log_path,
        )
        unit_report = _parse_unit_output(output)
        meta.unit_tests_total = unit_report.total
        meta.unit_tests_failed = unit_report.failed
        if rc != 0 and meta.status == "running":
            meta.status = "failed"

    _write_json(paths.unit_json_path, unit_report.model_dump())

    # Regression tests
    if not skip_regression and cfg.regression_test_command:
        rc, output = _run_command(
            cfg.regression_test_command,
            cwd=build_dir,
            log_path=paths.reg_log_path,
            pipeline_log_path=paths.pipeline_log_path,
        )
        reg_report = _parse_regression_output(output)
        meta.regression_total = reg_report.total
        meta.regression_failed = reg_report.failed
        meta.regression_broken = reg_report.broken
        if rc != 0 and meta.status == "running":
            meta.status = "failed"

    _write_json(paths.reg_json_path, reg_report.model_dump())

    # Finalize meta and indexes.
    if meta.status == "running":
        if meta.unit_tests_failed or meta.regression_failed or meta.regression_broken:
            meta.status = "failed"
        else:
            meta.status = "passed"

    meta.finished_at = datetime.utcnow()
    _write_json(paths.meta_path, meta.model_dump())

    _update_indexes(data_root, meta)
    return meta


def _update_indexes(data_root: Path, meta: RunMeta) -> None:
    # Update runs index for branch/arch.
    index_path = runs_index_path(data_root, meta.branch, meta.arch)
    entries: list[RunIndexEntry] = []
    if index_path.is_file():
        with index_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        entries = [RunIndexEntry.model_validate(e) for e in raw]

    entry = RunIndexEntry(
        branch=meta.branch,
        arch=meta.arch,
        run_id=meta.run_id,
        started_at=meta.started_at,
        finished_at=meta.finished_at,
        status=meta.status,
        unit_tests_failed=meta.unit_tests_failed,
        regression_failed=meta.regression_failed,
        regression_broken=meta.regression_broken,
    )
    entries.append(entry)
    entries.sort(key=lambda e: e.started_at, reverse=True)
    _write_json(index_path, [e.model_dump() for e in entries])

    # Update branches index.
    branches_path = branches_index_path(data_root)
    branches: dict[str, list[str]] = {}
    if branches_path.is_file():
        with branches_path.open("r", encoding="utf-8") as f:
            branches = json.load(f)
    archs = set(branches.get(meta.branch, []))
    archs.add(meta.arch)
    branches[meta.branch] = sorted(archs)
    _write_json(branches_path, branches)

