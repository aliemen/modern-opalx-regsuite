from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from modern_opalx_regsuite.config import EnvActivation
from modern_opalx_regsuite.remote import RemoteExecutor


class _FakeTransport:
    def is_active(self) -> bool:
        return True

    def close(self) -> None:
        pass


class _FakeConnection:
    def __init__(self) -> None:
        self.transport = _FakeTransport()
        self.commands: list[str] = []

    def run(self, cmd: str, **_kwargs):
        self.commands.append(cmd)
        return SimpleNamespace(return_code=0, stdout="", stderr="")


def _executor_with_allocation(env: EnvActivation | None = None) -> tuple[RemoteExecutor, _FakeConnection]:
    conn = _FakeConnection()
    executor = RemoteExecutor.__new__(RemoteExecutor)
    executor._conn = conn
    executor._gateway_conn = None
    executor._gateway = None
    executor._gateway_process = None
    executor._tunnel_proc = None
    executor._control_path = None
    executor._allocation_id = "12345"
    executor._slurm_cluster = None
    executor._env = env
    executor._command_timeout = 0
    executor._pipeline_log_path = None
    executor._connection_name = "daint"
    return executor, conn


def test_allocated_non_step_command_stays_outside_srun(tmp_path: Path) -> None:
    executor, conn = _executor_with_allocation(
        EnvActivation(style="uenv", prologue="--view=develop /uenv/image.squashfs")
    )

    rc = executor.run_command(
        "git fetch origin",
        remote_cwd="/work/repo",
        log_path=tmp_path / "git.log",
    )

    assert rc == 0
    assert len(conn.commands) == 1
    assert "srun --jobid" not in conn.commands[0]
    assert "uenv run --view=develop /uenv/image.squashfs -- git fetch origin" in conn.commands[0]


def test_allocated_slurm_step_command_uses_srun_ranks(tmp_path: Path) -> None:
    executor, conn = _executor_with_allocation(
        EnvActivation(style="uenv", prologue="--view=develop /uenv/image.squashfs")
    )

    rc = executor.run_command(
        "/build/src/opalx Generated.in --info 2",
        remote_cwd="/work/Generated",
        log_path=tmp_path / "opalx.log",
        slurm_step_ranks=2,
    )

    assert rc == 0
    assert len(conn.commands) == 1
    assert conn.commands[0].startswith(
        "srun --jobid=12345 -n 2 --overlap --uenv=/uenv/image.squashfs --view=develop"
    )
    assert "uenv run" not in conn.commands[0]
    assert "/build/src/opalx Generated.in --info 2" in conn.commands[0]
