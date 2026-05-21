"""Local and remote regression test executors.

Both variants share ``_build_simulation`` for post-processing (stat parsing,
delta computation, plot generation, and RegressionSimulation assembly).
"""
from __future__ import annotations

import os
import shlex
import shutil
import time
import threading
from pathlib import Path
from typing import Optional

from ..config import Connection, SuiteConfig
from ..data_model import RegressionTestsReport
from .execution import RunPaths, _append_pipeline_line, _run_command
from .parsing.regression import (
    _discover_regression_tests,
    _discover_regression_tests_remote,
)
from .regression_results import _build_simulation


def _find_opalx_executable(build_dir: Path, relpath: str) -> Optional[Path]:
    candidate = build_dir / relpath
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return candidate
    fallback = build_dir / "opalx"
    if fallback.is_file() and os.access(fallback, os.X_OK):
        return fallback
    which = shutil.which("opalx")
    if which:
        return Path(which)
    return None


def _build_opalx_run_command(
    *,
    opalx_exe: str,
    input_name: str,
    mpi_ranks: int,
    opalx_info_level: int,
    opalx_args: list[str],
    launcher: str,
) -> str:
    """Build the generated OPALX regression command.

    ``launcher`` is ``"mpirun"`` for local/non-Slurm execution and ``"none"``
    for Slurm allocations, where :class:`RemoteExecutor` supplies the outer
    ``srun -n`` job step.
    """
    args = [
        shlex.quote(opalx_exe),
        shlex.quote(input_name),
        "--info",
        str(opalx_info_level),
        *(shlex.quote(a) for a in opalx_args),
    ]
    cmd = " ".join(args)
    if launcher == "mpirun":
        return f"mpirun -np {mpi_ranks} {cmd}"
    if launcher == "none":
        return cmd
    raise ValueError(f"Unknown OPALX launcher: {launcher}")


def _run_regression_suite(
    cfg: SuiteConfig,
    paths: RunPaths,
    build_dir: Path,
    pipeline_log_path: Path,
    mpi_ranks: int = 1,
    opalx_info_level: int = 2,
    cancel_event: Optional[threading.Event] = None,
    base_env: Optional[dict[str, str]] = None,
) -> RegressionTestsReport:
    """Run regression tests locally."""
    tests_root = cfg.resolved_regtests_repo_root / cfg.regtests_subdir
    tests = _discover_regression_tests(tests_root)
    report = RegressionTestsReport(simulations=[])

    opalx_exe = _find_opalx_executable(build_dir, cfg.opalx_executable_relpath)
    if opalx_exe is None:
        _append_pipeline_line(
            pipeline_log_path,
            "[regression] opalx executable not found; skipping regression tests.",
        )
        return report

    reg_lines: list[str] = [
        f"Running {len(tests)} regression tests from {tests_root}",
        f"OPALX executable: {opalx_exe}",
        f"MPI ranks: {mpi_ranks}",
        f"OPALX --info: {opalx_info_level}",
    ]

    for test_name in tests:
        if cancel_event is not None and cancel_event.is_set():
            _append_pipeline_line(
                pipeline_log_path,
                "[regression] CANCELLED by user — stopping regression tests.",
            )
            break

        src_test_dir = tests_root / test_name
        work_test_dir = paths.work_dir / test_name
        if work_test_dir.exists():
            shutil.rmtree(work_test_dir)
        shutil.copytree(src_test_dir, work_test_dir)

        test_input = work_test_dir / f"{test_name}.in"
        rt_file = work_test_dir / f"{test_name}.rt"
        reference_dir = src_test_dir / "reference"

        test_log_local = work_test_dir / f"{test_name}-RT.log"
        test_log_run = paths.logs_dir / f"{test_name}-RT.log"
        env = (base_env or os.environ).copy()
        cmd = _build_opalx_run_command(
            opalx_exe=str(opalx_exe),
            input_name=test_input.name,
            mpi_ranks=mpi_ranks,
            opalx_info_level=opalx_info_level,
            opalx_args=cfg.opalx_args,
            launcher="mpirun",
        )
        _append_pipeline_line(
            pipeline_log_path,
            f"[regression] {test_name} generated command: {cmd}",
        )

        _append_pipeline_line(pipeline_log_path, f"[regression] START {test_name}")
        test_start = time.monotonic()
        rc, _output = _run_command(
            cmd,
            cwd=work_test_dir,
            log_path=test_log_local,
            pipeline_log_path=pipeline_log_path,
            env=env,
            timeout_seconds=cfg.per_test_timeout_seconds,
        )
        if test_log_local.exists():
            shutil.copy2(test_log_local, test_log_run)
            out_file = work_test_dir / f"{test_name}.out"
            if not out_file.exists():
                shutil.copy2(test_log_local, out_file)

        # Resolve the input file path so _build_simulation can look up element types
        in_file = test_input if test_input.exists() else None
        sim = _build_simulation(
            test_name=test_name,
            rc=rc,
            rt_file=rt_file,
            work_test_dir=work_test_dir,
            reference_dir=reference_dir,
            plots_dir=paths.plots_dir,
            pipeline_log_path=pipeline_log_path,
            test_start=test_start,
            input_file=in_file,
            log_path=test_log_run,
        )
        report.simulations.append(sim)
        metric_count = sum(len(c.metrics) for c in sim.containers)
        end_extra = f" signal={sim.crash_signal}" if sim.crash_signal else ""
        duration_ms = int((time.monotonic() - test_start) * 1000)
        _append_pipeline_line(
            pipeline_log_path,
            f"[regression] END {test_name} state={sim.state} duration_ms={duration_ms} metrics={metric_count}{end_extra}",
        )
        reg_lines.append(f"{test_name}: {sim.state} ({metric_count} checks)")

    if not cfg.keep_work_dirs and paths.work_dir.exists():
        shutil.rmtree(paths.work_dir)
        _append_pipeline_line(pipeline_log_path, "[regression] Removed temporary work directory.")

    paths.reg_log_path.write_text("\n".join(reg_lines) + "\n", encoding="utf-8")
    return report


