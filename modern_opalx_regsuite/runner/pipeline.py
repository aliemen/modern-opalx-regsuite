"""Main pipeline orchestration: git → cmake → build → unit → regression."""
from __future__ import annotations

import json
import shlex
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..archive_service import locked_index
from ..config import Connection, SuiteConfig
from ..data_model import (
    RunIndexEntry,
    RunMeta,
    UnitTestsReport,
    RegressionTestsReport,
    branches_index_path,
    runs_index_path,
)
from .execution import (
    RunPaths,
    _append_pipeline_line,
    _build_local_env,
    _ensure_run_paths,
    _phase,
    _run_command,
    _start_pipeline_log,
    _write_json,
)
from .git import _get_repo_url, _git_head_short, _git_update_repo
from .parsing.unit import _parse_unit_output
from .regression_runner import _run_regression_suite, _run_regression_suite_remote


def _cancel_run(meta: RunMeta, paths: RunPaths, data_root: Path) -> RunMeta:
    """Finalise a cancelled run and persist it."""
    _append_pipeline_line(paths.pipeline_log_path, "== PHASE: done status=cancelled ==")
    meta.status = "cancelled"
    meta.finished_at = datetime.now(timezone.utc)
    _write_json(paths.meta_path, meta.model_dump())
    _update_indexes(data_root, meta)
    return meta


def _update_indexes(data_root: Path, meta: RunMeta) -> None:
    # Update runs index for branch/arch under the same fcntl lock used by the
    # archive service, so a bulk-archive flip and a pipeline completion can't
    # clobber each other.
    index_path = runs_index_path(data_root, meta.branch, meta.arch)
    with locked_index(index_path):
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
            connection_name=meta.connection_name,
            triggered_by=meta.triggered_by,
            unit_tests_total=meta.unit_tests_total,
            unit_tests_failed=meta.unit_tests_failed,
            regression_total=meta.regression_total,
            regression_passed=meta.regression_passed,
            regression_failed=meta.regression_failed,
            regression_broken=meta.regression_broken,
            archived=meta.archived,
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


