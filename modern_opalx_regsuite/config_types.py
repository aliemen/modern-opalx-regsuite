from __future__ import annotations

import math
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EnvActivation(BaseModel):
    """How to activate the build/test environment.

    Used by both ``ArchConfig.env`` (local runs) and ``Connection.env`` (remote runs).
    Four styles:

    - ``"none"``: do nothing; commands run in whatever shell environment is the default.
    - ``"modules"``: source an lmod init script, then ``module use`` + ``module load`` lines.
    - ``"prologue"``: prepend a free-form shell command that is joined with ``&&`` before
      each run command.  Use this for simple setups like ``export VAR=val`` or sourcing
      a setup script.
    - ``"uenv"``: wrap each command with ``uenv run <prologue> -- <cmd>``.  Use this for
      CSCS uenv images.  Set ``prologue`` to everything that comes between ``uenv run``
      and ``--``, e.g.
      ``--view=develop /capstor/.../opal-x-gh200-mpich-gcc-2025-09-28.squashfs``.
    """

    model_config = ConfigDict(extra="forbid")

    style: Literal["none", "modules", "prologue", "uenv"] = Field(
        "none", description="Activation style: 'none', 'modules', 'prologue', or 'uenv'."
    )
    lmod_init: str = Field(
        "/usr/share/lmod/lmod/init/bash",
        description="Path to lmod init script (modules style only).",
    )
    module_use_paths: List[str] = Field(
        default_factory=list,
        description="Paths added with 'module use' before module loads (modules style only).",
    )
    module_loads: List[str] = Field(
        default_factory=list,
        description="Modules to load with 'module load' (modules style only).",
    )
    prologue: Optional[str] = Field(
        None,
        description=(
            "prologue style: free-form shell command prepended with '&&' before each command. "
            "uenv style: arguments passed between 'uenv run' and '--', e.g. "
            "'--view=develop /path/to/image.squashfs'."
        ),
    )


class GatewayEndpoint(BaseModel):
    """SSH ProxyJump gateway. Lives inside Connection.gateway."""

    model_config = ConfigDict(extra="forbid")

    host: str = Field(..., description="SSH hostname or IP of the jump host.")
    user: str = Field(..., description="SSH username on the jump host.")
    port: int = Field(22, description="SSH port on the jump host.")
    key_name: Optional[str] = Field(
        None,
        description=(
            "Name of SSH key in the user's ssh-keys dir (without .pem suffix). "
            "Required when auth_method is 'key'; unused for 'interactive'."
        ),
    )
    auth_method: Literal["key", "interactive"] = Field(
        "key",
        description=(
            "Authentication method: 'key' (SSH key, default) or 'interactive' "
            "(keyboard-interactive with password + 2FA, e.g. for hopx gateways)."
        ),
    )


