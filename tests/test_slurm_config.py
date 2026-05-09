from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from modern_opalx_regsuite.config import SlurmResources, SuiteConfig
from modern_opalx_regsuite.runner.pipeline_options import resolve_effective_run_options


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
        "--gpus=2",
        "--gpus-per-task=1",
        "--cpus-per-task=16",
    ]


def test_typed_slurm_fixed_nodes_support_two_ranks_on_one_node(
    tmp_path: Path,
) -> None:
    cfg = SuiteConfig.model_validate(
        {
            **_base_config(tmp_path),
            "arch_configs": [
                {
                    "arch": "cuda-one-node",
                    "mpi_ranks": 2,
                    "slurm": {
                        "nodes": 1,
                        "tasks_per_node": 2,
                        "gpus": 1,
                        "cpus_per_task": 16,
                    },
                }
            ],
        }
    )

    ac = cfg.get_arch_config("cuda-one-node")

    assert ac.slurm_allocation_args(2)[:4] == [
        "--ntasks=2",
        "--nodes=1",
        "--ntasks-per-node=2",
        "--gpus=1",
    ]
    assert ac.slurm_step_args(2) == [
        "--nodes=1",
        "--ntasks-per-node=2",
        "--gpus=1",
        "--cpus-per-task=16",
    ]


def test_slurm_trigger_override_can_clear_gpu_per_task(tmp_path: Path) -> None:
    cfg = SuiteConfig.model_validate(
        {
            **_base_config(tmp_path),
            "arch_configs": [
                {
                    "arch": "cuda",
                    "mpi_ranks": 1,
                    "slurm": {
                        "tasks_per_node": 1,
                        "gpus_per_task": 1,
                        "cpus_per_task": 16,
                    },
                }
            ],
        }
    )

    options = resolve_effective_run_options(
        cfg=cfg,
        arch="cuda",
        clean_build=False,
        custom_cmake_args=None,
        mpi_ranks=2,
        opalx_info_level=None,
        slurm_resources=SlurmResources(
            nodes=1,
            tasks_per_node=2,
            gpus=1,
            gpus_per_task=None,
        ),
    )

    assert options.slurm_config is not None
    assert options.slurm_config.allocation_args(2)[:4] == [
        "--ntasks=2",
        "--nodes=1",
        "--ntasks-per-node=2",
        "--gpus=1",
    ]
    assert "--gpus-per-task=1" not in options.slurm_config.allocation_args(2)
    assert options.persisted_slurm_resources is not None
    assert options.persisted_slurm_resources.gpus == 1
    assert options.persisted_slurm_resources.gpus_per_task is None


def test_slurm_capacity_validation_rejects_too_many_ranks(tmp_path: Path) -> None:
    cfg = SuiteConfig.model_validate(
        {
            **_base_config(tmp_path),
            "arch_configs": [
                {
                    "arch": "cuda",
                    "slurm": {
                        "nodes": 1,
                        "tasks_per_node": 1,
                    },
                }
            ],
        }
    )

    with pytest.raises(ValueError, match="exceeds Slurm capacity"):
        resolve_effective_run_options(
            cfg=cfg,
            arch="cuda",
            clean_build=False,
            custom_cmake_args=None,
            mpi_ranks=2,
            opalx_info_level=None,
        )


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


def test_slurm_override_rejects_legacy_slurm_args(tmp_path: Path) -> None:
    cfg = SuiteConfig.model_validate(
        {
            **_base_config(tmp_path),
            "arch_configs": [
                {
                    "arch": "legacy",
                    "slurm_args": ["--nodes=1"],
                }
            ],
        }
    )

    with pytest.raises(ValueError, match="legacy slurm_args"):
        resolve_effective_run_options(
            cfg=cfg,
            arch="legacy",
            clean_build=False,
            custom_cmake_args=None,
            mpi_ranks=1,
            opalx_info_level=None,
            slurm_resources=SlurmResources(nodes=1),
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
