from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]
from pydantic import BaseModel, ConfigDict, Field

from .config_types import (
    ArchConfig,
    Connection,
    EnvActivation,
    GatewayEndpoint,
    SlurmConfig,
)


DEFAULT_CONFIG_PATH = Path("config.toml")
CONFIG_ENV_VAR = "OPALX_REGSUITE_CONFIG"
DATA_ROOT_ENV_VAR = "OPALX_DATA_ROOT"
ARCHIVE_ROOT_ENV_VAR = "OPALX_ARCHIVE_ROOT"
SECRET_KEY_ENV_VAR = "OPALX_SECRET_KEY"


class SuiteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opalx_repo_root: Path = Field(..., description="Path to OPALX source checkout.")
    builds_root: Path = Field(
        ..., description="Root directory for per-branch/per-architecture builds."
    )
    data_root: Path = Field(
        ..., description="Root directory for regression and unit-test data."
    )
    archive_root: Optional[Path] = Field(
        None,
        description=(
            "Optional cold-storage root for archived run directories. Index files "
            "remain under data_root; only run directories move here."
        ),
    )

    regtests_repo_root: Path = Field(
        ...,
        description="Path to regression-tests-x source checkout.",
    )
    regtests_branch: str = Field(
        "master",
        description="Branch name to use for the regression-tests-x repository.",
    )
    regtests_subdir: str = Field(
        "RegressionTests",
        description="Subdirectory inside regression-tests-x that contains tests.",
    )

    default_branch: str = "master"
    default_architectures: List[str] = Field(
        default_factory=lambda: ["cpu-serial"],
        description="Architectures to test by default.",
    )

    unit_test_command: str = Field(
        default="ctest --output-on-failure",
        description="Shell command to run unit tests inside the build directory.",
    )
    regression_test_command: Optional[str] = Field(
        default=None,
        description=(
            "Shell command to run regression tests. If not set, you can provide "
            "a Python hook inside your own tooling that calls into the suite."
        ),
    )

    cmake_args: List[str] = Field(
        default_factory=lambda: [
            "-DBUILD_TYPE=Debug",
            "-DPLATFORMS=SERIAL",
            "-DOPALX_ENABLE_UNIT_TESTS=ON",
        ],
        description="Additional arguments for the CMake configure step.",
    )
    build_command: str = Field(
        default="make -j2",
        description="Build command executed in the build directory after CMake.",
    )
    build_jobs: int = Field(
        default=2,
        description="Default parallelism for make -j (overrides build_command's -j if set).",
    )
    mpi_ranks: int = Field(
        default=1,
        ge=1,
        description="Default MPI ranks for regression test execution.",
    )
    opalx_info_level: int = Field(
        default=2,
        ge=0,
        description="Default OPALX --info level for generated regression commands.",
    )
    opalx_executable_relpath: str = Field(
        "src/opalx",
        description=(
            "Path to the opalx executable relative to the build directory. "
            "Fallbacks to 'opalx' in the build root."
        ),
    )
    opalx_args: List[str] = Field(
        default_factory=list,
        description="Extra arguments to pass to OPALX for regression tests.",
    )
    keep_work_dirs: bool = Field(
        False,
        description="If true, retain per-test temporary work directories after a run.",
    )
    per_test_timeout_seconds: Optional[int] = Field(
        None,
        description=(
            "Kill a local regression test process after this many seconds. "
            "Killed tests are reported as 'crashed' (SIGKILL). None = no per-test limit."
        ),
    )
    max_pipeline_duration: int = Field(
        0,
        description=(
            "Maximum total seconds for the entire pipeline. The pipeline is "
            "cancelled automatically if it exceeds this duration. 0 = no limit."
        ),
    )

    # HTTPS git URLs for remote cloning (public repos).
    opalx_repo_url: Optional[str] = Field(
        None,
        description=(
            "HTTPS git URL for OPALX, used to clone on remote hosts. "
            "Example: 'https://github.com/org/opalx.git'. "
            "If not set, derived from 'git remote get-url origin' of opalx_repo_root."
        ),
    )
    regtests_repo_url: Optional[str] = Field(
        None,
        description=(
            "HTTPS git URL for regression-tests-x, used to clone on remote hosts. "
            "If not set, derived from 'git remote get-url origin' of regtests_repo_root."
        ),
    )

    # Per-architecture build recipes (optional).
    arch_configs: List[ArchConfig] = Field(
        default_factory=list,
        description="Per-architecture build recipes.",
    )

    # ── Per-user storage ─────────────────────────────────────────────────────
    # All identity-bearing state (SSH keys, named connections, profile) lives
    # under <users_root>/<username>/, never under data_root.
    users_root: Optional[Path] = Field(
        None,
        description=(
            "Root directory for per-user state (ssh-keys, connections.json). "
            "Defaults to ~/.config/opalx-regsuite/users."
        ),
    )

    # Deprecated. SSH keys now live per-user under <users_root>/<username>/ssh-keys.
    # Kept only as a fallback location read by the migrate-keys CLI helper.
    ssh_keys_dir: Optional[Path] = Field(
        None,
        description=(
            "DEPRECATED. Legacy global SSH key directory; only used by migrate-keys CLI. "
            "New keys are stored per-user under <users_root>/<username>/ssh-keys."
        ),
    )

    # Web server settings.
    host: str = Field("0.0.0.0", description="Host to bind the web server to.")
    port: int = Field(8000, description="Port to bind the web server to.")
    secret_key: str = Field(
        "",
        description=(
            "JWT signing key. Set via OPALX_SECRET_KEY env var or directly here."
        ),
    )
    users_file: Path = Field(
        default=Path("~/.config/opalx-regsuite/users.json"),
        description="Path to the JSON file storing bcrypt-hashed user credentials.",
    )

    def get_arch_config(self, arch: str) -> ArchConfig:
        """Return the ArchConfig for *arch*, falling back to a default if not found."""
        for ac in self.arch_configs:
            if ac.arch == arch:
                return ac
        # Infer build_jobs from legacy build_command (e.g. "make -j4" → 4).
        jobs = self.build_jobs
        m = re.search(r"-j\s*(\d+)", self.build_command)
        if m:
            jobs = int(m.group(1))
        return ArchConfig(
            arch=arch,
            build_jobs=jobs,
            mpi_ranks=self.mpi_ranks,
            opalx_info_level=None,
            env=EnvActivation(),
        )

    @property
    def resolved_opalx_repo_root(self) -> Path:
        return self.opalx_repo_root.expanduser().resolve()

    @property
    def resolved_builds_root(self) -> Path:
        return self.builds_root.expanduser().resolve()

    @property
    def resolved_data_root(self) -> Path:
        # Allow env var override so the caller can point at a cloned data repo.
        env_override = os.environ.get(DATA_ROOT_ENV_VAR)
        if env_override:
            return Path(env_override).expanduser().resolve()
        return self.data_root.expanduser().resolve()

    @property
    def resolved_archive_root(self) -> Optional[Path]:
        env_override = os.environ.get(ARCHIVE_ROOT_ENV_VAR)
        if env_override:
            return Path(env_override).expanduser().resolve()
        if self.archive_root is None:
            return None
        return self.archive_root.expanduser().resolve()

    @property
    def archive_enabled(self) -> bool:
        return self.resolved_archive_root is not None

    @property
    def resolved_regtests_repo_root(self) -> Path:
        return self.regtests_repo_root.expanduser().resolve()

    @property
    def resolved_users_root(self) -> Path:
        if self.users_root is not None:
            return self.users_root.expanduser().resolve()
        # Default to ~/.config/opalx-regsuite/users so identity-bearing state is
        # never co-located with data_root (which may be publicly shared).
        return Path.home() / ".config" / "opalx-regsuite" / "users"

    @property
    def resolved_ssh_keys_dir(self) -> Path:
        """DEPRECATED. Legacy global SSH keys directory.

        Kept only so the ``migrate-keys`` CLI helper can locate pre-existing keys
        and so old tests/scripts that read this property continue to function.
        New code must use ``user_store.user_keys_dir(cfg, username)`` instead.
        """
        if self.ssh_keys_dir is not None:
            return self.ssh_keys_dir.expanduser().resolve()
        return Path.home() / ".config" / "opalx-regsuite" / "ssh-keys"

    @property
    def resolved_secret_key(self) -> str:
        return os.environ.get(SECRET_KEY_ENV_VAR, self.secret_key)

    @property
    def resolved_users_file(self) -> Path:
        return self.users_file.expanduser().resolve()


