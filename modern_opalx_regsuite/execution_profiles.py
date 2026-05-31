from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config_types import (
    ArchConfig,
    Connection,
    EnvActivation,
    GatewayEndpoint,
    SlurmConfig,
    SlurmResources,
)
from .data_model import (
    BuildPresetSnapshot,
    EnvPresetSnapshot,
    ExecutionSnapshot,
    MachinePresetSnapshot,
    SlurmPresetSnapshot,
)
from .user_store import (
    ensure_user_dir,
    load_connections,
    resolve_connection_key_paths,
    user_dir,
    user_keys_dir,
)


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


def _validate_id(value: str) -> str:
    value = value.strip()
    if not _ID_RE.match(value):
        raise ValueError(
            "id must start with an alphanumeric character and contain only "
            "letters, digits, '.', '_' or '-'"
        )
    return value


def _is_default_env(env: EnvActivation) -> bool:
    return (
        env.style == "none"
        and not env.module_use_paths
        and not env.module_loads
        and not env.prologue
        and env.lmod_init == "/usr/share/lmod/lmod/init/bash"
    )


class BuildPreset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: Optional[str] = None
    cmake_args: Optional[list[str]] = None
    build_jobs: int = Field(2, ge=1)
    mpi_ranks: int = Field(1, ge=1)
    max_mpi_ranks: Optional[int] = Field(None, ge=1)
    opalx_info_level: Optional[int] = Field(None, ge=0)
    generated: bool = False

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return _validate_id(value)

    @model_validator(mode="after")
    def _validate_ranks(self) -> "BuildPreset":
        if self.max_mpi_ranks is not None and self.max_mpi_ranks < self.mpi_ranks:
            raise ValueError("max_mpi_ranks must be greater than or equal to mpi_ranks")
        return self


class MachineGatewayPreset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str
    port: int = Field(22, ge=1, le=65535)
    auth_method: Literal["key", "interactive"] = "key"


class MachinePreset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: Optional[str] = None
    kind: Literal["local", "ssh"] = "ssh"
    host: Optional[str] = None
    port: int = Field(22, ge=1, le=65535)
    gateway: Optional[MachineGatewayPreset] = None
    queue_key: Optional[str] = None
    generated: bool = False

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return _validate_id(value)

    @model_validator(mode="after")
    def _validate_kind(self) -> "MachinePreset":
        if self.kind == "ssh" and not self.host:
            raise ValueError("ssh machine presets require host")
        if self.kind == "local" and (self.host or self.gateway):
            raise ValueError("local machine presets cannot define host or gateway")
        return self


class EnvPreset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: Optional[str] = None
    env: EnvActivation = Field(default_factory=EnvActivation)
    generated: bool = False

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return _validate_id(value)


class SlurmPreset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: Optional[str] = None
    slurm: Optional[SlurmConfig] = None
    slurm_args: list[str] = Field(default_factory=list)
    command_timeout: int = Field(0, ge=0)
    salloc_timeout: int = Field(0, ge=0)
    generated: bool = False

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return _validate_id(value)

    @model_validator(mode="after")
    def _validate_shape(self) -> "SlurmPreset":
        if self.slurm is not None and self.slurm_args:
            raise ValueError("Use either slurm or slurm_args, not both.")
        if self.slurm is None and not self.slurm_args:
            raise ValueError("Slurm preset requires either slurm or slurm_args.")
        return self


class ExecutionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    build_presets: list[BuildPreset] = Field(default_factory=list)
    machine_presets: list[MachinePreset] = Field(default_factory=list)
    env_presets: list[EnvPreset] = Field(default_factory=list)
    slurm_presets: list[SlurmPreset] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    modified_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _unique_ids(self) -> "ExecutionSettings":
        for label, items in (
            ("build_presets", self.build_presets),
            ("machine_presets", self.machine_presets),
            ("env_presets", self.env_presets),
            ("slurm_presets", self.slurm_presets),
        ):
            ids = [item.id for item in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{label} contains duplicate ids")
        return self


class RunProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: Optional[str] = None
    build_preset_id: str
    machine_preset_id: str
    env_preset_id: Optional[str] = None
    slurm_preset_id: Optional[str] = None

    ssh_user: Optional[str] = None
    key_name: Optional[str] = None
    gateway_user: Optional[str] = None
    gateway_key_name: Optional[str] = None
    work_dir: str = "/tmp/opalx-regsuite"
    cleanup_after_run: bool = False
    keepalive_interval: int = Field(30, ge=0)
    generated: bool = False

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return _validate_id(value)


class RunProfilesDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    profiles: list[RunProfile] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    modified_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _unique_ids(self) -> "RunProfilesDocument":
        ids = [item.id for item in self.profiles]
        if len(ids) != len(set(ids)):
            raise ValueError("profiles contains duplicate ids")
        return self


class RunProfileSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: Optional[str] = None
    arch: str
    build_preset_id: str
    build_preset_name: str
    machine_preset_id: str
    machine_preset_name: str
    machine_kind: Literal["local", "ssh"]
    env_preset_id: Optional[str] = None
    env_preset_name: Optional[str] = None
    env_style: str = "none"
    slurm_preset_id: Optional[str] = None
    slurm_preset_name: Optional[str] = None
    default_mpi_ranks: int
    max_mpi_ranks: Optional[int] = None
    default_opalx_info_level: int
    slurm_enabled: bool
    slurm_overrides_supported: bool
    slurm_defaults: Optional[SlurmResources] = None
    interactive_gateway: bool = False
    generated: bool = False
    valid: bool = True
    validation_errors: list[str] = Field(default_factory=list)


class ResolvedRunProfile(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    profile: RunProfile
    build: BuildPreset
    machine: MachinePreset
    env_preset: Optional[EnvPreset]
    slurm_preset: Optional[SlurmPreset]
    arch_config: ArchConfig
    connection: Optional[Connection]
    execution_snapshot: ExecutionSnapshot

    @property
    def arch(self) -> str:
        return self.build.id

    @property
    def connection_name(self) -> str:
        if self.connection is None:
            return "local"
        return self.connection.name


_profiles_locks: dict[str, asyncio.Lock] = {}


def profiles_lock(username: str) -> asyncio.Lock:
    lock = _profiles_locks.get(username)
    if lock is None:
        lock = asyncio.Lock()
        _profiles_locks[username] = lock
    return lock


def public_settings_path(cfg: "SuiteConfig") -> Path:  # type: ignore[name-defined]
    return cfg.resolved_users_root / "_public" / "execution-settings.json"


def run_profiles_path(cfg: "SuiteConfig", username: str) -> Path:  # type: ignore[name-defined]
    return user_dir(cfg, username) / "run-profiles.json"


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _default_settings_from_config(cfg: "SuiteConfig") -> ExecutionSettings:  # type: ignore[name-defined]
    now = datetime.now(timezone.utc)
    machine_presets = [
        MachinePreset(
            id="local",
            name="Local",
            description="Run on the regsuite server.",
            kind="local",
            queue_key="local",
            generated=True,
        )
    ]
    build_presets: list[BuildPreset] = []
    env_presets: list[EnvPreset] = []
    slurm_presets: list[SlurmPreset] = []

    arch_names = list(cfg.default_architectures)
    for ac in cfg.arch_configs:
        if ac.arch not in arch_names:
            arch_names.append(ac.arch)

    for arch in arch_names:
        ac = cfg.get_arch_config(arch)
        build_presets.append(
            BuildPreset(
                id=ac.arch,
                name=ac.arch,
                cmake_args=ac.cmake_args,
                build_jobs=ac.build_jobs,
                mpi_ranks=ac.mpi_ranks,
                max_mpi_ranks=ac.max_mpi_ranks,
                opalx_info_level=ac.opalx_info_level,
                generated=True,
            )
        )
        if not _is_default_env(ac.env):
            env_presets.append(
                EnvPreset(
                    id=f"{ac.arch}-env",
                    name=f"{ac.arch} environment",
                    env=ac.env,
                    generated=True,
                )
            )
        if ac.slurm is not None or ac.slurm_args:
            slurm_presets.append(
                SlurmPreset(
                    id=f"{ac.arch}-slurm",
                    name=f"{ac.arch} Slurm",
                    slurm=ac.slurm,
                    slurm_args=ac.slurm_args,
                    command_timeout=ac.command_timeout,
                    salloc_timeout=ac.salloc_timeout,
                    generated=True,
                )
            )

    if not build_presets:
        for arch in cfg.default_architectures or ["cpu-serial"]:
            ac = cfg.get_arch_config(arch)
            build_presets.append(
                BuildPreset(
                    id=arch,
                    name=arch,
                    cmake_args=ac.cmake_args,
                    build_jobs=ac.build_jobs,
                    mpi_ranks=ac.mpi_ranks,
                    max_mpi_ranks=ac.max_mpi_ranks,
                    opalx_info_level=ac.opalx_info_level,
                    generated=True,
                )
            )

    return ExecutionSettings(
        build_presets=build_presets,
        machine_presets=machine_presets,
        env_presets=env_presets,
        slurm_presets=slurm_presets,
        created_at=now,
        modified_at=now,
    )


def load_execution_settings(cfg: "SuiteConfig") -> ExecutionSettings:  # type: ignore[name-defined]
    path = public_settings_path(cfg)
    if not path.is_file():
        settings = _default_settings_from_config(cfg)
        save_execution_settings(cfg, settings)
        return settings
    raw = json.loads(path.read_text(encoding="utf-8"))
    return ExecutionSettings.model_validate(raw)


def save_execution_settings(
    cfg: "SuiteConfig", settings: ExecutionSettings  # type: ignore[name-defined]
) -> ExecutionSettings:
    now = datetime.now(timezone.utc)
    if settings.created_at is None:
        settings = settings.model_copy(update={"created_at": now})
    settings = settings.model_copy(update={"modified_at": now})
    _write_json_atomic(public_settings_path(cfg), settings.model_dump(mode="json"))
    return settings


def _find_by_id(items: list, item_id: Optional[str]):
    if item_id is None:
        return None
    for item in items:
        if item.id == item_id:
            return item
    return None


def _upsert_by_id(items: list, item):
    for idx, existing in enumerate(items):
        if existing.id == item.id:
            items[idx] = item
            return
    items.append(item)


def _slug(value: str, fallback: str) -> str:
    raw = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-._")
    if not raw:
        raw = fallback
    if raw[0].isdigit():
        raw = f"x-{raw}"
    return raw[:80]


def _machine_from_connection(conn: Connection) -> MachinePreset:
    gateway = None
    if conn.gateway is not None:
        gateway = MachineGatewayPreset(
            host=conn.gateway.host,
            port=conn.gateway.port,
            auth_method=conn.gateway.auth_method,
        )
    return MachinePreset(
        id=_slug(conn.name, "remote"),
        name=conn.name,
        description=conn.description,
        kind="ssh",
        host=conn.host,
        port=conn.port,
        gateway=gateway,
        queue_key=conn.host,
        generated=True,
    )


def _env_preset_from_connection(conn: Connection) -> Optional[EnvPreset]:
    if _is_default_env(conn.env):
        return None
    return EnvPreset(
        id=_slug(f"{conn.name}-env", "remote-env"),
        name=f"{conn.name} environment",
        env=conn.env,
        generated=True,
    )


def _local_env_id_for_build(settings: ExecutionSettings, build_id: str) -> Optional[str]:
    candidate = f"{build_id}-env"
    return candidate if _find_by_id(settings.env_presets, candidate) is not None else None


def _slurm_id_for_build(settings: ExecutionSettings, build_id: str) -> Optional[str]:
    candidate = f"{build_id}-slurm"
    return candidate if _find_by_id(settings.slurm_presets, candidate) is not None else None


def _profile_from_connection_and_build(
    conn: Connection,
    build: BuildPreset,
    machine: MachinePreset,
    env_preset: Optional[EnvPreset],
    slurm_preset_id: Optional[str],
) -> RunProfile:
    return RunProfile(
        id=_slug(f"{conn.name}-{build.id}", f"profile-{build.id}"),
        name=f"{conn.name} / {build.name}",
        description=conn.description,
        build_preset_id=build.id,
        machine_preset_id=machine.id,
        env_preset_id=env_preset.id if env_preset is not None else None,
        slurm_preset_id=slurm_preset_id,
        ssh_user=conn.user,
        key_name=conn.key_name,
        gateway_user=conn.gateway.user if conn.gateway is not None else None,
        gateway_key_name=(
            conn.gateway.key_name
            if conn.gateway is not None and conn.gateway.auth_method != "interactive"
            else None
        ),
        work_dir=conn.work_dir,
        cleanup_after_run=conn.cleanup_after_run,
        keepalive_interval=conn.keepalive_interval,
        generated=True,
    )


def _local_profile_for_build(
    build: BuildPreset,
    env_preset_id: Optional[str],
) -> RunProfile:
    return RunProfile(
        id=_slug(f"local-{build.id}", f"local-{build.id}"),
        name=f"Local / {build.name}",
        build_preset_id=build.id,
        machine_preset_id="local",
        env_preset_id=env_preset_id,
        slurm_preset_id=None,
        generated=True,
    )


def _load_profiles_doc_unmigrated(
    cfg: "SuiteConfig", username: str  # type: ignore[name-defined]
) -> Optional[RunProfilesDocument]:
    path = run_profiles_path(cfg, username)
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return RunProfilesDocument.model_validate(raw)


def load_run_profiles(
    cfg: "SuiteConfig", username: str  # type: ignore[name-defined]
) -> list[RunProfile]:
    ensure_user_dir(cfg, username)
    existing = _load_profiles_doc_unmigrated(cfg, username)
    if existing is not None:
        return existing.profiles
    return migrate_user_profiles(cfg, username).profiles


def save_run_profiles(
    cfg: "SuiteConfig", username: str, profiles: list[RunProfile]  # type: ignore[name-defined]
) -> RunProfilesDocument:
    ensure_user_dir(cfg, username)
    now = datetime.now(timezone.utc)
    existing = _load_profiles_doc_unmigrated(cfg, username)
    created_at = existing.created_at if existing is not None else now
    doc = RunProfilesDocument(
        profiles=profiles,
        created_at=created_at,
        modified_at=now,
    )
    _write_json_atomic(run_profiles_path(cfg, username), doc.model_dump(mode="json"))
    return doc


def migrate_user_profiles(
    cfg: "SuiteConfig", username: str  # type: ignore[name-defined]
) -> RunProfilesDocument:
    settings = load_execution_settings(cfg)
    profiles: list[RunProfile] = []

    for build in settings.build_presets:
        profiles.append(
            _local_profile_for_build(
                build,
                _local_env_id_for_build(settings, build.id),
            )
        )

    changed_settings = False
    for conn in load_connections(cfg, username):
        machine = _machine_from_connection(conn)
        if _find_by_id(settings.machine_presets, machine.id) is None:
            _upsert_by_id(settings.machine_presets, machine)
            changed_settings = True
        else:
            machine = _find_by_id(settings.machine_presets, machine.id)

        env_preset = _env_preset_from_connection(conn)
        if env_preset is not None:
            existing_env = _find_by_id(settings.env_presets, env_preset.id)
            if existing_env is None:
                _upsert_by_id(settings.env_presets, env_preset)
                changed_settings = True
            else:
                env_preset = existing_env

        for build in settings.build_presets:
            profiles.append(
                _profile_from_connection_and_build(
                    conn,
                    build,
                    machine,
                    env_preset,
                    _slurm_id_for_build(settings, build.id),
                )
            )

    if changed_settings:
        save_execution_settings(cfg, settings)
    return save_run_profiles(cfg, username, profiles)


def get_run_profile(
    cfg: "SuiteConfig", username: str, profile_id: str  # type: ignore[name-defined]
) -> Optional[RunProfile]:
    for profile in load_run_profiles(cfg, username):
        if profile.id == profile_id:
            return profile
    return None


def upsert_run_profile(
    cfg: "SuiteConfig", username: str, profile: RunProfile  # type: ignore[name-defined]
) -> None:
    items = load_run_profiles(cfg, username)
    _upsert_by_id(items, profile)
    save_run_profiles(cfg, username, items)


def delete_run_profile(
    cfg: "SuiteConfig", username: str, profile_id: str  # type: ignore[name-defined]
) -> bool:
    items = load_run_profiles(cfg, username)
    new_items = [profile for profile in items if profile.id != profile_id]
    if len(new_items) == len(items):
        return False
    save_run_profiles(cfg, username, new_items)
    return True


def run_profiles_referencing_key(
    cfg: "SuiteConfig", username: str, key_name: str  # type: ignore[name-defined]
) -> list[str]:
    """Return private run profile ids that reference *key_name*."""
    dependents: list[str] = []
    for profile in load_run_profiles(cfg, username):
        if profile.key_name == key_name or profile.gateway_key_name == key_name:
            dependents.append(profile.id)
    return dependents


def _validate_profile_refs(
    settings: ExecutionSettings,
    profile: RunProfile,
) -> tuple[
    Optional[BuildPreset],
    Optional[MachinePreset],
    Optional[EnvPreset],
    Optional[SlurmPreset],
    list[str],
]:
    errors: list[str] = []
    build = _find_by_id(settings.build_presets, profile.build_preset_id)
    machine = _find_by_id(settings.machine_presets, profile.machine_preset_id)
    env_preset = _find_by_id(settings.env_presets, profile.env_preset_id)
    slurm_preset = _find_by_id(settings.slurm_presets, profile.slurm_preset_id)
    if build is None:
        errors.append(f"Build preset '{profile.build_preset_id}' is missing.")
    if machine is None:
        errors.append(f"Machine preset '{profile.machine_preset_id}' is missing.")
    if profile.env_preset_id and env_preset is None:
        errors.append(f"Environment preset '{profile.env_preset_id}' is missing.")
    if profile.slurm_preset_id and slurm_preset is None:
        errors.append(f"Slurm preset '{profile.slurm_preset_id}' is missing.")
    if machine is not None:
        if machine.kind == "local" and profile.slurm_preset_id:
            errors.append("Local profiles cannot use Slurm presets.")
        if machine.kind == "ssh":
            if not profile.ssh_user:
                errors.append("SSH machine profiles require ssh_user.")
            if not profile.key_name:
                errors.append("SSH machine profiles require key_name.")
            if machine.gateway is not None:
                if not profile.gateway_user:
                    errors.append("Gateway machine profiles require gateway_user.")
                if machine.gateway.auth_method == "key" and not profile.gateway_key_name:
                    errors.append("Key-auth gateways require gateway_key_name.")
    return build, machine, env_preset, slurm_preset, errors


def summarize_profile(
    cfg: "SuiteConfig",  # type: ignore[name-defined]
    username: str,
    profile: RunProfile,
    settings: Optional[ExecutionSettings] = None,
) -> RunProfileSummary:
    settings = settings or load_execution_settings(cfg)
    build, machine, env_preset, slurm_preset, errors = _validate_profile_refs(
        settings, profile
    )
    env_style = env_preset.env.style if env_preset is not None else "none"
    default_info = (
        build.opalx_info_level
        if build is not None and build.opalx_info_level is not None
        else cfg.opalx_info_level
    )
    slurm_defaults = (
        slurm_preset.slurm.resource_defaults()
        if slurm_preset is not None and slurm_preset.slurm is not None
        else None
    )
    interactive = bool(
        machine is not None
        and machine.gateway is not None
        and machine.gateway.auth_method == "interactive"
    )

    if machine is not None and machine.kind == "ssh":
        keys = user_keys_dir(cfg, username)
        if profile.key_name and not (keys / f"{profile.key_name}.pem").is_file():
            errors.append(f"SSH key '{profile.key_name}' is missing.")
        if (
            machine.gateway is not None
            and machine.gateway.auth_method == "key"
            and profile.gateway_key_name
            and not (keys / f"{profile.gateway_key_name}.pem").is_file()
        ):
            errors.append(f"Gateway SSH key '{profile.gateway_key_name}' is missing.")

    return RunProfileSummary(
        id=profile.id,
        name=profile.name,
        description=profile.description,
        arch=build.id if build is not None else profile.build_preset_id,
        build_preset_id=profile.build_preset_id,
        build_preset_name=build.name if build is not None else profile.build_preset_id,
        machine_preset_id=profile.machine_preset_id,
        machine_preset_name=(
            machine.name if machine is not None else profile.machine_preset_id
        ),
        machine_kind=machine.kind if machine is not None else "ssh",
        env_preset_id=profile.env_preset_id,
        env_preset_name=env_preset.name if env_preset is not None else None,
        env_style=env_style,
        slurm_preset_id=profile.slurm_preset_id,
        slurm_preset_name=slurm_preset.name if slurm_preset is not None else None,
        default_mpi_ranks=build.mpi_ranks if build is not None else 1,
        max_mpi_ranks=build.max_mpi_ranks if build is not None else None,
        default_opalx_info_level=default_info,
        slurm_enabled=slurm_preset is not None,
        slurm_overrides_supported=(
            slurm_preset is not None and slurm_preset.slurm is not None
        ),
        slurm_defaults=slurm_defaults,
        interactive_gateway=interactive,
        generated=profile.generated,
        valid=not errors,
        validation_errors=errors,
    )


def _snapshot_for(
    build: BuildPreset,
    machine: MachinePreset,
    env_preset: Optional[EnvPreset],
    slurm_preset: Optional[SlurmPreset],
) -> ExecutionSnapshot:
    return ExecutionSnapshot(
        build=BuildPresetSnapshot(
            id=build.id,
            name=build.name,
            cmake_args=build.cmake_args,
            build_jobs=build.build_jobs,
            mpi_ranks=build.mpi_ranks,
            max_mpi_ranks=build.max_mpi_ranks,
            opalx_info_level=build.opalx_info_level,
        ),
        machine=MachinePresetSnapshot(
            id=machine.id,
            name=machine.name,
            kind=machine.kind,
            host=machine.host,
            port=machine.port,
            gateway_host=machine.gateway.host if machine.gateway is not None else None,
            gateway_port=machine.gateway.port if machine.gateway is not None else None,
            gateway_auth_method=(
                machine.gateway.auth_method if machine.gateway is not None else None
            ),
            queue_key=machine.queue_key,
        ),
        environment=(
            EnvPresetSnapshot(
                id=env_preset.id,
                name=env_preset.name,
                env=env_preset.env,
            )
            if env_preset is not None
            else None
        ),
        slurm=(
            SlurmPresetSnapshot(
                id=slurm_preset.id,
                name=slurm_preset.name,
                slurm=slurm_preset.slurm,
                slurm_args=slurm_preset.slurm_args,
                command_timeout=slurm_preset.command_timeout,
                salloc_timeout=slurm_preset.salloc_timeout,
            )
            if slurm_preset is not None
            else None
        ),
    )


def _arch_config_for(
    build: BuildPreset,
    env_preset: Optional[EnvPreset],
    slurm_preset: Optional[SlurmPreset],
) -> ArchConfig:
    return ArchConfig(
        arch=build.id,
        cmake_args=build.cmake_args,
        build_jobs=build.build_jobs,
        mpi_ranks=build.mpi_ranks,
        max_mpi_ranks=build.max_mpi_ranks,
        opalx_info_level=build.opalx_info_level,
        slurm=slurm_preset.slurm if slurm_preset is not None else None,
        slurm_args=slurm_preset.slurm_args if slurm_preset is not None else [],
        command_timeout=(
            slurm_preset.command_timeout if slurm_preset is not None else 0
        ),
        salloc_timeout=(
            slurm_preset.salloc_timeout if slurm_preset is not None else 0
        ),
        env=env_preset.env if env_preset is not None else EnvActivation(),
    )


def _connection_for(
    profile: RunProfile,
    machine: MachinePreset,
    env_preset: Optional[EnvPreset],
) -> Optional[Connection]:
    if machine.kind == "local":
        return None
    assert machine.host is not None
    gateway = None
    if machine.gateway is not None:
        gateway = GatewayEndpoint(
            host=machine.gateway.host,
            user=profile.gateway_user or "",
            port=machine.gateway.port,
            key_name=(
                None
                if machine.gateway.auth_method == "interactive"
                else profile.gateway_key_name
            ),
            auth_method=machine.gateway.auth_method,
        )
    return Connection(
        name=machine.id,
        description=profile.name,
        host=machine.host,
        user=profile.ssh_user or "",
        port=machine.port,
        key_name=profile.key_name or "",
        gateway=gateway,
        work_dir=profile.work_dir,
        cleanup_after_run=profile.cleanup_after_run,
        env=env_preset.env if env_preset is not None else EnvActivation(),
        keepalive_interval=profile.keepalive_interval,
        queue_key=machine.queue_key,
    )


def resolve_run_profile(
    cfg: "SuiteConfig", username: str, profile_id: str  # type: ignore[name-defined]
) -> ResolvedRunProfile:
    settings = load_execution_settings(cfg)
    profile = get_run_profile(cfg, username, profile_id)
    if profile is None:
        raise KeyError(f"Run profile '{profile_id}' not found for user '{username}'.")
    build, machine, env_preset, slurm_preset, errors = _validate_profile_refs(
        settings, profile
    )
    if errors:
        raise ValueError("; ".join(errors))
    assert build is not None
    assert machine is not None

    connection = _connection_for(profile, machine, env_preset)
    return ResolvedRunProfile(
        profile=profile,
        build=build,
        machine=machine,
        env_preset=env_preset,
        slurm_preset=slurm_preset,
        arch_config=_arch_config_for(build, env_preset, slurm_preset),
        connection=connection,
        execution_snapshot=_snapshot_for(build, machine, env_preset, slurm_preset),
    )


def suite_config_with_profile(
    cfg: "SuiteConfig", resolved: ResolvedRunProfile  # type: ignore[name-defined]
) -> "SuiteConfig":  # type: ignore[name-defined]
    arch_configs = [
        ac for ac in cfg.arch_configs if ac.arch != resolved.arch_config.arch
    ]
    arch_configs.insert(0, resolved.arch_config)
    default_architectures = list(cfg.default_architectures)
    if resolved.arch_config.arch not in default_architectures:
        default_architectures.insert(0, resolved.arch_config.arch)
    return cfg.model_copy(
        update={
            "arch_configs": arch_configs,
            "default_architectures": default_architectures,
        }
    )


def resolved_profile_key_paths(
    cfg: "SuiteConfig",
    username: str,
    resolved: ResolvedRunProfile,
) -> tuple[Optional[Path], Optional[Path]]:
    if resolved.connection is None:
        return None, None
    return resolve_connection_key_paths(cfg, username, resolved.connection)


def legacy_connection_to_profile_context(
    cfg: "SuiteConfig",
    username: str,
    *,
    arch: str,
    connection_name: Optional[str],
) -> Optional[ResolvedRunProfile]:
    """Best-effort bridge for legacy callers that still pass arch+connection.

    Returns a resolved generated profile only if it already exists after
    migration. This is intentionally not used as the primary legacy path; it
    exists so "Run again" can find a profile recommendation later.
    """
    if not connection_name or connection_name.lower() == "local":
        profile_id = _slug(f"local-{arch}", f"local-{arch}")
    else:
        profile_id = _slug(f"{connection_name}-{arch}", f"profile-{arch}")
    try:
        return resolve_run_profile(cfg, username, profile_id)
    except Exception:
        return None
