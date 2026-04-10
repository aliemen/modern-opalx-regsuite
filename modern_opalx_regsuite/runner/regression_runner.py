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
from ..data_model import (
    RegressionMetric,
    RegressionSimulation,
    RegressionTestsReport,
)
from .execution import RunPaths, _append_pipeline_line, _run_command
from .parsing.regression import (
    _compute_delta,
    _discover_regression_tests,
    _extract_local_run_command,
    _parse_rt_file,
    _read_stat_data,
)
from .plotting import _write_stat_plot
from ..beamline_viz import generate_beamline_svg


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


def _wrap_command_with_mpirun_srun_shim(cmd: str) -> str:
    """Wrap *cmd* so legacy ``mpirun`` calls transparently map to ``srun``.

    Some cluster environments (for example CSCS uenv setups) provide ``srun``
    in Slurm allocations but no ``mpirun``. Legacy regression ``*.local``
    scripts still call ``mpirun`` directly, so we synthesize a tiny local
    ``mpirun`` shim in the test work dir and prepend ``$PWD`` to ``PATH``.
    """
    shim_script = (
        "cat > mpirun <<'OPALX_MPIRUN_SHIM'\n"
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == \"-np\" || \"${1:-}\" == \"-n\" || \"${1:-}\" == \"--np\" ]]; then\n"
        "  ranks=\"${2:-1}\"\n"
        "  shift 2\n"
        "  exec srun -n \"$ranks\" \"$@\"\n"
        "fi\n"
        "exec srun \"$@\"\n"
        "OPALX_MPIRUN_SHIM\n"
        "chmod +x mpirun\n"
        "PATH=\"$PWD:$PATH\"\n"
        f"{cmd}\n"
    )
    return f"bash -lc {shlex.quote(shim_script)}"


def _build_simulation(
    test_name: str,
    rc: int,
    rt_file: Path,
    generated_stat: Path,
    reference_stat: Path,
    plots_dir: Path,
    pipeline_log_path: Path,
    test_start: float,
    input_file: Optional[Path] = None,
) -> RegressionSimulation:
    """Shared post-processing: parse .rt, read stats, compute deltas, plot, assemble result."""
    description, checks = _parse_rt_file(rt_file)
    sim_metrics: list[RegressionMetric] = []

    if checks:
        for var_name, mode, eps in checks:
            rev, s_vals, values, unit = (
                _read_stat_data(generated_stat, var_name)
                if generated_stat.exists()
                else (None, [], [], None)
            )
            _ref_rev, ref_s_vals, ref_values, _ = (
                _read_stat_data(reference_stat, var_name)
                if reference_stat.exists()
                else (None, [], [], None)
            )
            delta = _compute_delta(mode, values, ref_values)

            state = "broken"
            if delta is not None:
                state = "passed" if delta < eps else "failed"
            elif rc != 0:
                state = "failed"

            plot_rel: Optional[str] = None
            can_plot = (
                s_vals
                and values
                and ref_s_vals
                and ref_values
                and len(s_vals) == len(values)
                and len(ref_s_vals) == len(ref_values)
                and min(len(values), len(ref_values)) > 1
            )
            if can_plot:
                plot_name = f"{test_name}_{var_name}.svg"
                plot_path = plots_dir / plot_name
                try:
                    _write_stat_plot(
                        s_vals=s_vals,
                        values=values,
                        ref_s_vals=ref_s_vals,
                        ref_values=ref_values,
                        out_path=plot_path,
                        test_name=test_name,
                        var_name=var_name,
                        var_unit=unit or "",
                    )
                    plot_rel = f"plots/{plot_name}"
                except Exception as exc:
                    _append_pipeline_line(
                        pipeline_log_path,
                        f"[regression] plot failed for {test_name}:{var_name}: {exc}",
                    )

            current_value = values[-1] if values else None
            reference_value = ref_values[-1] if ref_values else None
            sim_metrics.append(
                RegressionMetric(
                    metric=var_name,
                    mode=mode,
                    eps=eps,
                    delta=delta,
                    state=state,
                    reference_value=reference_value,
                    current_value=current_value,
                    plot=plot_rel,
                )
            )
    else:
        # Legacy: no .rt file — presence of stat file is the only check.
        has_stat = generated_stat.exists()
        state = "passed" if rc == 0 and has_stat else ("failed" if rc != 0 else "broken")
        sim_metrics.append(
            RegressionMetric(
                metric="run",
                mode="presence",
                eps=None,
                delta=None,
                state=state,
                reference_value=None,
                current_value=None,
                plot=None,
            )
        )

    sim_state = "passed"
    if any(m.state == "failed" for m in sim_metrics):
        sim_state = "failed"
    elif any(m.state == "broken" for m in sim_metrics):
        sim_state = "broken"

    # --- Beamline visualization -------------------------------------------
    # Look for the ElementPositions.txt file that OPALX writes to a data/
    # subdirectory next to the .stat file.
    beamline_plot: Optional[str] = None
    work_dir = generated_stat.parent
    data_dir = work_dir / "data"
    positions_file: Optional[Path] = next(
        data_dir.glob("*_ElementPositions.txt"), None
    ) if data_dir.is_dir() else None
    if positions_file is None:
        positions_file = next(work_dir.glob("*_ElementPositions.txt"), None)

    if positions_file is not None:
        beamline_out = plots_dir / f"{test_name}_beamline.svg"
        try:
            generate_beamline_svg(positions_file, input_file, beamline_out)
            beamline_plot = f"plots/{test_name}_beamline.svg"
        except Exception as exc:
            _append_pipeline_line(
                pipeline_log_path,
                f"[regression] beamline SVG failed for {test_name}: {exc}",
            )

    return RegressionSimulation(
        name=test_name,
        description=description,
        state=sim_state,
        # `.log` (not `.o`) so editors auto-open the file when downloaded.
        # The on-disk filenames in `_run_regression_suite[_remote]` use the
        # same suffix; if you change one, change the other.
        log_file=f"logs/{test_name}-RT.log",
        metrics=sim_metrics,
        duration_seconds=time.monotonic() - test_start,
        beamline_plot=beamline_plot,
    )