def _run_regression_suite_remote(
    cfg: SuiteConfig,
    paths: RunPaths,
    connection: Connection,
    mpi_ranks: int,
    opalx_info_level: int,
    use_slurm: bool,
    slurm_step_args: Optional[list[str]],
    remote: "RemoteExecutor",  # type: ignore[name-defined]
    remote_base: str,
    remote_build: str,
    run_id: str,
    pipeline_log_path: Path,
    cancel_event: Optional[threading.Event] = None,
) -> RegressionTestsReport:
    """Run regression tests on a remote host via SSH.

    Test discovery and result processing (stat parsing, plots) happen locally.
    Only the simulation execution happens on the remote.

    Sensitive-data rule: every line written to ``reg_lines`` (which becomes
    ``regression-tests.log`` under data_root) uses the connection name only;
    never the underlying SSH host or remote work_dir.
    """
    # Test discovery, metadata (.rt/.in), and reference stats all come from
    # the REMOTE regtests checkout — never the local working tree.  The local
    # tree is only used by the frontend for branch enumeration and may be on
    # an arbitrary commit; reading from it would silently miss tests added
    # on the branch the user picked.
    remote_opalx_exe = f"{remote_build}/{cfg.opalx_executable_relpath}"
    remote_tests_root = f"{remote_base}/regtests/{cfg.regtests_subdir}"

    tests = _discover_regression_tests_remote(remote, remote_tests_root)
    report = RegressionTestsReport(simulations=[])

    # Scratch area for fetched metadata (rt/in/reference) so _build_simulation
    # can parse them locally.  Lives under work_dir so `keep_work_dirs`
    # preserves it for debugging and the normal cleanup sweep removes it.
    meta_root = paths.work_dir / "_remote_meta"
    meta_root.mkdir(parents=True, exist_ok=True)

    reg_lines: list[str] = [
        f"Running {len(tests)} regression tests remotely via [{connection.name}]",
        f"MPI ranks: {mpi_ranks}",
        f"OPALX --info: {opalx_info_level}",
    ]

    # Ensure the per-run work directory exists on the remote before any cp -r calls.
    remote_run_work_dir = f"{remote_base}/work/{run_id}"
    remote.ensure_dir(remote_run_work_dir)

    if not use_slurm and (
        remote.run_command(
            "command -v mpirun >/dev/null 2>&1",
            remote_cwd=remote_run_work_dir,
            log_path=pipeline_log_path,
            append_log=True,
        )
        != 0
    ):
        _append_pipeline_line(
            pipeline_log_path,
            "[regression] WARNING: mpirun not detected on remote; non-Slurm regression runs may fail.",
        )

    for test_name in tests:
        if cancel_event is not None and cancel_event.is_set():
            _append_pipeline_line(
                pipeline_log_path,
                "[regression] CANCELLED by user — stopping regression tests.",
            )
            break

        work_test_dir = paths.work_dir / test_name
        if work_test_dir.exists():
            shutil.rmtree(work_test_dir)
        work_test_dir.mkdir(parents=True, exist_ok=True)

        remote_test_work = f"{remote_base}/work/{run_id}/{test_name}"
        remote_test_src = f"{remote_tests_root}/{test_name}"
        remote.run_command(
            f"rm -rf {shlex.quote(remote_test_work)} && cp -r {shlex.quote(remote_test_src)} {shlex.quote(remote_test_work)}",
            remote_cwd="/tmp",
            log_path=pipeline_log_path,
            append_log=True,
        )

        # Fetch metadata files from the remote checkout. These drive check
        # definitions (.rt) and element type resolution (.in). None of them
        # should ever be read from the local regtests working tree.
        meta_dir = meta_root / test_name
        meta_dir.mkdir(parents=True, exist_ok=True)

        # Accumulates per-test SSH/SFTP failures so _build_simulation can
        # distinguish transport flakes from genuinely broken metrics.
        transport_errors: list[str] = []

        rt_file = meta_dir / f"{test_name}.rt"
        # .rt is optional (legacy tests without checks still run); only
        # transport failures are noteworthy.
        rt_status, rt_detail = remote.fetch_file_status(
            f"{remote_test_src}/{test_name}.rt", rt_file
        )
        if rt_status == "transport_error":
            transport_errors.append(f"{test_name}.rt: {rt_detail}")
            _append_pipeline_line(
                pipeline_log_path,
                f"[regression] WARNING: transport error fetching {test_name}.rt: {rt_detail}",
            )

        in_file_local = meta_dir / f"{test_name}.in"
        in_status, in_detail = remote.fetch_file_status(
            f"{remote_test_src}/{test_name}.in", in_file_local
        )
        if in_status == "transport_error":
            transport_errors.append(f"{test_name}.in: {in_detail}")
            _append_pipeline_line(
                pipeline_log_path,
                f"[regression] WARNING: transport error fetching {test_name}.in: {in_detail}",
            )
        elif in_status == "absent":
            _append_pipeline_line(
                pipeline_log_path,
                f"[regression] WARNING: {test_name}.in missing on remote.",
            )

        local_reference_dir = work_test_dir / "reference"
        local_reference_dir.mkdir(parents=True, exist_ok=True)
        test_log_local = work_test_dir / f"{test_name}-RT.log"
        test_log_run = paths.logs_dir / f"{test_name}-RT.log"

        cmd = _build_opalx_run_command(
            opalx_exe=remote_opalx_exe,
            input_name=f"{test_name}.in",
            mpi_ranks=mpi_ranks,
            opalx_info_level=opalx_info_level,
            opalx_args=cfg.opalx_args,
            launcher="none" if use_slurm else "mpirun",
        )
        _append_pipeline_line(
            pipeline_log_path,
            f"[regression] {test_name} generated command: {cmd}",
        )

        _append_pipeline_line(pipeline_log_path, f"[regression] START {test_name}")
        test_start = time.monotonic()

        rc = remote.run_command(
            cmd,
            remote_cwd=remote_test_work,
            log_path=test_log_local,
            cancel_event=cancel_event,
            slurm_step_ranks=mpi_ranks if use_slurm else None,
            slurm_step_args=slurm_step_args if use_slurm else None,
        )

        if test_log_local.exists():
            shutil.copy2(test_log_local, test_log_run)

        # Discover which stat files actually exist on the remote for both the
        # run work dir (generated) and the regtests reference dir. One SSH
        # round-trip each; we look for the legacy {test}.stat and the
        # multi-beam {test}_c*.stat variants in the same find invocation.
        #
        # If the underlying ``find`` transport fails (not a non-zero rc, but
        # an SSH exception), we flag a transport error so the caller can
        # escalate the test state away from "broken".
        def _list_remote_stats(remote_dir: str) -> list[str]:
            pattern = (
                f"find {shlex.quote(remote_dir)} -maxdepth 1 -type f "
                f"\\( -name {shlex.quote(test_name + '.stat')} "
                f"-o -name {shlex.quote(test_name + '_c*.stat')} \\) -print "
                f"2>/dev/null || true"
            )
            try:
                res = remote.conn.run(pattern, hide=True, warn=True)
            except Exception as exc:
                transport_errors.append(
                    f"stat listing on {remote_dir}: {exc}"
                )
                return []
            if res.return_code != 0:
                return []
            return [
                line.strip().split("/")[-1]
                for line in res.stdout.splitlines()
                if line.strip()
            ]

        generated_basenames = _list_remote_stats(remote_test_work)
        reference_basenames = _list_remote_stats(f"{remote_test_src}/reference")

        # Fall back to legacy names so the runner still attempts a fetch on
        # crashed runs where find returned nothing — keeps behavior the same
        # as before for failing single-beam tests.
        if not generated_basenames:
            generated_basenames = [f"{test_name}.stat"]
        if not reference_basenames:
            reference_basenames = [f"{test_name}.stat"]

        for fname in generated_basenames:
            status, detail = remote.fetch_file_status(
                f"{remote_test_work}/{fname}", work_test_dir / fname
            )
            if status == "transport_error":
                transport_errors.append(f"generated {fname}: {detail}")
                _append_pipeline_line(
                    pipeline_log_path,
                    f"[regression] WARNING: transport error fetching {fname}: {detail}",
                )
            elif status == "absent":
                # Genuinely missing — _build_simulation will mark the affected
                # metrics as "broken" / "crashed" based on the exit code.
                pass

        for fname in reference_basenames:
            status, detail = remote.fetch_file_status(
                f"{remote_test_src}/reference/{fname}",
                local_reference_dir / fname,
            )
            if status == "transport_error":
                transport_errors.append(f"reference {fname}: {detail}")
                _append_pipeline_line(
                    pipeline_log_path,
                    f"[regression] WARNING: transport error fetching reference {fname}: {detail}",
                )

        # Try to fetch the element positions files for beamline visualization.
        # Attempt both the legacy single-beam name and any per-container
        # variants. We pull both the `.txt` (drives the 2D SVG) and the `.py`
        # (drives the interactive 3D mesh JSON), since extraction runs locally
        # and so works even if the remote has no Python beyond what OPALX
        # itself uses.
        positions_dir = work_test_dir / "data"
        positions_dir.mkdir(parents=True, exist_ok=True)
        positions_list_cmd = (
            f"find {shlex.quote(remote_test_work + '/data')} -maxdepth 1 -type f "
            f"\\( -name '*_ElementPositions.txt' -o -name '*_ElementPositions.py' \\) "
            f"-print 2>/dev/null || true"
        )
        positions_res = remote.conn.run(positions_list_cmd, hide=True, warn=True)
        remote_positions_files = [
            line.strip()
            for line in positions_res.stdout.splitlines()
            if line.strip()
        ] if positions_res.return_code == 0 else []
        if not remote_positions_files:
            remote_positions_files = [
                f"{remote_test_work}/data/{test_name}_ElementPositions.txt"
            ]
        for remote_positions in remote_positions_files:
            try:
                remote.fetch_file(
                    remote_positions,
                    positions_dir / Path(remote_positions).name,
                )
            except Exception:
                pass  # Not critical — beamline SVG will simply be skipped if absent

        # Use the remote-fetched .in file for element type resolution.
        in_file = in_file_local if in_file_local.exists() else None
        sim = _build_simulation(
            test_name=test_name,
            rc=rc,
            rt_file=rt_file,
            work_test_dir=work_test_dir,
            reference_dir=local_reference_dir,
            plots_dir=paths.plots_dir,
            pipeline_log_path=pipeline_log_path,
            test_start=test_start,
            input_file=in_file,
            log_path=test_log_run,
            transport_errors=transport_errors,
        )
        report.simulations.append(sim)
        metric_count = sum(len(c.metrics) for c in sim.containers)
        end_extra = f" signal={sim.crash_signal}" if sim.crash_signal else ""
        duration_ms = int((time.monotonic() - test_start) * 1000)
        _append_pipeline_line(
            pipeline_log_path,
            f"[regression] END {test_name} state={sim.state} duration_ms={duration_ms} metrics={metric_count}{end_extra}",
        )
        reg_lines.append(f"{test_name}: {sim.state} ({metric_count} checks)")

    if not cfg.keep_work_dirs and paths.work_dir.exists():
        shutil.rmtree(paths.work_dir)
        _append_pipeline_line(pipeline_log_path, "[regression] Removed temporary work directory.")

    paths.reg_log_path.write_text("\n".join(reg_lines) + "\n", encoding="utf-8")
    return report
