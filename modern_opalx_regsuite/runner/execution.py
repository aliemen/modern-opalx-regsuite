"""Low-level execution utilities: command running, env activation, path management."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from ..config import EnvActivation
from ..data_model import run_dir


_LMOD_INIT_CANDIDATES = [
    "/usr/share/lmod/lmod/init/bash",
    "/etc/profile.d/lmod.sh",
]


def _find_lmod_init() -> Optional[str]:
    for p in _LMOD_INIT_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def _build_local_env(
    env_activation: EnvActivation,
    pipeline_log_path: Path,
) -> dict[str, str]:
    """Return an environment dict for local runs based on an EnvActivation.

    Supports all three styles ("none", "modules", "prologue") so local
    execution has parity with remote. The prologue style runs the user's
    free-form shell command (e.g. ``uenv start ...``) in a fresh bash
    subshell, then captures the resulting environment via ``env -0``.
    """
    if env_activation.style == "none":
        return os.environ.copy()

    parts: list[str] = []

    if env_activation.style == "modules":
        if not env_activation.module_loads:
            return os.environ.copy()
        lmod_init = env_activation.lmod_init or _find_lmod_init()
        if not lmod_init or not os.path.isfile(lmod_init):
            # Fall back to autodetection if the configured path is missing.
            fallback = _find_lmod_init()
            if not fallback:
                _append_pipeline_line(
                    pipeline_log_path,
                    "[env] WARNING: lmod init script not found; skipping module loads.",
                )
                return os.environ.copy()
            lmod_init = fallback
        parts.append(f"source {shlex.quote(lmod_init)}")
        for p in env_activation.module_use_paths:
            parts.append(f"module use {shlex.quote(p)}")
        for m in env_activation.module_loads:
            parts.append(f"module load {shlex.quote(m)}")
        _append_pipeline_line(
            pipeline_log_path,
            f"[env] modules: {', '.join(env_activation.module_loads)}",
        )

    elif env_activation.style == "prologue":
        if not env_activation.prologue:
            return os.environ.copy()
        parts.append(env_activation.prologue)
        _append_pipeline_line(pipeline_log_path, "[env] prologue activated")

    parts.append("env -0")
    script = " && ".join(parts)
    proc = subprocess.run(["bash", "-c", script], capture_output=True)
    if proc.returncode != 0:
        _append_pipeline_line(
            pipeline_log_path,
            f"[env] WARNING: activation failed (rc={proc.returncode}); using base env.\n"
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


def _run_command(
    cmd: str,
    cwd: Path,
    log_path: Path,
    pipeline_log_path: Path | None = None,
    env: Optional[dict[str, str]] = None,
    append_log: bool = False,
    cancel_event: Optional[threading.Event] = None,
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

    # Watchdog: kill the subprocess as soon as cancel_event is set.
    if cancel_event is not None:
        def _watchdog() -> None:
            cancel_event.wait()
            proc.kill()
        threading.Thread(target=_watchdog, daemon=True).start()

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
