"""Local and remote regression test executors.

Both variants share ``_build_simulation`` for post-processing (stat parsing,
delta computation, plot generation, and RegressionSimulation assembly).
"""
from __future__ import annotations

import os
import shlex
import shutil
import signal as _signal
import time
import threading
from pathlib import Path
from typing import Optional

from ..config import Connection, SuiteConfig
from ..data_model import (
    RegressionContainer,
    RegressionMetric,
    RegressionSimulation,
    RegressionTestsReport,
)
from .execution import RunPaths, _append_pipeline_line, _run_command
from .parsing.regression import (
    _compute_delta,
    _discover_regression_tests,
    _discover_regression_tests_remote,
    _enumerate_stat_containers,
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


def _classify_crash(rc: int, log_path: Path) -> tuple[Optional[str], Optional[str]]:
    """Return (signal_name, crash_summary) when *rc* indicates a signal kill.

    On POSIX, Python's subprocess sets returncode to ``-N`` when the child was
    killed by signal N.  We extract the signal name and, if present, the MPI
    signal-fault block from the log file.
    """
    if rc >= 0:
        return None, None
    try:
        sig_name = _signal.Signals(abs(rc)).name   # e.g. "SIGSEGV"
    except ValueError:
        sig_name = f"SIG{abs(rc)}"
    crash_summary: Optional[str] = None
    if log_path.exists():
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
            start = text.find("*** Process received signal ***")
            end   = text.find("*** End of error message ***")
            if start != -1:
                end_idx = (end + len("*** End of error message ***")) if end != -1 else start + 2000
                crash_summary = text[start:end_idx].strip()
        except OSError:
            pass
    return sig_name, crash_summary


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


def _plot_basename(test_name: str, container_id: Optional[str], var_name: str) -> str:
    """Generate plot filename. Single-beam keeps the legacy name unchanged so
    existing runs still render; multi-beam adds the container id."""
    if container_id is None:
        return f"{test_name}_{var_name}.svg"
    return f"{test_name}_{container_id}_{var_name}.svg"


def _build_container(
    test_name: str,
    container_id: Optional[str],
    rc: int,
    checks: list[tuple[str, str, float]],
    generated_stat: Path,
    reference_stat: Optional[Path],
    plots_dir: Path,
    pipeline_log_path: Path,
) -> tuple[RegressionContainer, bool]:
    """Build one RegressionContainer from a single stat file pair.

    Returns ``(container, any_stat_plots)``. ``any_stat_plots`` tells the
    caller whether at least one metric produced a comparison plot (used to
    gate beamline diagram generation).
    """
    metrics: list[RegressionMetric] = []
    any_stat_plots = False
    revision: Optional[str] = None

    if checks:
        for var_name, mode, eps in checks:
            rev, s_vals, values, unit = (
                _read_stat_data(generated_stat, var_name)
                if generated_stat.exists()
                else (None, [], [], None)
            )
            if rev and not revision:
                revision = rev
            _ref_rev, ref_s_vals, ref_values, _ = (
                _read_stat_data(reference_stat, var_name)
                if reference_stat is not None and reference_stat.exists()
                else (None, [], [], None)
            )
            delta = _compute_delta(mode, values, ref_values)

            state = "broken"
            if delta is not None:
                state = "passed" if delta < eps else "failed"
            elif rc < 0:
                state = "crashed"
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
                any_stat_plots = True
                plot_name = _plot_basename(test_name, container_id, var_name)
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
                    tag = f"{test_name}:{var_name}" if container_id is None else f"{test_name}[{container_id}]:{var_name}"
                    _append_pipeline_line(
                        pipeline_log_path,
                        f"[regression] plot failed for {tag}: {exc}",
                    )

            current_value = values[-1] if values else None
            reference_value = ref_values[-1] if ref_values else None
            metrics.append(
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
        if rc == 0 and has_stat:
            state = "passed"
        elif rc < 0:
            state = "crashed"
        elif rc != 0:
            state = "failed"
        else:
            state = "broken"
        metrics.append(
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

    container_state = "passed"
    if any(m.state == "failed" for m in metrics):
        container_state = "failed"
    elif any(m.state == "crashed" for m in metrics):
        container_state = "crashed"
    elif any(m.state == "broken" for m in metrics):
        container_state = "broken"

    return (
        RegressionContainer(
            id=container_id,
            state=container_state,
            metrics=metrics,
            revision=revision,
        ),
        any_stat_plots,
    )


def _build_simulation(
    test_name: str,
    rc: int,
    rt_file: Path,
    work_test_dir: Path,
    reference_dir: Path,
    plots_dir: Path,
    pipeline_log_path: Path,
    test_start: float,
    input_file: Optional[Path] = None,
    log_path: Optional[Path] = None,
    transport_errors: Optional[list[str]] = None,
) -> RegressionSimulation:
    """Shared post-processing: parse .rt, discover per-container stat files,
    build one RegressionContainer per (generated, reference) pair, and roll
    up simulation-level state.

    For single-beam runs, ``containers`` is exactly one entry with ``id=None``
    so the frontend can trivially detect "render like before".
    """
    crash_signal, crash_summary = _classify_crash(
        rc, log_path or work_test_dir / f"{test_name}-RT.log"
    )

    description, checks = _parse_rt_file(rt_file)

    generated_pairs = _enumerate_stat_containers(work_test_dir, test_name)
    reference_pairs = _enumerate_stat_containers(reference_dir, test_name)
    ref_by_id: dict[Optional[str], Path] = {cid: p for cid, p in reference_pairs}

    containers: list[RegressionContainer] = []
    any_stat_plots = False

    if generated_pairs:
        # Normal path: at least one stat file was produced.
        pairs = generated_pairs
    elif reference_pairs:
        # Run crashed/failed and produced no stat files, but we know which
        # containers were expected from the reference side. Fabricate empty
        # generated paths so `_build_container` still marks metrics broken /
        # crashed with the right container ids.
        pairs = [(cid, work_test_dir / p.name) for cid, p in reference_pairs]
    else:
        # No stat files anywhere — fall back to a single legacy container so
        # the simulation row still shows up (with broken/crashed state).
        legacy = work_test_dir / f"{test_name}.stat"
        pairs = [(None, legacy)]

    for container_id, generated_stat in pairs:
        reference_stat = ref_by_id.get(container_id)
        if reference_stat is None and container_id is None and reference_pairs:
            # Generated side has no container suffix but reference side does
            # (unusual): pick the first reference so we don't silently lose data.
            reference_stat = reference_pairs[0][1]
        container, had_plots = _build_container(
            test_name=test_name,
            container_id=container_id,
            rc=rc,
            checks=checks,
            generated_stat=generated_stat,
            reference_stat=reference_stat,
            plots_dir=plots_dir,
            pipeline_log_path=pipeline_log_path,
        )
        containers.append(container)
        any_stat_plots = any_stat_plots or had_plots

    # Simulation-level rollup: worst-wins across every container's metrics.
    sim_state = "passed"
    all_metric_states = [m.state for c in containers for m in c.metrics]
    if any(s == "failed" for s in all_metric_states):
        sim_state = "failed"
    elif any(s == "crashed" for s in all_metric_states):
        sim_state = "crashed"
    elif any(s == "broken" for s in all_metric_states):
        sim_state = "broken"

    # Transport-level failures during metadata/stat fetch must not be silently
    # labelled "broken" — that reads like a test problem when it is really an
    # infrastructure problem. If the remote fetch step reported any errors and
    # the current rollup state is the quietest side of the spectrum, escalate
    # to "failed" and record the cause in crash_summary so the frontend shows
    # it next to the test row.
    if transport_errors:
        if sim_state in ("passed", "broken"):
            sim_state = "failed"
        combined = "SSH transport error(s) while fetching test outputs:\n  - " + \
            "\n  - ".join(transport_errors)
        crash_summary = (
            f"{crash_summary}\n\n{combined}" if crash_summary else combined
        )

    # --- Beamline visualization -------------------------------------------
    # Look for the ElementPositions.txt file that OPALX writes to a data/
    # subdirectory in the work dir. Multi-beam runs may emit per-container
    # variants (e.g. *_c0_ElementPositions.txt); we pick the first sorted
    # match since the beamline geometry is shared across containers.
    beamline_plot: Optional[str] = None
    data_dir = work_test_dir / "data"
    positions_file: Optional[Path] = next(
        iter(sorted(data_dir.glob("*_ElementPositions.txt"))), None
    ) if data_dir.is_dir() else None
    if positions_file is None:
        positions_file = next(
            iter(sorted(work_test_dir.glob("*_ElementPositions.txt"))), None
        )

    if positions_file is not None and any_stat_plots:
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
        containers=containers,
        duration_seconds=time.monotonic() - test_start,
        beamline_plot=beamline_plot,
        exit_code=rc,
        crash_signal=crash_signal,
        crash_summary=crash_summary,
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
        reference_dir = src_test_dir / "reference"

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
            timeout_seconds=cfg.per_test_timeout_seconds,
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
            work_test_dir=work_test_dir,
            reference_dir=reference_dir,
            plots_dir=paths.plots_dir,
            pipeline_log_path=pipeline_log_path,
            test_start=test_start,
            input_file=in_file,
            log_path=test_log_local,
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
    remote_opalx_dir = str(Path(remote_opalx_exe).parent)
    remote_tests_root = f"{remote_base}/regtests/{cfg.regtests_subdir}"

    tests = _discover_regression_tests_remote(remote, remote_tests_root)
    report = RegressionTestsReport(simulations=[])

    # Scratch area for fetched metadata (rt/in/reference) so _build_simulation
    # can parse them locally.  Lives under work_dir so `keep_work_dirs`
    # preserves it for debugging and the normal cleanup sweep removes it.
    meta_root = paths.work_dir / "_remote_meta"
    meta_root.mkdir(parents=True, exist_ok=True)

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

        # Fetch metadata files from the remote checkout.  These drive command
        # selection (.local presence), check definitions (.rt), and element
        # type resolution (.in).  None of them should ever be read from the
        # local regtests working tree.
        meta_dir = meta_root / test_name
        meta_dir.mkdir(parents=True, exist_ok=True)

        has_local_script = remote.path_exists(f"{remote_test_src}/{test_name}.local")

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

        env = {"OPALX_EXE_PATH": remote_opalx_dir}

        if has_local_script:
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
            cancel_event=cancel_event,
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

        # Try to fetch the element positions file for beamline visualization.
        # Attempt both the legacy single-beam name and any per-container
        # variants; the beamline SVG only needs one.
        positions_dir = work_test_dir / "data"
        positions_dir.mkdir(parents=True, exist_ok=True)
        positions_list_cmd = (
            f"find {shlex.quote(remote_test_work + '/data')} -maxdepth 1 -type f "
            f"-name '*_ElementPositions.txt' -print 2>/dev/null || true"
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
            log_path=test_log_local,
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
