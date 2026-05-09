"""Main pipeline orchestration: git → cmake → build → unit → regression."""
from __future__ import annotations

import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..config import Connection, SuiteConfig
from ..artifacts import write_artifact_manifest
from ..data_model import (
    RerunReference,
    RunMeta,
    RunOptions,
    UnitTestsReport,
    RegressionTestsReport,
)
from .cmake import build_cmake_command, merge_cmake_args, normalize_custom_cmake_args
from .execution import (
    _append_pipeline_line,
    _build_local_env,
    _ensure_run_paths,
    _phase,
    _run_command,
    _start_pipeline_log,
    _write_json,
)
from .pipeline_git import sync_repositories
from .pipeline_indexes import _cancel_run, _update_indexes
from .pipeline_options import resolve_effective_run_options
from .parsing.unit import _parse_unit_output
from .regression_runner import _run_regression_suite, _run_regression_suite_remote
from .remote_setup import create_remote_executor


def run_pipeline(
    cfg: SuiteConfig,
    branch: str,
    arch: str,
    run_id: Optional[str] = None,
    skip_unit: bool = False,
    skip_regression: bool = False,
    clean_build: bool = False,
    cancel_event: Optional[threading.Event] = None,
    connection: Optional[Connection] = None,
    target_key_path: Optional[Path] = None,
    gateway_key_path: Optional[Path] = None,
    repo_locks: Optional[dict[str, threading.Lock]] = None,
    triggered_by: str = "",
    public: bool = False,
    rerun_of: Optional[RerunReference] = None,
    custom_cmake_args: Optional[list[str]] = None,
    mpi_ranks: Optional[int] = None,
    opalx_info_level: Optional[int] = None,
    gateway_password: Optional[str] = None,
    gateway_otp: Optional[str] = None,
) -> RunMeta:
    """Run the full pipeline for a given branch/architecture.

    Pass *cancel_event* (a :class:`threading.Event`) to allow callers to
    interrupt the pipeline between phases.  The event is checked after git
    updates, after cmake+build, after unit tests, and between each regression
    test.

    Pass *connection* to run remotely. The runner is user-agnostic — the
    caller (the API layer) is responsible for resolving *target_key_path* and
    (optionally) *gateway_key_path* from the user's per-user ssh-keys dir
    before invoking this function. When *connection* is None, the run is
    local and uses ``ArchConfig.env`` for environment activation.

    Pass *repo_locks* (a dict mapping absolute repo path to
    :class:`threading.Lock`) to serialise git operations on shared local
    repositories when multiple pipelines run concurrently.
    """
    if run_id is None:
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    data_root = cfg.resolved_data_root
    paths = _ensure_run_paths(data_root, branch, arch, run_id)
    _start_pipeline_log(paths.pipeline_log_path, branch, arch, run_id)

    is_remote = connection is not None
    connection_name = connection.name if connection is not None else "local"
    run_options = resolve_effective_run_options(
        cfg=cfg,
        arch=arch,
        clean_build=clean_build,
        custom_cmake_args=custom_cmake_args,
        mpi_ranks=mpi_ranks,
        opalx_info_level=opalx_info_level,
    )
    ac = run_options.arch_config

    # SENSITIVE-DATA RULE: only ``connection_name`` (user-chosen) lands in
    # run-meta.json. Never write the underlying SSH host/user/work_dir here.
    meta = RunMeta(
        branch=branch,
        arch=arch,
        run_id=run_id,
        started_at=datetime.now(timezone.utc),
        status="running",
        connection_name=connection_name,
        triggered_by=triggered_by or None,
        public=public,
        run_options=RunOptions(
            skip_unit=skip_unit,
            skip_regression=skip_regression,
            clean_build=run_options.clean_build,
            custom_cmake_args=run_options.custom_cmake_args,
            mpi_ranks=run_options.mpi_ranks,
            opalx_info_level=run_options.opalx_info_level,
        ),
        rerun_of=rerun_of,
    )
    meta.regtest_branch = cfg.regtests_branch
    _write_json(paths.meta_path, meta.model_dump())

    base_cmake_args = ac.cmake_args if ac.cmake_args is not None else cfg.cmake_args
    effective_cmake_args = merge_cmake_args(
        base_cmake_args, run_options.custom_cmake_args
    )
    build_cmd = f"make -j{ac.build_jobs}"
    slurm_allocation_args = ac.slurm_allocation_args(run_options.mpi_ranks)

    # ── Remote executor setup ────────────────────────────────────────────────
    remote: Optional["RemoteExecutor"] = None  # type: ignore[name-defined]
    remote_base: Optional[str] = None
    remote_build: Optional[str] = None

    if is_remote and connection is not None:
        remote, remote_base, remote_build = create_remote_executor(
            connection=connection,
            target_key_path=target_key_path,
            gateway_key_path=gateway_key_path,
            pipeline_log_path=paths.pipeline_log_path,
            arch_config=ac,
            branch=branch,
            arch=arch,
            gateway_password=gateway_password,
            gateway_otp=gateway_otp,
        )

    # Build the local environment once for this run (used by cmake, build, tests).
    # Remote runs: env activation happens inline inside RemoteExecutor.
    module_env: Optional[dict[str, str]] = None
    if not is_remote:
        module_env = _build_local_env(ac.env, paths.pipeline_log_path)

    # Resolve repositories.
    opalx_repo = cfg.resolved_opalx_repo_root
    regtests_repo = cfg.resolved_regtests_repo_root

    # Determine build directory (local).
    build_dir = cfg.resolved_builds_root / branch / arch / "build"
    build_dir.mkdir(parents=True, exist_ok=True)

    try:
        # ── Phase: slurm-alloc (optional) ────────────────────────────────────
        if is_remote and remote is not None and slurm_allocation_args:
            _phase(paths.pipeline_log_path, "slurm-alloc")
            try:
                job_id = remote.allocate_slurm_job(slurm_allocation_args)
                _append_pipeline_line(
                    paths.pipeline_log_path,
                    f"[{connection_name}] Slurm job {job_id} allocated"
                    f" ({' '.join(slurm_allocation_args)})",
                )
            except Exception as exc:
                _phase(paths.pipeline_log_path, "done status=failed")
                meta.status = "failed"
                meta.finished_at = datetime.now(timezone.utc)
                _write_json(paths.meta_path, meta.model_dump())
                write_artifact_manifest(paths.root)
                _update_indexes(data_root, meta)
                raise RuntimeError(f"Slurm allocation failed: {exc}") from exc

        if is_remote and remote is not None:
            _append_pipeline_line(
                paths.pipeline_log_path,
                f"[{connection_name}] Connection established.",
            )
            remote.ensure_dir(remote_build)  # type: ignore[arg-type]

        # ── Phase: git ────────────────────────────────────────────────────────
        _phase(paths.pipeline_log_path, "git")
        opalx_git_ok, reg_git_ok = sync_repositories(
            cfg=cfg,
            meta=meta,
            paths=paths,
            branch=branch,
            connection_name=connection_name,
            remote=remote,
            remote_base=remote_base,
            opalx_repo=opalx_repo,
            regtests_repo=regtests_repo,
            repo_locks=repo_locks,
            cancel_event=cancel_event,
        )

        if cancel_event is not None and cancel_event.is_set():
            return _cancel_run(meta, paths, data_root)

        # Gate: abort before cmake/build if git failed so we never build stale
        # code (especially important on remote runs where a Slurm allocation
        # would otherwise be consumed pointlessly).
        if not (opalx_git_ok and reg_git_ok):
            _append_pipeline_line(
                paths.pipeline_log_path,
                "Git phase failed — aborting pipeline before cmake/build.",
            )
            meta.status = "failed"
            meta.finished_at = datetime.now(timezone.utc)
            _phase(paths.pipeline_log_path, "done status=failed")
            _write_json(paths.meta_path, meta.model_dump())
            write_artifact_manifest(paths.root)
            _update_indexes(data_root, meta)
            return meta

        # ── Clean build (optional) ───────────────────────────────────────────
        # User-requested full reconfigure: wipe the per-branch/arch build dir
        # before cmake. Source checkouts and run data are untouched.
        if run_options.clean_build:
            if is_remote and remote is not None:
                _append_pipeline_line(
                    paths.pipeline_log_path,
                    f"[{connection_name}] Clean build: wiping {remote_build}",
                )
                remote.remove_dir(remote_build)  # type: ignore[arg-type]
                remote.ensure_dir(remote_build)  # type: ignore[arg-type]
            else:
                _append_pipeline_line(
                    paths.pipeline_log_path,
                    f"Clean build: wiping {build_dir}",
                )
                shutil.rmtree(build_dir, ignore_errors=True)
                build_dir.mkdir(parents=True, exist_ok=True)

        # ── Phase: cmake ──────────────────────────────────────────────────────
        _phase(paths.pipeline_log_path, "cmake")
        if is_remote and remote is not None:
            # NB: cmake_cmd contains the remote work_dir; pass it to the
            # executor (which never logs the wrapped command), and only log a
            # sanitized line under data_root.
            cmake_cmd = build_cmake_command(
                effective_cmake_args, f"{remote_base}/opalx-src"
            )
            _append_pipeline_line(
                paths.pipeline_log_path,
                f"[{connection_name}] Configuring build (cmake)",
            )
            cmake_rc = remote.run_command(
                cmake_cmd,
                remote_cwd=remote_build,  # type: ignore[arg-type]
                log_path=paths.logs_dir / "cmake.log",
                cancel_event=cancel_event,
            )
        else:
            cmake_cmd = build_cmake_command(effective_cmake_args, str(opalx_repo))
            _append_pipeline_line(
                paths.pipeline_log_path, f"Configuring build: {cmake_cmd}"
            )
            cmake_rc, _ = _run_command(
                cmake_cmd,
                cwd=build_dir,
                log_path=paths.logs_dir / "cmake.log",
                pipeline_log_path=paths.pipeline_log_path,
                env=module_env,
                cancel_event=cancel_event,
            )

        if cmake_rc == 0:
            _append_pipeline_line(
                paths.pipeline_log_path,
                f"[{connection_name}] CMake configuration done.",
            )
        else:
            _append_pipeline_line(
                paths.pipeline_log_path,
                f"[{connection_name}] CMake configuration FAILED (rc={cmake_rc}).",
            )

        # ── Phase: build ──────────────────────────────────────────────────────
        _phase(paths.pipeline_log_path, "build")
        _append_pipeline_line(paths.pipeline_log_path, f"Building: {build_cmd}")
        if is_remote and remote is not None:
            build_rc = remote.run_command(
                build_cmd,
                remote_cwd=remote_build,  # type: ignore[arg-type]
                log_path=paths.logs_dir / "build.log",
                cancel_event=cancel_event,
            )
        else:
            build_rc, _ = _run_command(
                build_cmd,
                cwd=build_dir,
                log_path=paths.logs_dir / "build.log",
                pipeline_log_path=paths.pipeline_log_path,
                env=module_env,
                cancel_event=cancel_event,
            )

        build_ok = cmake_rc == 0 and build_rc == 0
        if build_ok:
            _append_pipeline_line(
                paths.pipeline_log_path,
                f"[{connection_name}] Build complete.",
            )
        else:
            _append_pipeline_line(
                paths.pipeline_log_path,
                f"[{connection_name}] Build FAILED (cmake_rc={cmake_rc}, build_rc={build_rc}).",
            )
        if not build_ok:
            meta.status = "failed"

        if cancel_event is not None and cancel_event.is_set():
            return _cancel_run(meta, paths, data_root)

        unit_report = UnitTestsReport()
        reg_report = RegressionTestsReport()

        # ── Phase: unit ───────────────────────────────────────────────────────
        _phase(paths.pipeline_log_path, "unit")
        if build_ok and not skip_unit and cfg.unit_test_command:
            if is_remote and remote is not None:
                rc = remote.run_command(
                    cfg.unit_test_command,
                    remote_cwd=remote_build,  # type: ignore[arg-type]
                    log_path=paths.unit_log_path,
                    cancel_event=cancel_event,
                )
                output = paths.unit_log_path.read_text(encoding="utf-8", errors="replace")
            else:
                rc, output = _run_command(
                    cfg.unit_test_command,
                    cwd=build_dir,
                    log_path=paths.unit_log_path,
                    pipeline_log_path=paths.pipeline_log_path,
                    env=module_env,
                    cancel_event=cancel_event,
                )
            unit_report = _parse_unit_output(output)
            meta.unit_tests_total = unit_report.total
            meta.unit_tests_failed = unit_report.failed
            _append_pipeline_line(
                paths.pipeline_log_path,
                f"[{connection_name}] Unit tests done: "
                f"{unit_report.total - unit_report.failed}/{unit_report.total} passed.",
            )
            if rc != 0 and meta.status == "running":
                meta.status = "failed"
        elif skip_unit:
            _append_pipeline_line(paths.pipeline_log_path, "[unit] Skipped by user.")
        else:
            _append_pipeline_line(paths.pipeline_log_path, "[unit] Skipped because build failed.")

        _write_json(paths.unit_json_path, unit_report.model_dump())

        if cancel_event is not None and cancel_event.is_set():
            return _cancel_run(meta, paths, data_root)

        # ── Phase: regression ─────────────────────────────────────────────────
        _phase(paths.pipeline_log_path, "regression")
        if build_ok and not skip_regression:
            if is_remote and remote is not None and connection is not None:
                reg_report = _run_regression_suite_remote(
                    cfg=cfg,
                    paths=paths,
                    connection=connection,
                    mpi_ranks=run_options.mpi_ranks,
                    opalx_info_level=run_options.opalx_info_level,
                    use_slurm=bool(slurm_allocation_args),
                    remote=remote,
                    remote_base=remote_base,  # type: ignore[arg-type]
                    remote_build=remote_build,  # type: ignore[arg-type]
                    run_id=run_id,
                    pipeline_log_path=paths.pipeline_log_path,
                    cancel_event=cancel_event,
                )
            else:
                reg_report = _run_regression_suite(
                    cfg=cfg,
                    paths=paths,
                    build_dir=build_dir,
                    pipeline_log_path=paths.pipeline_log_path,
                    mpi_ranks=run_options.mpi_ranks,
                    opalx_info_level=run_options.opalx_info_level,
                    cancel_event=cancel_event,
                    base_env=module_env,
                )
            meta.regression_total = reg_report.total
            meta.regression_passed = reg_report.passed
            meta.regression_failed = reg_report.failed
            meta.regression_broken = reg_report.broken
            if (
                meta.regression_failed > 0 or meta.regression_broken > 0
            ) and meta.status == "running":
                meta.status = "failed"
        elif skip_regression:
            _append_pipeline_line(paths.pipeline_log_path, "[regression] Skipped by user.")
        else:
            _append_pipeline_line(
                paths.pipeline_log_path, "[regression] Skipped because build failed."
            )

        _write_json(paths.reg_json_path, reg_report.model_dump())

        if cancel_event is not None and cancel_event.is_set():
            return _cancel_run(meta, paths, data_root)

        # ── Phase: done ───────────────────────────────────────────────────────
        if meta.status == "running":
            if meta.unit_tests_failed or meta.regression_failed or meta.regression_broken:
                meta.status = "failed"
            else:
                meta.status = "passed"

        meta.finished_at = datetime.now(timezone.utc)
        _phase(paths.pipeline_log_path, f"done status={meta.status}")
        _write_json(paths.meta_path, meta.model_dump())
        write_artifact_manifest(paths.root)
        _update_indexes(data_root, meta)
        return meta

    finally:
        # Always remove the local work dir so aborted/failed runs leave no debris.
        if paths.work_dir.exists():
            shutil.rmtree(paths.work_dir, ignore_errors=True)

        if remote is not None:
            # Clean up per-run work dir on remote (always).
            if remote_base is not None and run_id:
                remote.cleanup(f"{remote_base}/work/{run_id}")
            # Full cleanup only if configured on the connection.
            if (
                connection is not None
                and connection.cleanup_after_run
                and remote_base is not None
            ):
                remote.cleanup(remote_base)
            remote.close()