def _run_regression_suite(
    cfg: SuiteConfig,
    paths: RunPaths,
    build_dir: Path,
    pipeline_log_path: Path,
    mpi_ranks: int = 1,
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

        local_script = work_test_dir / f"{test_name}.local"
        test_input = work_test_dir / f"{test_name}.in"
        rt_file = work_test_dir / f"{test_name}.rt"
        generated_stat = work_test_dir / f"{test_name}.stat"
        reference_stat = src_test_dir / "reference" / f"{test_name}.stat"

        test_log_local = work_test_dir / f"{test_name}-RT.log"
        test_log_run = paths.logs_dir / f"{test_name}-RT.log"
        env = (base_env or os.environ).copy()
        env["OPALX_EXE_PATH"] = str(opalx_exe.parent)

        if local_script.is_file():
            os.chmod(local_script, 0o755)
            extra_args = " ".join(shlex.quote(a) for a in cfg.opalx_args)
            local_cmd = _extract_local_run_command(local_script)
            if local_cmd:
                _append_pipeline_line(
                    pipeline_log_path,
                    f"[regression] {test_name} local command: {local_cmd}",
                )
            cmd = f"bash {shlex.quote(local_script.name)}" + (
                f" {extra_args}" if extra_args else ""
            )
        else:
            extra_args = " ".join(shlex.quote(a) for a in cfg.opalx_args)
            mpi_prefix = f"mpirun -np {mpi_ranks} " if mpi_ranks > 1 else ""
            cmd = (
                f"{mpi_prefix}{shlex.quote(str(opalx_exe))} "
                f"{extra_args} {shlex.quote(test_input.name)}"
            ).strip()

        _append_pipeline_line(pipeline_log_path, f"[regression] START {test_name}")
        test_start = time.monotonic()
        rc, _output = _run_command(
            cmd,
            cwd=work_test_dir,
            log_path=test_log_local,
            pipeline_log_path=pipeline_log_path,
            env=env,
        )
        if test_log_local.exists():
            shutil.copy2(test_log_local, test_log_run)
            out_file = work_test_dir / f"{test_name}.out"
            if not out_file.exists():
                shutil.copy2(test_log_local, out_file)

        # Resolve the input file path so _build_simulation can look up element types
        in_file = test_input if test_input.exists() else (local_script if local_script.is_file() else None)
        sim = _build_simulation(
            test_name=test_name,
            rc=rc,
            rt_file=rt_file,
            generated_stat=generated_stat,
            reference_stat=reference_stat,
            plots_dir=paths.plots_dir,
            pipeline_log_path=pipeline_log_path,
            test_start=test_start,
            input_file=in_file,
        )
        report.simulations.append(sim)
        _append_pipeline_line(
            pipeline_log_path,
            f"[regression] END {test_name} state={sim.state} metrics={len(sim.metrics)}",
        )
        reg_lines.append(f"{test_name}: {sim.state} ({len(sim.metrics)} checks)")

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
    tests_root = cfg.resolved_regtests_repo_root / cfg.regtests_subdir
    tests = _discover_regression_tests(tests_root)
    report = RegressionTestsReport(simulations=[])

    remote_opalx_exe = f"{remote_build}/{cfg.opalx_executable_relpath}"
    remote_opalx_dir = str(Path(remote_opalx_exe).parent)
    remote_tests_root = f"{remote_base}/regtests/{cfg.regtests_subdir}"

    reg_lines: list[str] = [
        f"Running {len(tests)} regression tests remotely via [{connection.name}]"
    ]

    # Ensure the per-run work directory exists on the remote before any cp -r calls.
    remote_run_work_dir = f"{remote_base}/work/{run_id}"
    remote.ensure_dir(remote_run_work_dir)

    has_mpirun = (
        remote.run_command(
            "command -v mpirun >/dev/null 2>&1",
            remote_cwd=remote_run_work_dir,
            log_path=pipeline_log_path,
            append_log=True,
        )
        == 0
    )
    has_srun = (
        remote.run_command(
            "command -v srun >/dev/null 2>&1",
            remote_cwd=remote_run_work_dir,
            log_path=pipeline_log_path,
            append_log=True,
        )
        == 0
    )
    use_mpirun_shim = (not has_mpirun) and has_srun
    if use_mpirun_shim:
        _append_pipeline_line(
            pipeline_log_path,
            "[regression] mpirun not found on remote; using an srun-backed mpirun shim for legacy .local scripts.",
        )
    elif not has_mpirun:
        _append_pipeline_line(
            pipeline_log_path,
            "[regression] WARNING: neither mpirun nor srun detected on remote; regression runs may fail.",
        )

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
        work_test_dir.mkdir(parents=True, exist_ok=True)

        remote_test_work = f"{remote_base}/work/{run_id}/{test_name}"
        remote_test_src = f"{remote_tests_root}/{test_name}"
        remote.run_command(
            f"rm -rf {shlex.quote(remote_test_work)} && cp -r {shlex.quote(remote_test_src)} {shlex.quote(remote_test_work)}",
            remote_cwd="/tmp",
            log_path=pipeline_log_path,
            append_log=True,
        )

        local_script = src_test_dir / f"{test_name}.local"
        rt_file = src_test_dir / f"{test_name}.rt"
        reference_stat = src_test_dir / "reference" / f"{test_name}.stat"
        local_stat = work_test_dir / f"{test_name}.stat"
        test_log_local = work_test_dir / f"{test_name}-RT.log"
        test_log_run = paths.logs_dir / f"{test_name}-RT.log"

        env = {"OPALX_EXE_PATH": remote_opalx_dir}

        if local_script.is_file():
            extra_args = " ".join(shlex.quote(a) for a in cfg.opalx_args)
            cmd = f"bash {shlex.quote(test_name + '.local')}"
            if extra_args:
                cmd += f" {extra_args}"
            if use_mpirun_shim:
                cmd = _wrap_command_with_mpirun_srun_shim(cmd)
        else:
            extra_args = " ".join(shlex.quote(a) for a in cfg.opalx_args)
            if mpi_ranks > 1:
                mpi_prefix = (
                    f"srun -n {mpi_ranks} " if use_mpirun_shim else f"mpirun -np {mpi_ranks} "
                )
            else:
                mpi_prefix = ""
            cmd = (
                f"{mpi_prefix}{shlex.quote(remote_opalx_exe)} "
                f"{extra_args} {shlex.quote(test_name + '.in')}"
            ).strip()

        _append_pipeline_line(pipeline_log_path, f"[regression] START {test_name}")
        test_start = time.monotonic()

        rc = remote.run_command(
            cmd,
            remote_cwd=remote_test_work,
            log_path=test_log_local,
            env_vars=env,
        )

        if test_log_local.exists():
            shutil.copy2(test_log_local, test_log_run)

        remote_stat = f"{remote_test_work}/{test_name}.stat"
        try:
            remote.fetch_file(remote_stat, local_stat)
        except Exception as exc:
            _append_pipeline_line(
                pipeline_log_path,
                f"[regression] WARNING: could not fetch {test_name}.stat: {exc}",
            )

        # Try to fetch the element positions file for beamline visualization
        remote_positions = f"{remote_test_work}/data/{test_name}_ElementPositions.txt"
        local_positions = work_test_dir / "data" / f"{test_name}_ElementPositions.txt"
        try:
            local_positions.parent.mkdir(parents=True, exist_ok=True)
            remote.fetch_file(remote_positions, local_positions)
        except Exception:
            pass  # Not critical — beamline SVG will simply be skipped if absent

        # Use the source-side .in file for element type resolution
        src_in_file = src_test_dir / f"{test_name}.in"
        in_file = src_in_file if src_in_file.exists() else None
        sim = _build_simulation(
            test_name=test_name,
            rc=rc,
            rt_file=rt_file,
            generated_stat=local_stat,
            reference_stat=reference_stat,
            plots_dir=paths.plots_dir,
            pipeline_log_path=pipeline_log_path,
            test_start=test_start,
            input_file=in_file,
        )
        report.simulations.append(sim)
        _append_pipeline_line(
            pipeline_log_path,
            f"[regression] END {test_name} state={sim.state} metrics={len(sim.metrics)}",
        )
        reg_lines.append(f"{test_name}: {sim.state} ({len(sim.metrics)} checks)")

    if not cfg.keep_work_dirs and paths.work_dir.exists():
        shutil.rmtree(paths.work_dir)
        _append_pipeline_line(pipeline_log_path, "[regression] Removed temporary work directory.")

    paths.reg_log_path.write_text("\n".join(reg_lines) + "\n", encoding="utf-8")
    return report