class SlurmConfig(BaseModel):
    """Typed Slurm allocation recipe for an architecture.

    The requested MPI ranks are supplied at run time. This model converts the
    static per-architecture resource shape into concrete ``salloc`` arguments.
    """

    model_config = ConfigDict(extra="forbid")

    partition: Optional[str] = Field(None, description="Slurm partition.")
    account: Optional[str] = Field(None, description="Slurm account/project.")
    cluster: Optional[str] = Field(None, description="Slurm cluster name.")
    time: Optional[str] = Field(None, description="Wall-clock limit, e.g. 00:30:00.")
    tasks_per_node: Optional[int] = Field(
        None,
        ge=1,
        description="MPI tasks per node. Used to compute --nodes for rank overrides.",
    )
    cpus_per_task: Optional[int] = Field(
        None,
        ge=1,
        description="CPUs assigned to each MPI task.",
    )
    gpus_per_task: Optional[int] = Field(
        None,
        ge=1,
        description="GPUs assigned to each MPI task. Total --gpus scales with ranks.",
    )
    extra_args: List[str] = Field(
        default_factory=list,
        description="Additional non-resource salloc arguments.",
    )

    @field_validator("extra_args")
    @classmethod
    def _reject_resource_extra_args(cls, values: List[str]) -> List[str]:
        blocked = {
            "--nodes",
            "-N",
            "--ntasks",
            "-n",
            "--ntasks-per-node",
            "--gpus",
            "--gpus-per-task",
            "--cpus-per-task",
            "-c",
            "--partition",
            "-p",
            "--account",
            "-A",
            "--time",
            "-t",
            "--cluster",
        }
        short_with_value_prefixes = ("-N", "-n", "-c", "-p", "-A", "-t")
        for arg in values:
            key = arg.split("=", 1)[0]
            if key in blocked or any(
                arg.startswith(prefix) and arg != prefix
                for prefix in short_with_value_prefixes
            ):
                raise ValueError(
                    f"slurm.extra_args must not contain managed resource flag {key!r}"
                )
        return values

    def allocation_args(self, mpi_ranks: int) -> List[str]:
        """Return concrete ``salloc`` arguments for *mpi_ranks*."""
        args: list[str] = [f"--ntasks={mpi_ranks}"]
        if self.tasks_per_node is not None:
            args.append(f"--nodes={math.ceil(mpi_ranks / self.tasks_per_node)}")
            args.append(f"--ntasks-per-node={self.tasks_per_node}")
        if self.gpus_per_task is not None:
            args.append(f"--gpus={mpi_ranks * self.gpus_per_task}")
            args.append(f"--gpus-per-task={self.gpus_per_task}")
        if self.cpus_per_task is not None:
            args.append(f"--cpus-per-task={self.cpus_per_task}")
        if self.time:
            args.append(f"--time={self.time}")
        if self.partition:
            args.append(f"--partition={self.partition}")
        if self.account:
            args.append(f"--account={self.account}")
        if self.cluster:
            args.append(f"--cluster={self.cluster}")
        args.extend(self.extra_args)
        return args

    def step_args(self, mpi_ranks: int) -> List[str]:
        """Return concrete ``srun`` step resource arguments for *mpi_ranks*."""
        args: list[str] = []
        if self.tasks_per_node is not None:
            args.append(f"--nodes={math.ceil(mpi_ranks / self.tasks_per_node)}")
            args.append(f"--ntasks-per-node={self.tasks_per_node}")
        if self.gpus_per_task is not None:
            args.append(f"--gpus-per-task={self.gpus_per_task}")
        if self.cpus_per_task is not None:
            args.append(f"--cpus-per-task={self.cpus_per_task}")
        return args


