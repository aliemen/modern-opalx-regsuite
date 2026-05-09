from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..config import ArchConfig, SuiteConfig
from .cmake import normalize_custom_cmake_args


@dataclass(frozen=True)
class EffectiveRunOptions:
    arch_config: ArchConfig
    custom_cmake_args: list[str]
    clean_build: bool
    mpi_ranks: int
    opalx_info_level: int


def resolve_effective_run_options(
    *,
    cfg: SuiteConfig,
    arch: str,
    clean_build: bool,
    custom_cmake_args: Optional[list[str]],
    mpi_ranks: Optional[int],
    opalx_info_level: Optional[int],
) -> EffectiveRunOptions:
    """Resolve run-level overrides against architecture and global defaults."""
    arch_config = cfg.get_arch_config(arch)
    effective_custom_cmake_args = normalize_custom_cmake_args(custom_cmake_args)
    effective_clean_build = clean_build or bool(effective_custom_cmake_args)

    effective_mpi_ranks = (
        mpi_ranks if mpi_ranks is not None else arch_config.mpi_ranks
    )
    if effective_mpi_ranks < 1:
        raise ValueError("mpi_ranks must be >= 1")
    if (
        arch_config.max_mpi_ranks is not None
        and effective_mpi_ranks > arch_config.max_mpi_ranks
    ):
        raise ValueError(
            f"mpi_ranks={effective_mpi_ranks} exceeds "
            f"max_mpi_ranks={arch_config.max_mpi_ranks} for arch '{arch}'"
        )

    effective_opalx_info_level = (
        opalx_info_level
        if opalx_info_level is not None
        else (
            arch_config.opalx_info_level
            if arch_config.opalx_info_level is not None
            else cfg.opalx_info_level
        )
    )
    if effective_opalx_info_level < 0:
        raise ValueError("opalx_info_level must be >= 0")

    return EffectiveRunOptions(
        arch_config=arch_config,
        custom_cmake_args=effective_custom_cmake_args,
        clean_build=effective_clean_build,
        mpi_ranks=effective_mpi_ranks,
        opalx_info_level=effective_opalx_info_level,
    )
