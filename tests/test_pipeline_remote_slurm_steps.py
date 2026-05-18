from __future__ import annotations

from pathlib import Path
from typing import Any

from modern_opalx_regsuite.config import (
    ArchConfig,
    Connection,
    SlurmConfig,
    SuiteConfig,
)
from modern_opalx_regsuite.runner import pipeline


class _FakeRemote:
    def __init__(self) -> None:
        self.allocation_args: list[str] | None = None
        self.commands: list[dict[str, Any]] = []
        self.closed = False

    def allocate_slurm_job(self, slurm_args: list[str]) -> str:
        self.allocation_args = list(slurm_args)
        return "12345"

    def ensure_dir(self, _remote_path: str) -> None:
        pass

    def run_command(self, cmd: str, **kwargs: Any) -> int:
        self.commands.append({"cmd": cmd, **kwargs})
        return 0

    def cleanup(self, _remote_path: str) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def test_remote_slurm_pipeline_runs_cmake_and_build_inside_job_step(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_remote = _FakeRemote()
    cfg = SuiteConfig(
        opalx_repo_root=tmp_path / "opalx",
        builds_root=tmp_path / "builds",
        data_root=tmp_path / "data",
        regtests_repo_root=tmp_path / "regtests",
        arch_configs=[
            ArchConfig(
                arch="gpu-slurm",
                slurm=SlurmConfig(
                    time="00:05:00",
                    tasks_per_node=1,
                    cpus_per_task=4,
                ),
            )
        ],
    )
    connection = Connection(
        name="daint",
        host="daint.example",
        user="runner",
        key_name="cluster-key",
        work_dir="/remote/opalx-regsuite",
    )

    monkeypatch.setattr(
        pipeline,
        "create_remote_executor",
        lambda **_kwargs: (
            fake_remote,
            "/remote/opalx-regsuite",
            "/remote/opalx-regsuite/builds/master/gpu-slurm/build",
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "sync_repositories",
        lambda **_kwargs: (True, True),
    )

    meta = pipeline.run_pipeline(
        cfg=cfg,
        branch="master",
        arch="gpu-slurm",
        run_id="remote-slurm-build",
        skip_unit=True,
        skip_regression=True,
        connection=connection,
        target_key_path=tmp_path / "cluster-key.pem",
    )

    cmake_call = next(
        call for call in fake_remote.commands if call["cmd"].startswith("cmake ")
    )
    build_call = next(
        call for call in fake_remote.commands if call["cmd"] == "make -j2"
    )

    assert meta.status == "passed"
    assert fake_remote.allocation_args is not None
    assert cmake_call["slurm_step_ranks"] == 1
    assert build_call["slurm_step_ranks"] == 1
    assert "slurm_step_args" not in cmake_call
    assert "slurm_step_args" not in build_call
    assert fake_remote.closed is True
