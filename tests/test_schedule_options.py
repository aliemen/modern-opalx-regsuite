from __future__ import annotations

import asyncio
from pathlib import Path

from modern_opalx_regsuite.config import SuiteConfig
from modern_opalx_regsuite.scheduler.models import ScheduleCreateRequest, ScheduleSpec
from modern_opalx_regsuite.scheduler.store import create_schedule


def test_schedule_store_preserves_rank_options(tmp_path: Path) -> None:
    cfg = SuiteConfig(
        opalx_repo_root=tmp_path / "opalx",
        builds_root=tmp_path / "builds",
        data_root=tmp_path / "data",
        regtests_repo_root=tmp_path / "regtests",
    )

    async def run():
        return await create_schedule(
            cfg,
            owner="demo-user",
            body=ScheduleCreateRequest(
                name="nightly",
                spec=ScheduleSpec(days=["MON"], time="02:00"),
                branch="master",
                arch="cpu-serial",
                connection_name="local",
                mpi_ranks=2,
                opalx_info_level=4,
            ),
        )

    schedule = asyncio.run(run())

    assert schedule.mpi_ranks == 2
    assert schedule.opalx_info_level == 4