class Connection(BaseModel):
    """A named, per-user remote execution target.

    Stored in ``<users_root>/<username>/connections.json`` as part of a list.
    Referenced by ``name`` from the trigger endpoint and selected at run time.

    The ``name`` is the only identity surface that may appear in publicly-shareable
    ``data_root`` artifacts (run metadata, log headers). Choose it accordingly.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Unique name of the connection within a user.")
    description: Optional[str] = Field(
        None, description="Optional human-readable description."
    )

    host: str = Field(..., description="SSH hostname or IP of the target machine.")
    user: str = Field(..., description="SSH username on the target machine.")
    port: int = Field(22, description="SSH port on the target machine.")
    key_name: str = Field(
        ...,
        description="Name of SSH key in this user's ssh-keys dir (without .pem suffix).",
    )

    gateway: Optional[GatewayEndpoint] = Field(
        None,
        description="Optional jump host. If set, target is reached via this gateway.",
    )

    work_dir: str = Field(
        "/tmp/opalx-regsuite",
        description="Persistent base directory on the remote target.",
    )
    cleanup_after_run: bool = Field(
        False,
        description="If true, delete work_dir after every run.",
    )

    env: EnvActivation = Field(
        default_factory=EnvActivation,
        description="How to activate the environment on the remote target.",
    )

    keepalive_interval: int = Field(
        30,
        description=(
            "SSH keepalive interval in seconds. Prevents silent connection "
            "drops caused by NAT/firewall timeouts during long builds. 0 = disabled."
        ),
    )


class ArchConfig(BaseModel):
    """Per-architecture build recipe.

    Pure run-config: cmake/build/test parameters and (for local runs) environment
    activation. Execution-target details — SSH host, user, key, gateway, remote
    work_dir — live in per-user :class:`Connection` objects, not here.
    """

    model_config = ConfigDict(extra="forbid")

    arch: str = Field(..., description="Architecture identifier, e.g. 'cpu-serial'.")
    cmake_args: Optional[List[str]] = Field(
        None,
        description="Overrides SuiteConfig.cmake_args for this architecture.",
    )
    build_jobs: int = Field(2, description="Parallelism for make -j.")
    mpi_ranks: int = Field(
        1,
        ge=1,
        description="Default MPI ranks for regression test execution.",
    )
    max_mpi_ranks: Optional[int] = Field(
        None,
        ge=1,
        description="Maximum MPI ranks users may request for this architecture.",
    )
    opalx_info_level: Optional[int] = Field(
        None,
        ge=0,
        description="Default OPALX --info level for this architecture.",
    )
    slurm: Optional[SlurmConfig] = Field(
        None,
        description="Typed Slurm allocation recipe for remote Slurm runs.",
    )
    slurm_args: List[str] = Field(
        default_factory=list,
        description=(
            "DEPRECATED. Legacy raw salloc arguments. Prefer [arch_configs.slurm]. "
            "salloc arguments for Slurm-managed remote runs, e.g. "
            "['--partition=debug', '--ntasks=4', '--gpus=4', '--time=01:00:00']. "
            "When non-empty the runner allocates a job via 'salloc --parsable --no-shell' "
            "before starting the pipeline. Leave empty to run all commands directly "
            "over SSH (no Slurm)."
        ),
    )

    command_timeout: int = Field(
        0,
        description=(
            "Maximum seconds for any single remote command. Wraps commands with "
            "shell-level timeout. Applies to non-srun commands; srun commands "
            "should use --time in slurm_args instead. 0 = no limit."
        ),
    )
    salloc_timeout: int = Field(
        0,
        description="Maximum seconds to wait for a Slurm allocation. 0 = no limit.",
    )
    env: EnvActivation = Field(
        default_factory=EnvActivation,
        description="Environment activation for local runs of this arch. Remote runs use the selected Connection's env instead.",
    )

    @model_validator(mode="after")
    def _validate_slurm_and_limits(self) -> "ArchConfig":
        if self.slurm is not None and self.slurm_args:
            raise ValueError("Use either arch_configs.slurm or slurm_args, not both.")
        if self.max_mpi_ranks is not None and self.max_mpi_ranks < self.mpi_ranks:
            raise ValueError("max_mpi_ranks must be greater than or equal to mpi_ranks.")
        return self

    def slurm_allocation_args(self, mpi_ranks: int) -> list[str]:
        if self.slurm is not None:
            return self.slurm.allocation_args(mpi_ranks)
        return list(self.slurm_args)

    def slurm_step_args(self, mpi_ranks: int) -> list[str]:
        if self.slurm is not None:
            return self.slurm.step_args(mpi_ranks)
        return _legacy_slurm_step_args(self.slurm_args, mpi_ranks)


def _legacy_slurm_step_args(slurm_args: list[str], mpi_ranks: int) -> list[str]:
    """Derive safe ``srun`` step placement flags from legacy raw ``salloc`` args."""
    values: dict[str, str] = {}
    aliases = {
        "--ntasks-per-node": "--ntasks-per-node",
        "--gpus-per-task": "--gpus-per-task",
        "--cpus-per-task": "--cpus-per-task",
        "-c": "--cpus-per-task",
    }
    idx = 0
    while idx < len(slurm_args):
        arg = slurm_args[idx]
        key, sep, value = arg.partition("=")
        canonical = aliases.get(key)
        if canonical is not None:
            if sep:
                values[canonical] = value
            elif idx + 1 < len(slurm_args):
                values[canonical] = slurm_args[idx + 1]
                idx += 1
        elif arg.startswith("-c") and len(arg) > 2:
            values["--cpus-per-task"] = arg[2:]
        idx += 1

    step_args: list[str] = []
    tasks_per_node = values.get("--ntasks-per-node")
    if tasks_per_node:
        try:
            step_args.append(
                f"--nodes={math.ceil(mpi_ranks / int(tasks_per_node))}"
            )
        except ValueError:
            pass
        step_args.append(f"--ntasks-per-node={tasks_per_node}")
    if values.get("--gpus-per-task"):
        step_args.append(f"--gpus-per-task={values['--gpus-per-task']}")
    if values.get("--cpus-per-task"):
        step_args.append(f"--cpus-per-task={values['--cpus-per-task']}")
    return step_args
