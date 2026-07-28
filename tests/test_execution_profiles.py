from __future__ import annotations

import json
from pathlib import Path

import pytest

from modern_opalx_regsuite.config import SuiteConfig
from modern_opalx_regsuite.config_types import (
    ArchConfig,
    Connection,
    EnvActivation,
    SlurmConfig,
)
from modern_opalx_regsuite.execution_profiles import (
    ExecutionSettings,
    RunProfile,
    load_execution_settings,
    load_run_profiles,
    resolve_run_profile,
    run_profiles_referencing_key,
    public_settings_path,
    save_execution_settings,
    save_run_profiles,
    suite_config_with_profile,
)
from modern_opalx_regsuite.user_store import save_connections, user_keys_dir


def _cfg(tmp_path: Path) -> SuiteConfig:
    return SuiteConfig(
        opalx_repo_root=tmp_path / "opalx",
        builds_root=tmp_path / "builds",
        data_root=tmp_path / "data",
        users_root=tmp_path / "users",
        regtests_repo_root=tmp_path / "regtests",
        arch_configs=[
            ArchConfig(
                arch="cuda-daint",
                cmake_args=["-DPLATFORMS=CUDA"],
                build_jobs=16,
                mpi_ranks=1,
                max_mpi_ranks=4,
                slurm=SlurmConfig(
                    partition="debug",
                    account="c41",
                    time="00:30:00",
                    tasks_per_node=1,
                    cpus_per_task=16,
                    gpus_per_task=1,
                ),
            )
        ],
    )


def test_public_settings_seed_from_legacy_arch_configs(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)

    settings = load_execution_settings(cfg)

    build = next(p for p in settings.build_presets if p.id == "cuda-daint")
    slurm = next(p for p in settings.slurm_presets if p.id == "cuda-daint-slurm")
    assert build.cmake_args == ["-DPLATFORMS=CUDA"]
    assert build.build_jobs == 16
    assert build.max_mpi_ranks == 4
    assert slurm.slurm is not None
    assert slurm.slurm.partition == "debug"
    assert settings.machine_presets[0].id == "local"
    assert settings.cmake_quick_selections == []


def test_public_settings_load_old_document_without_quick_selections(
    tmp_path: Path,
) -> None:
    cfg = _cfg(tmp_path)
    path = public_settings_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "build_presets": [],
                "machine_presets": [],
                "env_presets": [],
                "slurm_presets": [],
            }
        ),
        encoding="utf-8",
    )

    settings = load_execution_settings(cfg)

    assert settings.cmake_quick_selections == []


def test_public_settings_validate_and_round_trip_cmake_quick_selections(
    tmp_path: Path,
) -> None:
    cfg = _cfg(tmp_path)
    saved = save_execution_settings(
        cfg,
        ExecutionSettings(
            cmake_quick_selections=[" IPPL_GIT_TAG ", "Kokkos_VERSION"],
        ),
    )

    assert saved.cmake_quick_selections == ["IPPL_GIT_TAG", "Kokkos_VERSION"]
    assert load_execution_settings(cfg).cmake_quick_selections == [
        "IPPL_GIT_TAG",
        "Kokkos_VERSION",
    ]

    with pytest.raises(ValueError, match="duplicate names"):
        ExecutionSettings(cmake_quick_selections=["IPPL_GIT_TAG", "IPPL_GIT_TAG"])
    with pytest.raises(ValueError, match="must start with a letter or underscore"):
        ExecutionSettings(cmake_quick_selections=["-DIPPL_GIT_TAG="])


def test_user_profiles_migrate_connections_without_touching_keys(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    username = "demo"
    key_dir = user_keys_dir(cfg, username)
    key_dir.mkdir(parents=True, exist_ok=True)
    key_path = key_dir / "cluster.pem"
    key_path.write_text("not-a-real-key", encoding="utf-8")
    key_path.chmod(0o600)
    save_connections(
        cfg,
        username,
        [
            Connection(
                name="daint",
                host="daint.example",
                user="runner",
                key_name="cluster",
                work_dir="/scratch/demo/opalx-regsuite",
                env=EnvActivation(
                    style="uenv",
                    prologue="--view=develop /uenv/image.squashfs",
                ),
            )
        ],
    )

    profiles = load_run_profiles(cfg, username)
    resolved = resolve_run_profile(cfg, username, "daint-cuda-daint")

    assert any(profile.id == "local-cuda-daint" for profile in profiles)
    assert resolved.connection is not None
    assert resolved.connection.user == "runner"
    assert resolved.connection.key_name == "cluster"
    assert resolved.connection.env.style == "uenv"
    assert resolved.arch_config.slurm is not None
    assert key_path.read_text(encoding="utf-8") == "not-a-real-key"


def test_profile_resolution_builds_transient_arch_and_connection(
    tmp_path: Path,
) -> None:
    cfg = _cfg(tmp_path)
    username = "demo"
    load_execution_settings(cfg)
    save_run_profiles(
        cfg,
        username,
        [
            RunProfile(
                id="local-cuda",
                name="Local CUDA",
                build_preset_id="cuda-daint",
                machine_preset_id="local",
            )
        ],
    )

    resolved = resolve_run_profile(cfg, username, "local-cuda")
    effective_cfg = suite_config_with_profile(cfg, resolved)

    assert resolved.connection is None
    assert resolved.execution_snapshot.build is not None
    assert resolved.execution_snapshot.build.id == "cuda-daint"
    assert effective_cfg.get_arch_config("cuda-daint").cmake_args == [
        "-DPLATFORMS=CUDA"
    ]


def test_run_profiles_referencing_key_finds_private_profile_refs(
    tmp_path: Path,
) -> None:
    cfg = _cfg(tmp_path)
    username = "demo"
    save_run_profiles(
        cfg,
        username,
        [
            RunProfile(
                id="target-key",
                name="Target key",
                build_preset_id="cuda-daint",
                machine_preset_id="daint",
                key_name="cluster",
            ),
            RunProfile(
                id="gateway-key",
                name="Gateway key",
                build_preset_id="cuda-daint",
                machine_preset_id="daint",
                gateway_key_name="cluster",
            ),
            RunProfile(
                id="other-key",
                name="Other key",
                build_preset_id="cuda-daint",
                machine_preset_id="daint",
                key_name="other",
            ),
        ],
    )

    assert run_profiles_referencing_key(cfg, username, "cluster") == [
        "target-key",
        "gateway-key",
    ]
