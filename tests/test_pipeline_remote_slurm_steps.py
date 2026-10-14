from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from modern_opalx_regsuite.config import (
    ArchConfig,
    Connection,
    SlurmConfig,
    SuiteConfig,
)
from modern_opalx_regsuite.data_model import (
    RegressionSimulation,
    RegressionTestsReport,
    SkipConfigSnapshot,
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


_CTEST_OUT = "1/1 Test #1: TestFast .........   Passed    0.10 sec\n"


def _local_cfg(tmp_path: Path, unit_cmd: str) -> SuiteConfig:
    return SuiteConfig(
        opalx_repo_root=tmp_path / "opalx",
        builds_root=tmp_path / "builds",
        data_root=tmp_path / "data",
        regtests_repo_root=tmp_path / "regtests",
        arch_configs=[ArchConfig(arch="cpu-serial")],
        unit_test_command=unit_cmd,
    )


def _patch_local(monkeypatch, commands: list[str], captured: dict) -> None:
    def fake_run_command(cmd, cwd, log_path, pipeline_log_path, **_kwargs):
        commands.append(cmd)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("ok\n", encoding="utf-8")
        return 0, _CTEST_OUT if "ctest" in cmd or "run-unit" in cmd else "ok"

    def fake_regression(**kwargs):
        captured["skip_tests"] = list(kwargs["skip_tests"])
        return RegressionTestsReport(
            simulations=[RegressionSimulation(name="DBA-COF-Gauss", state="skipped")]
        )

    monkeypatch.setattr(pipeline, "_run_command", fake_run_command)
    monkeypatch.setattr(pipeline, "sync_repositories", lambda **_k: (True, True))
    monkeypatch.setattr(pipeline, "_run_regression_suite", fake_regression)


_SNAPSHOT = SkipConfigSnapshot(
    id="slow",
    name="Slow",
    unit_tests=["TestOrbitThreader"],
    regression_tests=["DBA-COF-Gauss"],
)


def test_pipeline_applies_skip_config_to_unit_and_regression(
    tmp_path: Path, monkeypatch
) -> None:
    commands: list[str] = []
    captured: dict = {}
    _patch_local(monkeypatch, commands, captured)
    cfg = _local_cfg(tmp_path, "ctest --output-on-failure")

    meta = pipeline.run_pipeline(
        cfg=cfg,
        branch="master",
        arch="cpu-serial",
        run_id="skip-run",
        skip_config=_SNAPSHOT,
    )

    assert "ctest --output-on-failure -E '^(TestOrbitThreader)$'" in commands
    assert captured["skip_tests"] == ["DBA-COF-Gauss"]
    assert meta.status == "passed"
    assert (meta.unit_tests_total, meta.unit_tests_skipped) == (1, 1)
    assert meta.regression_skipped == 1
    assert meta.run_options.skip_config == _SNAPSHOT
    run_root = tmp_path / "data" / "runs" / "master" / "cpu-serial" / "skip-run"
    unit = json.loads((run_root / "unit-tests.json").read_text(encoding="utf-8"))
    assert {"TestOrbitThreader": "skipped", "TestFast": "passed"} == {
        t["name"]: t["status"] for t in unit["tests"]
    }
    index = json.loads(
        (tmp_path / "data" / "runs-index" / "master" / "cpu-serial.json").read_text(
            encoding="utf-8"
        )
    )
    assert index[0]["regression_skipped"] == 1
    assert index[0]["unit_tests_skipped"] == 1
    assert index[0]["run_options"]["skip_config"]["id"] == "slow"


def test_pipeline_ignores_unit_skips_for_non_ctest_command(
    tmp_path: Path, monkeypatch
) -> None:
    commands: list[str] = []
    _patch_local(monkeypatch, commands, {})
    cfg = _local_cfg(tmp_path, "./run-unit.sh")

    meta = pipeline.run_pipeline(
        cfg=cfg,
        branch="master",
        arch="cpu-serial",
        run_id="custom-unit",
        skip_config=_SNAPSHOT,
    )

    assert "./run-unit.sh" in commands
    assert meta.unit_tests_skipped == 0
    assert meta.status == "passed"
    log = (
        tmp_path / "data" / "runs" / "master" / "cpu-serial" / "custom-unit"
        / "logs" / "pipeline.log"
    ).read_text(encoding="utf-8")
    assert "skip config ignored, unit_test_command is not ctest" in log


def test_phase_skip_switches_win_over_skip_config(tmp_path: Path, monkeypatch) -> None:
    commands: list[str] = []
    captured: dict = {}
    _patch_local(monkeypatch, commands, captured)
    cfg = _local_cfg(tmp_path, "ctest --output-on-failure")

    meta = pipeline.run_pipeline(
        cfg=cfg,
        branch="master",
        arch="cpu-serial",
        run_id="phase-skip",
        skip_unit=True,
        skip_regression=True,
        skip_config=_SNAPSHOT,
    )

    assert not any(c.startswith("ctest") for c in commands)
    assert "skip_tests" not in captured
    assert (meta.unit_tests_skipped, meta.regression_skipped) == (0, 0)
    assert meta.run_options.skip_config == _SNAPSHOT
