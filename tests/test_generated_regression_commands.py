from __future__ import annotations

import os
from pathlib import Path

import pytest

from modern_opalx_regsuite.config import Connection, SuiteConfig
from modern_opalx_regsuite.data_model import RegressionSimulation
from modern_opalx_regsuite.runner.execution import _ensure_run_paths
from modern_opalx_regsuite.runner import regression_runner


def test_local_regression_runner_ignores_local_script_and_generates_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    regtests = tmp_path / "regression-tests-x"
    test_dir = regtests / "RegressionTests" / "Generated"
    (test_dir / "reference").mkdir(parents=True)
    (test_dir / "Generated.in").write_text("OPTION;\n", encoding="utf-8")
    (test_dir / "Generated.local").write_text("exit 99\n", encoding="utf-8")
    (test_dir / "Generated.rt").write_text('"Generated."\n', encoding="utf-8")
    (test_dir / "reference" / "Generated.stat").write_text("SDDS\n", encoding="utf-8")

    build_dir = tmp_path / "build"
    opalx = build_dir / "src" / "opalx"
    opalx.parent.mkdir(parents=True)
    opalx.write_text("#!/bin/sh\n", encoding="utf-8")
    os.chmod(opalx, 0o755)

    paths = _ensure_run_paths(tmp_path / "data", "master", "cpu-serial", "run-1")
    captured: dict[str, str] = {}

    def fake_run_command(cmd, cwd, log_path, pipeline_log_path, **_kwargs):
        captured["cmd"] = cmd
        (cwd / "Generated.stat").write_text("SDDS\n", encoding="utf-8")
        log_path.write_text("ok\n", encoding="utf-8")
        return 0, "ok"

    monkeypatch.setattr(regression_runner, "_run_command", fake_run_command)

    cfg = SuiteConfig(
        opalx_repo_root=tmp_path / "opalx",
        builds_root=tmp_path / "builds",
        data_root=tmp_path / "data",
        regtests_repo_root=regtests,
    )

    report = regression_runner._run_regression_suite(
        cfg,
        paths,
        build_dir,
        paths.pipeline_log_path,
        mpi_ranks=2,
        opalx_info_level=4,
    )

    assert report.total == 1
    assert captured["cmd"].startswith("mpirun -np 2 ")
    assert "Generated.in --info 4" in captured["cmd"]
    assert "Generated.local" not in captured["cmd"]


def test_remote_slurm_generated_command_uses_outer_srun_launcher() -> None:
    cmd = regression_runner._build_opalx_run_command(
        opalx_exe="/remote/build/src/opalx",
        input_name="Generated.in",
        mpi_ranks=2,
        opalx_info_level=3,
        opalx_args=["--foo", "bar"],
        launcher="none",
    )

    assert cmd == "/remote/build/src/opalx Generated.in --info 3 --foo bar"
    assert "mpirun" not in cmd
    assert "srun" not in cmd


def _make_regtest(root: Path, name: str) -> None:
    test_dir = root / "RegressionTests" / name
    (test_dir / "reference").mkdir(parents=True)
    (test_dir / f"{name}.in").write_text("OPTION;\n", encoding="utf-8")
    (test_dir / f"{name}.rt").write_text(f'"{name}."\n', encoding="utf-8")
    (test_dir / "reference" / f"{name}.stat").write_text("SDDS\n", encoding="utf-8")


def test_local_runner_skips_configured_tests_and_logs_missing_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    regtests = tmp_path / "regression-tests-x"
    _make_regtest(regtests, "Keep")
    _make_regtest(regtests, "Slow")
    build_dir = tmp_path / "build"
    opalx = build_dir / "src" / "opalx"
    opalx.parent.mkdir(parents=True)
    opalx.write_text("#!/bin/sh\n", encoding="utf-8")
    os.chmod(opalx, 0o755)
    paths = _ensure_run_paths(tmp_path / "data", "master", "cpu-serial", "run-1")
    executed: list[str] = []

    def fake_run_command(cmd, cwd, log_path, pipeline_log_path, **_kwargs):
        executed.append(cwd.name)
        (cwd / f"{cwd.name}.stat").write_text("SDDS\n", encoding="utf-8")
        log_path.write_text("ok\n", encoding="utf-8")
        return 0, "ok"

    monkeypatch.setattr(regression_runner, "_run_command", fake_run_command)
    cfg = SuiteConfig(
        opalx_repo_root=tmp_path / "opalx",
        builds_root=tmp_path / "builds",
        data_root=tmp_path / "data",
        regtests_repo_root=regtests,
    )

    report = regression_runner._run_regression_suite(
        cfg, paths, build_dir, paths.pipeline_log_path, skip_tests=["Slow", "Gone"]
    )

    assert executed == ["Keep"]
    assert [s.name for s in report.simulations] == ["Keep", "Slow"]
    assert report.simulations[1].state == "skipped"
    assert report.simulations[1].containers == []
    assert report.skipped == 1
    log = paths.pipeline_log_path.read_text(encoding="utf-8")
    assert "[regression] SKIP Slow" in log
    assert "Skip config lists Gone, not present on this branch." in log
    assert "Slow: skipped" in paths.reg_log_path.read_text(encoding="utf-8")


class _Res:
    return_code = 0
    stdout = ""


class _Conn:
    def run(self, *_args, **_kwargs):
        return _Res()


class _FakeRemote:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self.conn = _Conn()

    def ensure_dir(self, _path: str) -> None:
        pass

    def run_command(self, cmd: str, **_kwargs) -> int:
        self.commands.append(cmd)
        return 0

    def fetch_file_status(self, _remote: str, _local: Path):
        return ("absent", None)

    def fetch_file(self, _remote: str, _local: Path) -> None:
        raise FileNotFoundError(_remote)


def test_remote_runner_never_copies_or_runs_skipped_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = _FakeRemote()
    paths = _ensure_run_paths(tmp_path / "data", "master", "gpu", "run-2")
    monkeypatch.setattr(
        regression_runner,
        "_discover_regression_tests_remote",
        lambda _remote, _root: ["Keep", "Slow"],
    )
    monkeypatch.setattr(
        regression_runner,
        "_build_simulation",
        lambda **kw: RegressionSimulation(name=kw["test_name"], state="passed"),
    )
    cfg = SuiteConfig(
        opalx_repo_root=tmp_path / "opalx",
        builds_root=tmp_path / "builds",
        data_root=tmp_path / "data",
        regtests_repo_root=tmp_path / "regtests",
    )

    report = regression_runner._run_regression_suite_remote(
        cfg=cfg,
        paths=paths,
        connection=Connection(
            name="daint",
            host="daint.example",
            user="runner",
            key_name="k",
            work_dir="/r",
        ),
        mpi_ranks=1,
        opalx_info_level=2,
        use_slurm=True,
        slurm_step_args=None,
        remote=remote,
        remote_base="/r",
        remote_build="/r/build",
        run_id="run-2",
        pipeline_log_path=paths.pipeline_log_path,
        skip_tests=["Slow"],
    )

    assert not any("Slow" in cmd for cmd in remote.commands)
    assert [(s.name, s.state) for s in report.simulations] == [
        ("Keep", "passed"),
        ("Slow", "skipped"),
    ]
