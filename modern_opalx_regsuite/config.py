from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

import tomllib
from pydantic import BaseModel, Field


DEFAULT_CONFIG_PATH = Path("config.toml")
CONFIG_ENV_VAR = "OPALX_REGSUITE_CONFIG"


class SuiteConfig(BaseModel):
    opalx_repo_root: Path = Field(..., description="Path to OPALX source checkout.")
    builds_root: Path = Field(
        ..., description="Root directory for per-branch/per-architecture builds."
    )
    data_root: Path = Field(
        ..., description="Root directory for regression and unit-test data."
    )

    regtests_repo_root: Path = Field(
        ...,
        description="Path to regression-tests-x source checkout.",
    )
    regtests_branch: str = Field(
        "master",
        description="Branch name to use for the regression-tests-x repository.",
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

    @property
    def resolved_opalx_repo_root(self) -> Path:
        return self.opalx_repo_root.expanduser().resolve()

    @property
    def resolved_builds_root(self) -> Path:
        return self.builds_root.expanduser().resolve()

    @property
    def resolved_data_root(self) -> Path:
        return self.data_root.expanduser().resolve()

    @property
    def resolved_regtests_repo_root(self) -> Path:
        return self.regtests_repo_root.expanduser().resolve()


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

    # We keep the writer dependency-free by emitting a minimal TOML
    # representation manually. The schema here is simple and stable.
    data = cfg.model_dump(mode="json")
    lines: list[str] = []

    def add_kv(key: str, value) -> None:
        if isinstance(value, str):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key} = "{escaped}"')
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
    add_kv("regtests_repo_root", str(data["regtests_repo_root"]))
    add_kv("regtests_branch", data.get("regtests_branch", "master"))
    add_kv("default_branch", data.get("default_branch", "master"))
    add_kv("default_architectures", data.get("default_architectures", []))
    add_kv("unit_test_command", data.get("unit_test_command", "ctest --output-on-failure"))
    if data.get("regression_test_command") is not None:
        add_kv("regression_test_command", data["regression_test_command"])
    add_kv("cmake_args", data.get("cmake_args", []))
    add_kv("build_command", data.get("build_command", "make -j2"))

    text = "\n".join(lines) + "\n"
    with config_path.open("w", encoding="utf-8") as f:
        f.write(text)
    return config_path


def init_default_config(
    opalx_repo_root: Path,
    builds_root: Path,
    data_root: Path,
    default_branch: str = "master",
    default_architectures: Optional[List[str]] = None,
    path: Optional[Path] = None,
) -> Path:
    cfg = SuiteConfig(
        opalx_repo_root=opalx_repo_root,
        builds_root=builds_root,
        data_root=data_root,
        default_branch=default_branch,
        default_architectures=default_architectures
        or ["cpu-serial"],
    )
    return save_config(cfg, path=path)

