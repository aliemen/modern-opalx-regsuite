"""JSON-backed store for weekly schedules.

All schedules live in one shared file at ``<data_root>/schedules.json``. A
module-level :class:`asyncio.Lock` serializes read-modify-write operations to
avoid interleaved writes from concurrent API calls or the scheduler task.

Sensitive-data rule: only ``connection_name`` (user-chosen label) is stored in
this file — never the underlying SSH host, user, or key paths. Key resolution
happens at fire time via the owner's per-user connection store.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .models import Schedule, ScheduleCreateRequest, ScheduleUpdateRequest

if TYPE_CHECKING:
    from ..config import SuiteConfig


_store_lock: Optional[asyncio.Lock] = None


def _get_lock() -> asyncio.Lock:
    global _store_lock
    if _store_lock is None:
        _store_lock = asyncio.Lock()
    return _store_lock


def schedules_path(cfg: "SuiteConfig") -> Path:
    return cfg.resolved_data_root / "schedules.json"


def _read_raw(cfg: "SuiteConfig") -> list[Schedule]:
    path = schedules_path(cfg)
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("schedules", []) if isinstance(raw, dict) else raw
    return [Schedule.model_validate(item) for item in items]


def _write_raw(cfg: "SuiteConfig", schedules: list[Schedule]) -> None:
    path = schedules_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schedules": [s.model_dump(mode="json") for s in schedules]}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


# ── Public API ──────────────────────────────────────────────────────────────


async def list_schedules(cfg: "SuiteConfig") -> list[Schedule]:
    """Return all schedules (publicly visible)."""
    async with _get_lock():
        return _read_raw(cfg)


async def get_schedule(cfg: "SuiteConfig", schedule_id: str) -> Optional[Schedule]:
    async with _get_lock():
        for s in _read_raw(cfg):
            if s.id == schedule_id:
                return s
    return None


async def create_schedule(
    cfg: "SuiteConfig", owner: str, body: ScheduleCreateRequest
) -> Schedule:
    now = datetime.now(timezone.utc)
    schedule = Schedule(
        id=str(uuid.uuid4()),
        name=body.name,
        enabled=body.enabled,
        spec=body.spec,
        branch=body.branch,
        arch=body.arch,
        regtests_branch=body.regtests_branch,
        connection_name=body.connection_name,
        skip_unit=body.skip_unit,
        skip_regression=body.skip_regression,
        clean_build=body.clean_build,
        public=body.public,
        owner=owner,
        created_at=now,
        modified_at=now,
    )
    async with _get_lock():
        items = _read_raw(cfg)
        items.append(schedule)
        _write_raw(cfg, items)
    return schedule


async def update_schedule(
    cfg: "SuiteConfig",
    schedule_id: str,
    body: ScheduleUpdateRequest,
) -> Optional[Schedule]:
    """Replace the mutable fields of a schedule. Owner check is enforced by
    the caller (router), not here — this store is a dumb data layer."""
    now = datetime.now(timezone.utc)
    async with _get_lock():
        items = _read_raw(cfg)
        for i, existing in enumerate(items):
            if existing.id == schedule_id:
                updated = existing.model_copy(
                    update={
                        "name": body.name,
                        "enabled": body.enabled,
                        "spec": body.spec,
                        "branch": body.branch,
                        "arch": body.arch,
                        "regtests_branch": body.regtests_branch,
                        "connection_name": body.connection_name,
                        "skip_unit": body.skip_unit,
                        "skip_regression": body.skip_regression,
                        "clean_build": body.clean_build,
                        "public": body.public,
                        "modified_at": now,
                    }
                )
                items[i] = updated
                _write_raw(cfg, items)
                return updated
    return None


async def delete_schedule(cfg: "SuiteConfig", schedule_id: str) -> bool:
    async with _get_lock():
        items = _read_raw(cfg)
        new_items = [s for s in items if s.id != schedule_id]
        if len(new_items) == len(items):
            return False
        _write_raw(cfg, new_items)
        return True


async def update_schedule_runtime_state(
    cfg: "SuiteConfig",
    schedule_id: str,
    *,
    last_triggered_at: datetime,
    last_run_id: Optional[str],
    last_status: str,
    last_message: Optional[str] = None,
) -> None:
    """Persist the scheduler's ``last_*`` fields after a fire attempt."""
    async with _get_lock():
        items = _read_raw(cfg)
        for i, s in enumerate(items):
            if s.id == schedule_id:
                items[i] = s.model_copy(
                    update={
                        "last_triggered_at": last_triggered_at,
                        "last_run_id": last_run_id,
                        "last_status": last_status,
                        "last_message": last_message,
                    }
                )
                _write_raw(cfg, items)
                return
