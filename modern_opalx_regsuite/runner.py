from __future__ import annotations

import json
import math
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from .config import ArchConfig, SuiteConfig
from .data_model import (
    RegressionMetric,
    RegressionSimulation,
    RegressionTestsReport,
    RunIndexEntry,
    RunMeta,
    UnitTestsReport,
    branches_index_path,
    run_dir,
    runs_index_path,
)


_LMOD_INIT_CANDIDATES = [
    "/usr/share/lmod/lmod/init/bash",
    "/etc/profile.d/lmod.sh",
]


def _find_lmod_init() -> Optional[str]:
    for p in _LMOD_INIT_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def _build_module_env(
    module_loads: list[str],
    module_use_paths: list[str],
    pipeline_log_path: Path,
) -> dict[str, str]:
    """Return an environment dict with the requested lmod modules loaded."""
    if not module_loads:
        return os.environ.copy()

    lmod_init = _find_lmod_init()
    if not lmod_init:
        _append_pipeline_line(
            pipeline_log_path,
            "[modules] WARNING: lmod init script not found; skipping module loads.",
        )
        return os.environ.copy()

    parts = [f"source {shlex.quote(lmod_init)}"]
    for p in module_use_paths:
        parts.append(f"module use {shlex.quote(p)}")
    for m in module_loads:
        parts.append(f"module load {shlex.quote(m)}")
    parts.append("env -0")

    script = " && ".join(parts)
    _append_pipeline_line(
        pipeline_log_path, f"[modules] Loading: {', '.join(module_loads)}"
    )
    proc = subprocess.run(["bash", "-c", script], capture_output=True)
    if proc.returncode != 0:
        _append_pipeline_line(
            pipeline_log_path,
            f"[modules] WARNING: module load failed (rc={proc.returncode}); using base env.\n"
            + proc.stderr.decode(errors="replace"),
        )
        return os.environ.copy()

    env: dict[str, str] = {}
    for item in proc.stdout.split(b"\0"):
        s = item.decode(errors="replace")
        if "=" in s:
            k, v = s.split("=", 1)
            env[k] = v
    return env


