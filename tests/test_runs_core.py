from __future__ import annotations

import asyncio
from pathlib import Path

from modern_opalx_regsuite.api import runs_core
from modern_opalx_regsuite.api.state import ActiveRun
from modern_opalx_regsuite.config import SlurmResources, SuiteConfig


def test_start_run_forces_clean_build_for_custom_cmake_args(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}

    cfg = SuiteConfig(
        opalx_repo_root=tmp_path / "opalx",
        builds_root=tmp_path / "builds",
        data_root=tmp_path / "data",
        regtests_repo_root=tmp_path / "regtests",
    )

    async def fake_acquire_run_slot(**kwargs):
        captured["active_custom_cmake_args"] = kwargs["custom_cmake_args"]
        captured["active_mpi_ranks"] = kwargs["mpi_ranks"]
        captured["active_opalx_info_level"] = kwargs["opalx_info_level"]
        captured["active_slurm_resources"] = kwargs["slurm_resources"]
        active_kwargs = {
            k: v for k, v in kwargs.items() if k != "custom_cmake_args"
        }
        return ActiveRun(
            **active_kwargs,
            custom_cmake_args=kwargs["custom_cmake_args"],
        )

    class FakeCoordinator:
        async def run_pipeline_async(
            self,
            _cfg,
            _active,
            _skip_unit,
            _skip_regression,
            clean_build=False,
            custom_cmake_args=None,
        ):
            captured["clean_build"] = clean_build
            captured["custom_cmake_args"] = custom_cmake_args

    monkeypatch.setattr(runs_core, "acquire_run_slot", fake_acquire_run_slot)
    monkeypatch.setattr(runs_core, "get_coordinator", lambda: FakeCoordinator())

    async def run() -> None:
        await runs_core.start_run(
            cfg,
            run_id="forced-clean",
            triggered_by="demo-user",
            owner_for_connection="demo-user",
            branch="master",
            arch="cpu-serial",
            regtests_branch=None,
            skip_unit=False,
            skip_regression=False,
            clean_build=False,
            custom_cmake_args=["", "# comment", " -DIPPL_GIT_TAG=master "],
            mpi_ranks=2,
            opalx_info_level=4,
            slurm_resources=SlurmResources(nodes=1, tasks_per_node=2),
            connection_name="local",
        )
        await asyncio.sleep(0)

    asyncio.run(run())

    assert captured["active_custom_cmake_args"] == ["-DIPPL_GIT_TAG=master"]
    assert captured["active_mpi_ranks"] == 2
    assert captured["active_opalx_info_level"] == 4
    assert captured["active_slurm_resources"] == SlurmResources(
        nodes=1,
        tasks_per_node=2,
    )
    assert captured["clean_build"] is True
    assert captured["custom_cmake_args"] == ["-DIPPL_GIT_TAG=master"]


def test_start_run_preserves_rank_options_when_queued(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}

    cfg = SuiteConfig(
        opalx_repo_root=tmp_path / "opalx",
        builds_root=tmp_path / "builds",
        data_root=tmp_path / "data",
        regtests_repo_root=tmp_path / "regtests",
    )

    async def fake_acquire_run_slot(**_kwargs):
        return None

    async def fake_enqueue_run(queued):
        captured["queued_mpi_ranks"] = queued.mpi_ranks
        captured["queued_opalx_info_level"] = queued.opalx_info_level
        captured["queued_slurm_resources"] = queued.slurm_resources
        return 1

    monkeypatch.setattr(runs_core, "acquire_run_slot", fake_acquire_run_slot)
    monkeypatch.setattr(runs_core, "enqueue_run", fake_enqueue_run)

    async def run() -> None:
        await runs_core.start_run(
            cfg,
            run_id="queued",
            triggered_by="demo-user",
            owner_for_connection="demo-user",
            branch="master",
            arch="cpu-serial",
            regtests_branch=None,
            skip_unit=False,
            skip_regression=False,
            clean_build=False,
            custom_cmake_args=None,
            mpi_ranks=3,
            opalx_info_level=5,
            slurm_resources=SlurmResources(nodes=2, tasks_per_node=2),
            connection_name="local",
        )

    asyncio.run(run())

    assert captured["queued_mpi_ranks"] == 3
    assert captured["queued_opalx_info_level"] == 5
    assert captured["queued_slurm_resources"] == SlurmResources(
        nodes=2,
        tasks_per_node=2,
    )