def _find_config_path(explicit: Optional[Path] = None) -> Path:
    if explicit is not None:
        return explicit
    env = os.environ.get(CONFIG_ENV_VAR)
    if env:
        return Path(env)
    return DEFAULT_CONFIG_PATH


def load_config(path: Optional[Path] = None) -> SuiteConfig:
    config_path = _find_config_path(path)
    if not config_path.is_file():
        raise FileNotFoundError(
            f"Config file not found at {config_path}. Run 'opalx-regsuite init' first."
        )
    with config_path.open("rb") as f:
        raw = tomllib.load(f)
    return SuiteConfig.model_validate(raw)


def save_config(cfg: SuiteConfig, path: Optional[Path] = None) -> Path:
    config_path = _find_config_path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    data = cfg.model_dump(mode="json")
    lines: list[str] = []

    def add_kv(key: str, value) -> None:
        if isinstance(value, str):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key} = "{escaped}"')
        elif isinstance(value, bool):
            lines.append(f"{key} = {'true' if value else 'false'}")
        elif isinstance(value, int):
            lines.append(f"{key} = {value}")
        elif isinstance(value, list):
            parts: list[str] = []
            for item in value:
                if isinstance(item, str):
                    esc = item.replace("\\", "\\\\").replace('"', '\\"')
                    parts.append(f'"{esc}"')
                else:
                    parts.append(str(item))
            lines.append(f"{key} = [{', '.join(parts)}]")
        else:
            lines.append(f"{key} = {value}")

    add_kv("opalx_repo_root", str(data["opalx_repo_root"]))
    add_kv("builds_root", str(data["builds_root"]))
    add_kv("data_root", str(data["data_root"]))
    if data.get("archive_root"):
        add_kv("archive_root", str(data["archive_root"]))
    add_kv("regtests_repo_root", str(data["regtests_repo_root"]))
    add_kv("regtests_branch", data.get("regtests_branch", "master"))
    add_kv("regtests_subdir", data.get("regtests_subdir", "RegressionTests"))
    add_kv("default_branch", data.get("default_branch", "master"))
    add_kv("default_architectures", data.get("default_architectures", []))
    add_kv("unit_test_command", data.get("unit_test_command", "ctest --output-on-failure"))
    if data.get("regression_test_command") is not None:
        add_kv("regression_test_command", data["regression_test_command"])
    add_kv("cmake_args", data.get("cmake_args", []))
    add_kv("build_command", data.get("build_command", "make -j2"))
    add_kv("build_jobs", data.get("build_jobs", 2))
    add_kv("mpi_ranks", data.get("mpi_ranks", 1))
    add_kv("opalx_info_level", data.get("opalx_info_level", 2))
    add_kv("opalx_executable_relpath", data.get("opalx_executable_relpath", "src/opalx"))
    add_kv("opalx_args", data.get("opalx_args", []))
    add_kv("keep_work_dirs", data.get("keep_work_dirs", False))
    if data.get("max_pipeline_duration", 0) != 0:
        add_kv("max_pipeline_duration", data["max_pipeline_duration"])
    if data.get("opalx_repo_url"):
        add_kv("opalx_repo_url", data["opalx_repo_url"])
    if data.get("regtests_repo_url"):
        add_kv("regtests_repo_url", data["regtests_repo_url"])
    if data.get("users_root"):
        add_kv("users_root", str(data["users_root"]))
    if data.get("ssh_keys_dir"):
        add_kv("ssh_keys_dir", str(data["ssh_keys_dir"]))
    add_kv("host", data.get("host", "0.0.0.0"))
    add_kv("port", data.get("port", 8000))
    # Never write the secret key to disk; it lives in the env var.
    add_kv("users_file", str(data.get("users_file", "~/.config/opalx-regsuite/users.json")))

    def _emit_env(env: dict, table_prefix: str) -> None:
        """Emit an [arch_configs.env] sub-table if it has non-default content."""
        style = env.get("style", "none")
        is_default = (
            style == "none"
            and not env.get("module_use_paths")
            and not env.get("module_loads")
            and not env.get("prologue")
            and env.get("lmod_init", "/usr/share/lmod/lmod/init/bash")
                == "/usr/share/lmod/lmod/init/bash"
        )
        if is_default:
            return
        lines.append("")
        lines.append(f"[{table_prefix}.env]")
        add_kv("style", style)
        if style == "modules":
            if env.get("lmod_init") and env["lmod_init"] != "/usr/share/lmod/lmod/init/bash":
                add_kv("lmod_init", env["lmod_init"])
            if env.get("module_use_paths"):
                add_kv("module_use_paths", env["module_use_paths"])
            if env.get("module_loads"):
                add_kv("module_loads", env["module_loads"])
        elif style == "prologue":
            if env.get("prologue"):
                add_kv("prologue", env["prologue"])

    def _emit_slurm(slurm: dict) -> None:
        """Emit an [arch_configs.slurm] sub-table if configured."""
        if not slurm:
            return
        lines.append("")
        lines.append("[arch_configs.slurm]")
        for key in (
            "partition",
            "account",
            "cluster",
            "time",
            "tasks_per_node",
            "cpus_per_task",
            "gpus_per_task",
        ):
            if slurm.get(key) is not None:
                add_kv(key, slurm[key])
        if slurm.get("extra_args"):
            add_kv("extra_args", slurm["extra_args"])

    # Per-arch configs as TOML array-of-tables.
    for ac in data.get("arch_configs", []):
        lines.append("")
        lines.append("[[arch_configs]]")
        add_kv("arch", ac.get("arch", ""))
        if ac.get("cmake_args") is not None:
            add_kv("cmake_args", ac["cmake_args"])
        add_kv("build_jobs", ac.get("build_jobs", 2))
        add_kv("mpi_ranks", ac.get("mpi_ranks", 1))
        if ac.get("max_mpi_ranks") is not None:
            add_kv("max_mpi_ranks", ac["max_mpi_ranks"])
        if ac.get("opalx_info_level") is not None:
            add_kv("opalx_info_level", ac["opalx_info_level"])
        _emit_slurm(ac.get("slurm") or {})
        if ac.get("slurm_args"):
            add_kv("slurm_args", ac["slurm_args"])
        if ac.get("command_timeout", 0) != 0:
            add_kv("command_timeout", ac["command_timeout"])
        if ac.get("salloc_timeout", 0) != 0:
            add_kv("salloc_timeout", ac["salloc_timeout"])
        # Nested env activation as a sibling sub-table.
        env = ac.get("env") or {}
        _emit_env(env, "arch_configs")

    text = "\n".join(lines) + "\n"
    with config_path.open("w", encoding="utf-8") as f:
        f.write(text)
    return config_path


def init_default_config(
    opalx_repo_root: Path,
    builds_root: Path,
    data_root: Path,
    regtests_repo_root: Path,
    default_branch: str = "master",
    default_architectures: Optional[List[str]] = None,
    path: Optional[Path] = None,
) -> Path:
    cfg = SuiteConfig(
        opalx_repo_root=opalx_repo_root,
        builds_root=builds_root,
        data_root=data_root,
        regtests_repo_root=regtests_repo_root,
        default_branch=default_branch,
        default_architectures=default_architectures or ["cpu-serial"],
    )
    return save_config(cfg, path=path)
