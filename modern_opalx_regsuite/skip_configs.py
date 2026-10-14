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
import statistics
from pathlib import Path
from typing import Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .archive_service import filter_entries_by_view
from .catalog import list_catalog_tests
from .data_model import SkipConfigSnapshot, run_dir
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


class SkipCandidate(BaseModel):
    name: str
    median_seconds: Optional[float] = None


class SkipCandidates(BaseModel):
    regression: list[SkipCandidate] = Field(default_factory=list)
    unit: list[SkipCandidate] = Field(default_factory=list)


def _recent_finished_entries(data_root: Path, limit: int) -> list[dict]:
    entries: list[dict] = []
    index_root = data_root / "runs-index"
    if not index_root.is_dir():
        return entries
    for path in index_root.rglob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(raw, list):
            entries.extend(
                e
                for e in filter_entries_by_view(raw, "active")
                if e.get("status") in {"passed", "failed"}
            )
    entries.sort(key=lambda e: str(e.get("started_at", "")), reverse=True)
    return entries[:limit]


def _durations(
    data_root: Path, entries: list[dict], filename: str, key: str
) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for e in entries:
        try:
            path = run_dir(data_root, e["branch"], e["arch"], e["run_id"]) / filename
            items = json.loads(path.read_text(encoding="utf-8")).get(key, [])
        except (KeyError, OSError, ValueError, AttributeError):
            continue
        for item in items:
            name = item.get("name")
            if not name:
                continue
            # Skipped entries register the name but contribute no duration.
            durations = out.setdefault(name, [])
            state = (item.get("status") or item.get("state") or "").lower()
            if state != "skipped" and isinstance(
                item.get("duration_seconds"), (int, float)
            ):
                durations.append(float(item["duration_seconds"]))
    return out


def _ranked(names: list[str], durations: dict[str, list[float]]) -> list[SkipCandidate]:
    candidates = [
        SkipCandidate(
            name=n,
            median_seconds=statistics.median(durations[n]) if durations.get(n) else None,
        )
        for n in names
    ]
    return sorted(
        candidates,
        key=lambda c: (c.median_seconds is None, -(c.median_seconds or 0.0), c.name.lower()),
    )


def collect_skip_candidates(cfg: "SuiteConfig", recent_runs: int = 10) -> SkipCandidates:  # type: ignore[name-defined]
    """Names to offer in the skip config editor, slowest first.

    Regression names come from the catalog of the configured regtests branch
    (enabled tests only), falling back to recently run simulations. Unit names
    have no catalog, so they are the names seen in the most recent finished,
    non-archived runs. Medians ignore skipped entries.
    """
    data_root = cfg.resolved_data_root
    entries = _recent_finished_entries(data_root, recent_runs)
    reg_durations = _durations(data_root, entries, "regression-tests.json", "simulations")
    unit_durations = _durations(data_root, entries, "unit-tests.json", "tests")
    catalog = list_catalog_tests(
        cfg.resolved_regtests_repo_root, cfg.regtests_branch, include_disabled=False
    )
    reg_names = [t.name for t in catalog.tests] or sorted(reg_durations)
    return SkipCandidates(
        regression=_ranked(reg_names, reg_durations),
        unit=_ranked(sorted(unit_durations), unit_durations),
    )