@dataclass
class RunPaths:
    root: Path
    logs_dir: Path
    plots_dir: Path
    work_dir: Path
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
    work_dir = root / "work"
    logs_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    return RunPaths(
        root=root,
        logs_dir=logs_dir,
        plots_dir=plots_dir,
        work_dir=work_dir,
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


def _start_pipeline_log(pipeline_log_path: Path, branch: str, arch: str, run_id: str) -> None:
    pipeline_log_path.parent.mkdir(parents=True, exist_ok=True)
    with pipeline_log_path.open("w", encoding="utf-8") as f:
        f.write(
            f"# OPALX regression run\n"
            f"branch={branch}\n"
            f"arch={arch}\n"
            f"run_id={run_id}\n"
            f"started_at={datetime.now(timezone.utc).isoformat()}Z\n\n"
        )


def _phase(pipeline_log_path: Path, name: str) -> None:
    """Emit a structured phase marker that the SSE tailer can detect."""
    _append_pipeline_line(pipeline_log_path, f"== PHASE: {name} ==")


def _git_update_repo(repo_path: Path, branch: str, pipeline_log_path: Path) -> bool:
    """Fetch, checkout, and pull a given branch if this looks like a git repo."""
    git_dir = repo_path / ".git"
    if not git_dir.exists():
        _append_pipeline_line(
            pipeline_log_path,
            f"[git] Skipping update; {repo_path} is not a git repository.",
        )
        return False

    def run_git(args: str) -> bool:
        cmd = f"git {args}"
        _append_pipeline_line(pipeline_log_path, f"[git] {cmd}")
        rc, _ = _run_command(
            cmd,
            cwd=repo_path,
            log_path=pipeline_log_path,
            pipeline_log_path=pipeline_log_path,
            append_log=True,
        )
        return rc == 0

    ok = True
    ok = run_git(f"fetch origin {branch}") and ok
    ok = run_git(f"checkout {branch}") and ok
    ok = run_git(f"pull --ff-only origin {branch}") and ok
    return ok


def _git_head_short(repo_path: Path) -> Optional[str]:
    git_dir = repo_path / ".git"
    if not git_dir.exists():
        return None
    proc = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(repo_path),
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _run_command(
    cmd: str,
    cwd: Path,
    log_path: Path,
    pipeline_log_path: Path | None = None,
    env: Optional[dict[str, str]] = None,
    append_log: bool = False,
) -> Tuple[int, str]:  # returncode, output
    cmd_list = shlex.split(cmd)
    proc = subprocess.Popen(
        cmd_list,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    lines: list[str] = []
    log_mode = "a" if append_log else "w"
    with log_path.open(log_mode, encoding="utf-8") as log_file, (
        pipeline_log_path.open("a", encoding="utf-8")
        if pipeline_log_path is not None and pipeline_log_path != log_path
        else open(os.devnull, "a", encoding="utf-8")
    ) as pipe_log:
        header = f"$ {cmd}\n"
        log_file.write(header)
        if pipeline_log_path is not None and pipeline_log_path != log_path:
            pipe_log.write(header)
        for line in proc.stdout:
            log_file.write(line)
            if pipeline_log_path is not None and pipeline_log_path != log_path:
                pipe_log.write(line)
            lines.append(line)
    proc.wait()
    return proc.returncode, "".join(lines)


def _parse_unit_output(output: str) -> UnitTestsReport:
    from .data_model import UnitTestCase

    _CTEST_LINE = re.compile(
        r"^\s*\d+/\d+\s+Test\s+#\d+:\s+(\S+)\s+\.+\s+"
        r"(Passed|\*{0,3}Failed\*{0,3}|Not Run)\s+([\d.]+)\s+sec",
    )
    cases: list[UnitTestCase] = []
    for line in output.splitlines():
        m = _CTEST_LINE.match(line)
        if m:
            name = m.group(1)
            raw_status = m.group(2).strip("*")
            status = "passed" if raw_status == "Passed" else "failed"
            duration = float(m.group(3))
            cases.append(UnitTestCase(name=name, status=status, duration_seconds=duration))

    if not cases:
        status = "passed"
        if "failed" in output.lower() or "error" in output.lower():
            status = "failed"
        cases.append(UnitTestCase(name="unit-suite", status=status, output_snippet=output[-4000:]))

    return UnitTestsReport(tests=cases)


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


def _discover_regression_tests(tests_root: Path) -> list[str]:
    tests: list[str] = []
    if not tests_root.is_dir():
        return tests
    for entry in sorted(tests_root.iterdir()):
        if entry.name.startswith(".") or not entry.is_dir():
            continue
        test = entry.name
        if (entry / "disabled").exists():
            continue
        if not (entry / f"{test}.in").is_file():
            continue
        if not (entry / "reference" / f"{test}.stat").is_file():
            continue
        tests.append(test)
    return tests


def _parse_rt_file(rt_path: Path) -> tuple[Optional[str], list[tuple[str, str, float]]]:
    if not rt_path.is_file():
        return None, []
    lines = [l.strip() for l in rt_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not lines:
        return None, []
    description = lines[0].strip().strip('"')
    checks: list[tuple[str, str, float]] = []
    for line in lines[1:]:
        if not line.startswith("stat"):
            continue
        m = re.match(r'^stat\s+"([^"]+)"\s+(\S+)\s+(\S+)\s*$', line)
        if not m:
            continue
        var = m.group(1)
        mode = m.group(2)
        try:
            eps = float(m.group(3))
        except ValueError:
            continue
        checks.append((var, mode, eps))
    return description, checks


def _extract_local_run_command(local_script: Path) -> Optional[str]:
    """Extract the effective run command from a legacy *.local script.

    These files usually contain:
    - shebang
    - cd to script directory
    - mpirun/opalx invocation
    """
    if not local_script.is_file():
        return None
    lines = local_script.read_text(encoding="utf-8", errors="replace").splitlines()
    for raw in reversed(lines):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("cd "):
            continue
        return line
    return None


def _parse_sdds_kv(block: str, key: str) -> Optional[str]:
    m = re.search(rf"{key}=([^,]+)", block)
    if not m:
        return None
    return m.group(1).strip().strip('"')


def _read_stat_data(path: Path, var_name: str) -> tuple[Optional[str], list[float], list[float], Optional[str]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    columns: dict[str, dict[str, int | str]] = {}
    params: dict[str, int] = {}

    i = 0
    while i < len(lines):
        line = lines[i]
        if "&column" in line:
            block = line
            while "&end" not in lines[i] and i + 1 < len(lines):
                i += 1
                block += lines[i]
            name = _parse_sdds_kv(block, "name")
            unit = _parse_sdds_kv(block, "units")
            if name:
                columns[name] = {"column": len(columns), "units": unit or ""}
        elif "&parameter" in line:
            block = line
            while "&end" not in lines[i] and i + 1 < len(lines):
                i += 1
                block += lines[i]
            name = _parse_sdds_kv(block, "name")
            if name:
                params[name] = len(params)
        elif "&data" in line:
            while "&end" not in lines[i] and i + 1 < len(lines):
                i += 1
            i += 1
            break
        i += 1

    header_lines = i
    rev_line = params.get("revision")
    revision: Optional[str] = None
    if rev_line is not None and header_lines + rev_line < len(lines):
        revision = lines[header_lines + rev_line]
        m = re.search(r"(.* git rev\. )#([A-Za-z0-9]{7})[A-Za-z0-9]*", revision)
        if m:
            revision = f"{m.group(1)}{m.group(2)}"

    if "s" not in columns or var_name not in columns:
        return revision, [], [], None

    s_col = int(columns["s"]["column"])
    var_col = int(columns[var_name]["column"])
    var_unit = str(columns[var_name].get("units", "")).strip('"')

    data_start = header_lines + len(params)
    s_vals: list[float] = []
    values: list[float] = []
    for row in lines[data_start:]:
        parts = row.split()
        if len(parts) <= max(s_col, var_col):
            continue
        try:
            s_vals.append(float(parts[s_col]))
            values.append(float(parts[var_col]))
        except ValueError:
            continue

    return revision, s_vals, values, var_unit


def _compute_delta(mode: str, values: list[float], ref_values: list[float]) -> Optional[float]:
    if not values or not ref_values or len(values) != len(ref_values):
        return None
    if mode == "last":
        return abs(values[-1] - ref_values[-1])
    if mode == "avg":
        sq = sum((values[i] - ref_values[i]) ** 2 for i in range(len(values)))
        return math.sqrt(sq) / len(values)
    return None


def _write_stat_plot(
    s_vals: list[float],
    values: list[float],
    ref_s_vals: list[float],
    ref_values: list[float],
    out_path: Path,
    test_name: str,
    var_name: str,
    var_unit: str,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax1 = plt.subplots(figsize=(9, 4.5))
    ax2 = ax1.twinx()
    n_common = min(len(values), len(ref_values))
    diffs = [values[i] - ref_values[i] for i in range(n_common)]

    ax1.plot(s_vals[: len(values)], values, label="current", linewidth=2)
    ref_s = ref_s_vals if len(ref_s_vals) == len(ref_values) else s_vals[: len(ref_values)]
    ax1.plot(ref_s, ref_values, label="reference", linewidth=2)
    ax2.plot(s_vals[:n_common], diffs, "--", color="grey", label="difference", linewidth=1.0)

    pretty_var = var_name.replace("_", "(")
    if "(" in pretty_var and not pretty_var.endswith(")"):
        pretty_var += ")"
    y_unit = f" [{var_unit}]" if var_unit else ""

    ax1.set_title(test_name)
    ax1.set_xlabel("s [m]")
    ax1.set_ylabel(f"{pretty_var}{y_unit}")
    ax2.set_ylabel(f"delta {pretty_var}{y_unit}")
    ax1.legend(loc="lower left")
    ax2.legend(loc="lower right")
    ax1.grid(True)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


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


def _run_regression_suite(
    cfg: SuiteConfig,
    paths: RunPaths,
    build_dir: Path,
    pipeline_log_path: Path,
    mpi_ranks: int = 1,
    cancel_event: Optional[threading.Event] = None,
    base_env: Optional[dict[str, str]] = None,
) -> RegressionTestsReport:
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

    reg_lines: list[str] = []
    reg_lines.append(f"Running {len(tests)} regression tests from {tests_root}")
    reg_lines.append(f"OPALX executable: {opalx_exe}")

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

        test_log_local = work_test_dir / f"{test_name}-RT.o"
        test_log_run = paths.logs_dir / f"{test_name}-RT.o"
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
            # Run via bash to preserve the exact script semantics.
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
        _test_start = time.monotonic()
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

        description, checks = _parse_rt_file(rt_file)
        sim_metrics: list[RegressionMetric] = []

        if checks:
            for var_name, mode, eps in checks:
                rev, s_vals, values, unit = _read_stat_data(generated_stat, var_name) if generated_stat.exists() else (None, [], [], None)
                _ref_rev, ref_s_vals, ref_values, _ = _read_stat_data(reference_stat, var_name) if reference_stat.exists() else (None, [], [], None)
                delta = _compute_delta(mode, values, ref_values)

                state = "broken"
                if delta is not None:
                    state = "passed" if delta < eps else "failed"
                elif rc != 0:
                    state = "failed"

                plot_rel: Optional[str] = None
                can_plot = (
                    s_vals and values and ref_s_vals and ref_values
                    and len(s_vals) == len(values)
                    and len(ref_s_vals) == len(ref_values)
                    and min(len(values), len(ref_values)) > 1
                )
                if can_plot:
                    plot_name = f"{test_name}_{var_name}.svg"
                    plot_path = paths.plots_dir / plot_name
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
            # Legacy behavior when .rt is absent: one synthetic check.
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

        sim = RegressionSimulation(
            name=test_name,
            description=description,
            state=sim_state,
            log_file=f"logs/{test_name}-RT.o",
            metrics=sim_metrics,
            duration_seconds=time.monotonic() - _test_start,
        )
        report.simulations.append(sim)
        _append_pipeline_line(
            pipeline_log_path,
            f"[regression] END {test_name} state={sim_state} metrics={len(sim_metrics)}",
        )
        reg_lines.append(f"{test_name}: {sim_state} ({len(sim_metrics)} checks)")

    if not cfg.keep_work_dirs and paths.work_dir.exists():
        shutil.rmtree(paths.work_dir)
        _append_pipeline_line(pipeline_log_path, "[regression] Removed temporary work directory.")

    paths.reg_log_path.write_text("\n".join(reg_lines) + "\n", encoding="utf-8")
    return report


def _run_regression_suite_remote(
    cfg: SuiteConfig,
    paths: RunPaths,
    ac: "ArchConfig",
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
    """
    tests_root = cfg.resolved_regtests_repo_root / cfg.regtests_subdir
    tests = _discover_regression_tests(tests_root)
    report = RegressionTestsReport(simulations=[])

    remote_opalx_exe = f"{remote_build}/{cfg.opalx_executable_relpath}"
    remote_opalx_dir = str(Path(remote_opalx_exe).parent)
    remote_tests_root = f"{remote_base}/regtests/{cfg.regtests_subdir}"

    reg_lines: list[str] = []
    reg_lines.append(f"Running {len(tests)} regression tests remotely on {ac.remote_host}")
    reg_lines.append(f"Remote OPALX executable: {remote_opalx_exe}")

    # Ensure the per-run work directory exists on the remote before any cp -r calls.
    remote_run_work_dir = f"{remote_base}/work/{run_id}"
    remote.ensure_dir(remote_run_work_dir)

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

        # Copy test directory on the remote.
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
        test_log_local = work_test_dir / f"{test_name}-RT.o"
        test_log_run = paths.logs_dir / f"{test_name}-RT.o"

        env = {"OPALX_EXE_PATH": remote_opalx_dir}

        if local_script.is_file():
            extra_args = " ".join(shlex.quote(a) for a in cfg.opalx_args)
            cmd = f"bash {shlex.quote(test_name + '.local')}"
            if extra_args:
                cmd += f" {extra_args}"
        else:
            extra_args = " ".join(shlex.quote(a) for a in cfg.opalx_args)
            mpi_prefix = f"mpirun -np {ac.mpi_ranks} " if ac.mpi_ranks > 1 else ""
            cmd = (
                f"{mpi_prefix}{shlex.quote(remote_opalx_exe)} "
                f"{extra_args} {shlex.quote(test_name + '.in')}"
            ).strip()

        _append_pipeline_line(pipeline_log_path, f"[regression] START {test_name}")
        _test_start = time.monotonic()

        rc = remote.run_command(
            cmd,
            remote_cwd=remote_test_work,
            log_path=test_log_local,
            module_loads=ac.module_loads or None,
            module_use_paths=cfg.module_use_paths or None,
            lmod_init=ac.remote_lmod_init,
            env=env,
        )

        # Copy log to run logs directory.
        if test_log_local.exists():
            shutil.copy2(test_log_local, test_log_run)

        # Fetch the .stat file from the remote.
        remote_stat = f"{remote_test_work}/{test_name}.stat"
        try:
            remote.fetch_file(remote_stat, local_stat)
        except Exception as exc:
            _append_pipeline_line(
                pipeline_log_path,
                f"[regression] WARNING: could not fetch {test_name}.stat: {exc}",
            )

        # --- Local processing (identical to _run_regression_suite) ---
        description, checks = _parse_rt_file(rt_file)
        sim_metrics: list[RegressionMetric] = []

        if checks:
            for var_name, mode, eps in checks:
                rev, s_vals, values, unit = (
                    _read_stat_data(local_stat, var_name)
                    if local_stat.exists()
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
                    plot_path = paths.plots_dir / plot_name
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
            has_stat = local_stat.exists()
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

        sim = RegressionSimulation(
            name=test_name,
            description=description,
            state=sim_state,
            log_file=f"logs/{test_name}-RT.o",
            metrics=sim_metrics,
            duration_seconds=time.monotonic() - _test_start,
        )
        report.simulations.append(sim)
        _append_pipeline_line(
            pipeline_log_path,
            f"[regression] END {test_name} state={sim_state} metrics={len(sim_metrics)}",
        )
        reg_lines.append(f"{test_name}: {sim_state} ({len(sim_metrics)} checks)")

    if not cfg.keep_work_dirs and paths.work_dir.exists():
        shutil.rmtree(paths.work_dir)
        _append_pipeline_line(pipeline_log_path, "[regression] Removed temporary work directory.")

    paths.reg_log_path.write_text("\n".join(reg_lines) + "\n", encoding="utf-8")
    return report


def _validate_remote_config(ac: ArchConfig) -> None:
    """Raise ValueError if required remote fields are missing."""
    missing = []
    if not ac.remote_host:
        missing.append("remote_host")
    if not ac.remote_user:
        missing.append("remote_user")
    if not ac.remote_key_name:
        missing.append("remote_key_name")
    if missing:
        raise ValueError(
            f"execution_mode='remote' for arch '{ac.arch}' requires: "
            + ", ".join(missing)
        )


def _get_repo_url(repo_path: Path, config_url: Optional[str]) -> str:
    """Resolve a git clone URL: use config value or derive from local origin."""
    if config_url:
        return config_url
    proc = subprocess.run(
        ["git", "-C", str(repo_path), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    raise ValueError(
        f"Cannot determine git URL for {repo_path}. "
        "Set opalx_repo_url / regtests_repo_url in config."
    )


def run_pipeline(
    cfg: SuiteConfig,
    branch: str,
    arch: str,
    run_id: Optional[str] = None,
    skip_unit: bool = False,
    skip_regression: bool = False,
    cancel_event: Optional[threading.Event] = None,
    execution_host: Optional[str] = None,
    execution_user: Optional[str] = None,
) -> RunMeta:
    """Run the full pipeline for a given branch/architecture.

    Pass *cancel_event* (a :class:`threading.Event`) to allow callers to
    interrupt the pipeline between phases.  The event is checked after git
    updates, after cmake+build, after unit tests, and between each regression
    test.
    """
    if run_id is None:
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    data_root = cfg.resolved_data_root
    paths = _ensure_run_paths(data_root, branch, arch, run_id)
    _start_pipeline_log(paths.pipeline_log_path, branch, arch, run_id)

    meta = RunMeta(
        branch=branch,
        arch=arch,
        run_id=run_id,
        started_at=datetime.now(timezone.utc),
        status="running",
        execution_host=execution_host,
        execution_user=execution_user,
    )
    _write_json(paths.meta_path, meta.model_dump())

    # Resolve arch-specific overrides.
    ac = cfg.get_arch_config(arch)
    effective_cmake_args = ac.cmake_args if ac.cmake_args is not None else cfg.cmake_args
    build_cmd = f"make -j{ac.build_jobs}"

    is_remote = ac.execution_mode == "remote"

    # ── Remote executor setup ────────────────────────────────────────────────
    remote: Optional["RemoteExecutor"] = None  # type: ignore[name-defined]
    remote_base: Optional[str] = None
    remote_build: Optional[str] = None

    if is_remote:
        from .remote import RemoteExecutor

        _validate_remote_config(ac)
        key_path = cfg.resolved_ssh_keys_dir / f"{ac.remote_key_name}.pem"
        if not key_path.exists():
            raise FileNotFoundError(f"SSH key not found: {key_path}")
        remote = RemoteExecutor(
            host=ac.remote_host,  # type: ignore[arg-type]
            user=ac.remote_user,  # type: ignore[arg-type]
            key_path=key_path,
            port=ac.remote_port,
            pipeline_log_path=paths.pipeline_log_path,
        )
        remote_base = ac.remote_work_dir
        remote_build = f"{remote_base}/builds/{branch}/{arch}/build"

    # Build the module environment once for this run (used by cmake, build, tests).
    module_env: Optional[dict[str, str]] = None
    if ac.module_loads and not is_remote:
        # For remote runs, module loading is handled inline by RemoteExecutor.
        module_env = _build_module_env(
            ac.module_loads,
            cfg.module_use_paths,
            paths.pipeline_log_path,
        )

    # Resolve repositories.
    opalx_repo = cfg.resolved_opalx_repo_root
    regtests_repo = cfg.resolved_regtests_repo_root

    # Determine build directory (local).
    build_dir = cfg.resolved_builds_root / branch / arch / "build"
    build_dir.mkdir(parents=True, exist_ok=True)

    try:
        if is_remote and remote is not None:
            remote.ensure_dir(remote_build)  # type: ignore[arg-type]

        # ── Phase: git ────────────────────────────────────────────────────────
        _phase(paths.pipeline_log_path, "git")

        # Local git update (always, for commit hash tracking).
        _append_pipeline_line(
            paths.pipeline_log_path, f"Updating OPALX repo at {opalx_repo}"
        )
        opalx_git_ok = _git_update_repo(
            repo_path=opalx_repo,
            branch=branch,
            pipeline_log_path=paths.pipeline_log_path,
        )
        _append_pipeline_line(
            paths.pipeline_log_path,
            f"Updating regression-tests repo at {regtests_repo} (branch {cfg.regtests_branch})",
        )
        reg_git_ok = _git_update_repo(
            repo_path=regtests_repo,
            branch=cfg.regtests_branch,
            pipeline_log_path=paths.pipeline_log_path,
        )
        meta.opalx_commit = _git_head_short(opalx_repo)
        meta.tests_repo_commit = _git_head_short(regtests_repo)
        _write_json(paths.meta_path, meta.model_dump())

        # Remote: clone or update repos via HTTPS.
        if is_remote and remote is not None:
            opalx_url = _get_repo_url(opalx_repo, cfg.opalx_repo_url)
            regtests_url = _get_repo_url(regtests_repo, cfg.regtests_repo_url)
            _append_pipeline_line(
                paths.pipeline_log_path,
                f"[remote] Cloning/updating OPALX on {ac.remote_host}",
            )
            remote_opalx_ok = remote.git_clone_or_update(
                opalx_url,
                f"{remote_base}/opalx-src",
                branch,
                log_path=paths.pipeline_log_path,
            )
            _append_pipeline_line(
                paths.pipeline_log_path,
                f"[remote] Cloning/updating regression-tests on {ac.remote_host}",
            )
            remote_regtests_ok = remote.git_clone_or_update(
                regtests_url,
                f"{remote_base}/regtests",
                cfg.regtests_branch,
                log_path=paths.pipeline_log_path,
            )
            if not (remote_opalx_ok and remote_regtests_ok):
                opalx_git_ok = False

        if cancel_event is not None and cancel_event.is_set():
            return _cancel_run(meta, paths, data_root)

        # ── Phase: cmake ──────────────────────────────────────────────────────
        _phase(paths.pipeline_log_path, "cmake")
        if is_remote and remote is not None:
            cmake_cmd = " ".join(
                ["cmake", *effective_cmake_args, shlex.quote(f"{remote_base}/opalx-src")]
            )
            _append_pipeline_line(
                paths.pipeline_log_path, f"[remote] Configuring build: {cmake_cmd}"
            )
            cmake_rc = remote.run_command(
                cmake_cmd,
                remote_cwd=remote_build,  # type: ignore[arg-type]
                log_path=paths.logs_dir / "cmake.log",
                module_loads=ac.module_loads or None,
                module_use_paths=cfg.module_use_paths or None,
                lmod_init=ac.remote_lmod_init,
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
            )

        # ── Phase: build ──────────────────────────────────────────────────────
        _phase(paths.pipeline_log_path, "build")
        _append_pipeline_line(paths.pipeline_log_path, f"Building: {build_cmd}")
        if is_remote and remote is not None:
            build_rc = remote.run_command(
                build_cmd,
                remote_cwd=remote_build,  # type: ignore[arg-type]
                log_path=paths.logs_dir / "build.log",
                module_loads=ac.module_loads or None,
                module_use_paths=cfg.module_use_paths or None,
                lmod_init=ac.remote_lmod_init,
            )
        else:
            build_rc, _ = _run_command(
                build_cmd,
                cwd=build_dir,
                log_path=paths.logs_dir / "build.log",
                pipeline_log_path=paths.pipeline_log_path,
                env=module_env,
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
                    module_loads=ac.module_loads or None,
                    module_use_paths=cfg.module_use_paths or None,
                    lmod_init=ac.remote_lmod_init,
                )
                output = paths.unit_log_path.read_text(
                    encoding="utf-8", errors="replace"
                )
            else:
                rc, output = _run_command(
                    cfg.unit_test_command,
                    cwd=build_dir,
                    log_path=paths.unit_log_path,
                    pipeline_log_path=paths.pipeline_log_path,
                    env=module_env,
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
            if is_remote and remote is not None:
                reg_report = _run_regression_suite_remote(
                    cfg=cfg,
                    paths=paths,
                    ac=ac,
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
            _append_pipeline_line(paths.pipeline_log_path, "[regression] Skipped because build failed.")

        _write_json(paths.reg_json_path, reg_report.model_dump())

        # Check one more time after regression (cancel may have fired mid-loop).
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
            # Full cleanup only if configured.
            if ac.remote_cleanup and remote_base is not None:
                remote.cleanup(remote_base)
            remote.close()


def _cancel_run(meta: RunMeta, paths: RunPaths, data_root: Path) -> RunMeta:
    """Finalise a cancelled run and persist it."""
    _append_pipeline_line(paths.pipeline_log_path, "== PHASE: done status=cancelled ==")
    meta.status = "cancelled"
    meta.finished_at = datetime.now(timezone.utc)
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
        execution_host=meta.execution_host,
        unit_tests_total=meta.unit_tests_total,
        unit_tests_failed=meta.unit_tests_failed,
        regression_total=meta.regression_total,
        regression_passed=meta.regression_passed,
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

