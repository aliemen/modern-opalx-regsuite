from __future__ import annotations

import os
from pathlib import Path

import pytest

from modern_opalx_regsuite.config import SuiteConfig
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
