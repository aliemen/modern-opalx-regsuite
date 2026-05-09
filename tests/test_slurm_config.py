from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from modern_opalx_regsuite.config import SuiteConfig


def _base_config(tmp_path: Path) -> dict:
    return {
        "opalx_repo_root": tmp_path / "opalx",
        "builds_root": tmp_path / "builds",
        "data_root": tmp_path / "data",
        "regtests_repo_root": tmp_path / "regtests",
    }


def test_typed_slurm_scales_tasks_nodes_and_gpus(tmp_path: Path) -> None:
    cfg = SuiteConfig.model_validate(
        {
            **_base_config(tmp_path),
            "arch_configs": [
                {
                    "arch": "cuda-daint",
                    "mpi_ranks": 1,
                    "slurm": {
                        "partition": "debug",
                        "account": "c41",
                        "time": "00:30:00",
                        "tasks_per_node": 1,
                        "cpus_per_task": 16,
                        "gpus_per_task": 1,
                    },
                }
            ],
        }
    )

    args = cfg.get_arch_config("cuda-daint").slurm_allocation_args(2)

    assert "--ntasks=2" in args
    assert "--nodes=2" in args
    assert "--ntasks-per-node=1" in args
    assert "--gpus=2" in args
    assert "--gpus-per-task=1" in args
    assert "--cpus-per-task=16" in args
    assert "--partition=debug" in args
    assert "--account=c41" in args

    step_args = cfg.get_arch_config("cuda-daint").slurm_step_args(2)
    assert step_args == [
        "--nodes=2",
        "--ntasks-per-node=1",
        "--gpus-per-task=1",
        "--cpus-per-task=16",
    ]


def test_legacy_slurm_args_still_load(tmp_path: Path) -> None:
    cfg = SuiteConfig.model_validate(
        {
            **_base_config(tmp_path),
            "arch_configs": [
                {
                    "arch": "legacy",
                    "slurm_args": ["--nodes=1", "--ntasks-per-node=1"],
                }
            ],
        }
    )

    assert cfg.get_arch_config("legacy").slurm_allocation_args(2) == [
        "--nodes=1",
        "--ntasks-per-node=1",
    ]

    legacy = SuiteConfig.model_validate(
        {
            **_base_config(tmp_path),
            "arch_configs": [
                {
                    "arch": "legacy-full",
                    "slurm_args": [
                        "--nodes=1",
                        "--ntasks-per-node=1",
                        "--gpus=1",
                        "--gpus-per-task=1",
                        "--cpus-per-task=16",
                        "--account=c41",
                    ],
                }
            ],
        }
    )
    assert legacy.get_arch_config("legacy-full").slurm_step_args(2) == [
        "--nodes=2",
        "--ntasks-per-node=1",
        "--gpus-per-task=1",
        "--cpus-per-task=16",
    ]


def test_slurm_args_and_typed_slurm_are_mutually_exclusive(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        SuiteConfig.model_validate(
            {
                **_base_config(tmp_path),
                "arch_configs": [
                    {
                        "arch": "bad",
                        "slurm_args": ["--nodes=1"],
                        "slurm": {"tasks_per_node": 1},
                    }
                ],
            }
        )


def test_slurm_extra_args_reject_managed_resource_flags(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        SuiteConfig.model_validate(
            {
                **_base_config(tmp_path),
                "arch_configs": [
                    {
                        "arch": "bad",
                        "slurm": {
                            "tasks_per_node": 1,
                            "extra_args": ["--nodes=2"],
                        },
                    }
                ],
            }
        )