def run_pipeline(
    cfg: SuiteConfig,
    branch: str,
    arch: str,
    run_id: Optional[str] = None,
    skip_unit: bool = False,
    skip_regression: bool = False,
    cancel_event: Optional[threading.Event] = None,
    connection: Optional[Connection] = None,
    target_key_path: Optional[Path] = None,
    gateway_key_path: Optional[Path] = None,
    repo_locks: Optional[dict[str, threading.Lock]] = None,
    triggered_by: str = "",
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
    )
    _write_json(paths.meta_path, meta.model_dump())

    # Resolve arch-specific overrides.
    ac = cfg.get_arch_config(arch)
    effective_cmake_args = ac.cmake_args if ac.cmake_args is not None else cfg.cmake_args
    build_cmd = f"make -j{ac.build_jobs}"

    # ── Remote executor setup ────────────────────────────────────────────────
    remote: Optional["RemoteExecutor"] = None  # type: ignore[name-defined]
    remote_base: Optional[str] = None
    remote_build: Optional[str] = None

    if is_remote and connection is not None:
        from ..remote import RemoteExecutor

        if target_key_path is None:
            raise ValueError(
                "run_pipeline: connection is set but target_key_path is None — "
                "the API layer must pre-resolve key paths."
            )
        if not target_key_path.exists():
            raise FileNotFoundError(f"SSH key not found: {target_key_path}")
        if (
            connection.gateway is not None
            and connection.gateway.auth_method != "interactive"
        ):
            if gateway_key_path is None:
                raise ValueError(
                    "run_pipeline: connection has a gateway but gateway_key_path is None"
                )
            if not gateway_key_path.exists():
                raise FileNotFoundError(
                    f"Gateway SSH key not found: {gateway_key_path}"
                )
        remote = RemoteExecutor(
            host=connection.host,
            user=connection.user,
            key_path=target_key_path,
            port=connection.port,
            connection_name=connection.name,
            gateway=connection.gateway,
            gateway_key_path=gateway_key_path,
            env=connection.env,
            pipeline_log_path=paths.pipeline_log_path,
            keepalive_interval=connection.keepalive_interval,
            command_timeout=ac.command_timeout,
            salloc_timeout=ac.salloc_timeout,
            gateway_password=gateway_password,
            gateway_otp=gateway_otp,
        )
        remote_base = connection.work_dir
        remote_build = f"{remote_base}/builds/{branch}/{arch}/build"

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
        if is_remote and remote is not None and ac.slurm_args:
            _phase(paths.pipeline_log_path, "slurm-alloc")
            try:
                job_id = remote.allocate_slurm_job(ac.slurm_args)
                _append_pipeline_line(
                    paths.pipeline_log_path,
                    f"[{connection_name}] Slurm job {job_id} allocated"
                    f" ({' '.join(ac.slurm_args)})",
                )
            except Exception as exc:
                _phase(paths.pipeline_log_path, "done status=failed")
                meta.status = "failed"
                meta.finished_at = datetime.now(timezone.utc)
                _write_json(paths.meta_path, meta.model_dump())
                _update_indexes(data_root, meta)
                raise RuntimeError(f"Slurm allocation failed: {exc}") from exc

        if is_remote and remote is not None:
            remote.ensure_dir(remote_build)  # type: ignore[arg-type]

        # ── Phase: git ────────────────────────────────────────────────────────
        _phase(paths.pipeline_log_path, "git")

        if is_remote and remote is not None:
            # Remote runs: read-only local operations only.
            # We never mutate the local working tree so concurrent local
            # builds are not disturbed.  The real clone/update happens on
            # the remote machine.
            meta.opalx_commit = _git_head_short(opalx_repo)
            meta.tests_repo_commit = _git_head_short(regtests_repo)
            _write_json(paths.meta_path, meta.model_dump())

            opalx_url = _get_repo_url(opalx_repo, cfg.opalx_repo_url)
            regtests_url = _get_repo_url(regtests_repo, cfg.regtests_repo_url)

            # Sanitized: connection_name only, no host. The actual git URLs are
            # public (or at least already in the user's connection config) so
            # they're acceptable; the SSH host is not.
            _append_pipeline_line(
                paths.pipeline_log_path,
                f"[{connection_name}] Cloning/updating OPALX (branch={branch})",
            )
            remote_opalx_ok = remote.git_clone_or_update(
                opalx_url,
                f"{remote_base}/opalx-src",
                branch,
                log_path=paths.pipeline_log_path,
                cancel_event=cancel_event,
            )
            _append_pipeline_line(
                paths.pipeline_log_path,
                f"[{connection_name}] Cloning/updating regression-tests (branch={cfg.regtests_branch})",
            )
            remote_regtests_ok = remote.git_clone_or_update(
                regtests_url,
                f"{remote_base}/regtests",
                cfg.regtests_branch,
                log_path=paths.pipeline_log_path,
                cancel_event=cancel_event,
            )
            opalx_git_ok = remote_opalx_ok and remote_regtests_ok
            reg_git_ok = True
        else:
            # Local runs: full git update under per-repo locks so concurrent
            # pipelines serialise access to the shared working trees.
            _opalx_lock = (repo_locks or {}).get(str(opalx_repo))
            _regtests_lock = (repo_locks or {}).get(str(regtests_repo))

            if _opalx_lock:
                _opalx_lock.acquire()
            try:
                _append_pipeline_line(
                    paths.pipeline_log_path,
                    f"Updating OPALX repo at {opalx_repo}",
                )
                opalx_git_ok = _git_update_repo(
                    repo_path=opalx_repo,
                    branch=branch,
                    pipeline_log_path=paths.pipeline_log_path,
                )
                meta.opalx_commit = _git_head_short(opalx_repo)
            finally:
                if _opalx_lock:
                    _opalx_lock.release()

            if _regtests_lock:
                _regtests_lock.acquire()
            try:
                _append_pipeline_line(
                    paths.pipeline_log_path,
                    f"Updating regression-tests repo at {regtests_repo} (branch {cfg.regtests_branch})",
                )
                reg_git_ok = _git_update_repo(
                    repo_path=regtests_repo,
                    branch=cfg.regtests_branch,
                    pipeline_log_path=paths.pipeline_log_path,
                )
                meta.tests_repo_commit = _git_head_short(regtests_repo)
            finally:
                if _regtests_lock:
                    _regtests_lock.release()

            _write_json(paths.meta_path, meta.model_dump())

        if cancel_event is not None and cancel_event.is_set():
            return _cancel_run(meta, paths, data_root)

        # ── Phase: cmake ──────────────────────────────────────────────────────
        _phase(paths.pipeline_log_path, "cmake")
        if is_remote and remote is not None:
            # NB: cmake_cmd contains the remote work_dir; pass it to the
            # executor (which never logs the wrapped command), and only log a
            # sanitized line under data_root.
            cmake_cmd = " ".join(
                ["cmake", *effective_cmake_args, shlex.quote(f"{remote_base}/opalx-src")]
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
            cmake_cmd = " ".join(["cmake", *effective_cmake_args, str(opalx_repo)])
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
        if not build_ok:
            meta.status = "failed"
        if not (opalx_git_ok and reg_git_ok):
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
                    mpi_ranks=ac.mpi_ranks,
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
                    mpi_ranks=ac.mpi_ranks,
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
        _update_indexes(data_root, meta)
        return meta

    finally:
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
