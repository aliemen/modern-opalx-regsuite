"""Global test skip configs: named lists of unit and regression tests that a
manual run may skip. Stored under ``users_root/_public`` next to the public
execution presets; a run stores a frozen ``SkipConfigSnapshot`` instead of a
reference, so editing a config never changes past or queued runs.
"""
from __future__ import annotations

import json
import logging
import re
import shlex
from pathlib import Path
from typing import Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .data_model import SkipConfigSnapshot
from .execution_profiles import _slug, _validate_id, _write_json_atomic

logger = logging.getLogger(__name__)

_TEST_NAME_RE = re.compile(r"^[A-Za-z0-9_.+-]+$")
# Characters with special meaning in CMake/ctest regular expressions.
_CMAKE_REGEX_SPECIALS = set("^$.[]*+?|()\\")
_SHELL_OPERATORS = {"&&", "||", ";", "|"}


def _normalize_names(values: list[str]) -> list[str]:
    names = {value.strip() for value in values if value.strip()}
    for name in names:
        if not _TEST_NAME_RE.fullmatch(name):
            raise ValueError(
                f"Invalid test name '{name}': use letters, digits, '.', '_', '+' or '-'"
            )
    return sorted(names)


class SkipConfigInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., max_length=80)
    description: Optional[str] = Field(None, max_length=300)
    unit_tests: list[str] = Field(default_factory=list)
    regression_tests: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be empty")
        return value

    @field_validator("description")
    @classmethod
    def _description(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("unit_tests", "regression_tests")
    @classmethod
    def _tests(cls, values: list[str]) -> list[str]:
        return _normalize_names(values)


class SkipConfig(SkipConfigInput):
    id: str

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return _validate_id(value)


class SkipConfigsDocument(BaseModel):
    version: int = 1
    configs: list[SkipConfig] = Field(default_factory=list)


def skip_configs_path(cfg: "SuiteConfig") -> Path:  # type: ignore[name-defined]
    return cfg.resolved_users_root / "_public" / "test-skip-configs.json"


def load_skip_configs(cfg: "SuiteConfig") -> SkipConfigsDocument:  # type: ignore[name-defined]
    path = skip_configs_path(cfg)
    if not path.is_file():
        return SkipConfigsDocument()
    try:
        return SkipConfigsDocument.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring unreadable skip config file %s: %s", path, exc)
        return SkipConfigsDocument()


def save_skip_configs(cfg: "SuiteConfig", doc: SkipConfigsDocument) -> None:  # type: ignore[name-defined]
    _write_json_atomic(skip_configs_path(cfg), doc.model_dump(mode="json"))


def _ensure_unique_name(
    doc: SkipConfigsDocument, name: str, own_id: Optional[str]
) -> None:
    for existing in doc.configs:
        if existing.id != own_id and existing.name.lower() == name.lower():
            raise ValueError(f"A skip config named '{existing.name}' already exists.")


def _unique_id(doc: SkipConfigsDocument, name: str) -> str:
    base = _slug(name, "skip-config")
    taken = {c.id for c in doc.configs}
    candidate, n = base, 2
    while candidate in taken:
        candidate = f"{base[:75]}-{n}"
        n += 1
    return candidate


def create_skip_config(cfg: "SuiteConfig", body: SkipConfigInput) -> SkipConfig:  # type: ignore[name-defined]
    doc = load_skip_configs(cfg)
    _ensure_unique_name(doc, body.name, None)
    config = SkipConfig(id=_unique_id(doc, body.name), **body.model_dump())
    doc.configs.append(config)
    save_skip_configs(cfg, doc)
    return config


def update_skip_config(
    cfg: "SuiteConfig", config_id: str, body: SkipConfigInput  # type: ignore[name-defined]
) -> SkipConfig:
    doc = load_skip_configs(cfg)
    for i, existing in enumerate(doc.configs):
        if existing.id == config_id:
            _ensure_unique_name(doc, body.name, config_id)
            config = SkipConfig(id=config_id, **body.model_dump())
            doc.configs[i] = config
            save_skip_configs(cfg, doc)
            return config
    raise KeyError(config_id)


def delete_skip_config(cfg: "SuiteConfig", config_id: str) -> bool:  # type: ignore[name-defined]
    doc = load_skip_configs(cfg)
    remaining = [c for c in doc.configs if c.id != config_id]
    if len(remaining) == len(doc.configs):
        return False
    save_skip_configs(cfg, doc.model_copy(update={"configs": remaining}))
    return True


def skip_config_snapshot(cfg: "SuiteConfig", config_id: str) -> SkipConfigSnapshot:  # type: ignore[name-defined]
    for config in load_skip_configs(cfg).configs:
        if config.id == config_id:
            return SkipConfigSnapshot(
                id=config.id,
                name=config.name,
                unit_tests=list(config.unit_tests),
                regression_tests=list(config.regression_tests),
            )
    raise KeyError(config_id)


def _cmake_regex_escape(name: str) -> str:
    return "".join(f"\\{c}" if c in _CMAKE_REGEX_SPECIALS else c for c in name)


def ctest_command_with_excludes(command: str, names: Sequence[str]) -> Optional[str]:
    """Return *command* with an anchored ctest ``-E`` regex excluding *names*.

    An existing ``-E``/``--exclude-regex`` value is kept and OR-ed with the new
    pattern. Returns ``None`` when *command* is not a direct ctest invocation
    (env assignments, shell chains, wrapper scripts); callers then run all
    tests. The result is shell-quoted, so it survives both the local
    ``shlex.split`` launcher and the remote ``bash -c`` / ``srun`` wrapping.
    """
    if not names:
        return command
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if not tokens or Path(tokens[0]).name != "ctest":
        return None
    if any(t in _SHELL_OPERATORS for t in tokens):
        return None
    pattern = "^(" + "|".join(_cmake_regex_escape(n) for n in names) + ")$"
    for flag in ("-E", "--exclude-regex"):
        if flag in tokens:
            i = tokens.index(flag)
            if i + 1 < len(tokens):
                tokens[i + 1] = f"({tokens[i + 1]})|{pattern}"
                return shlex.join(tokens)
    return shlex.join([*tokens, "-E", pattern])
