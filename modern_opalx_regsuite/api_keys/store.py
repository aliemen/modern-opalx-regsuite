"""Per-user persistence for :class:`ApiKeyRecord` values.

Records live at ``<user_dir>/api-keys.json`` alongside ``connections.json`` and
``ssh-keys/``. All writes are atomic (temp file + ``os.replace``) with 0600
permissions, mirroring ``api/keys.py``'s write discipline.

Concurrency: the per-user :func:`asyncio.Lock` in
``user_store.connections_lock`` is repurposed for api-keys serialization too --
both are cheap enough that sharing is fine and it keeps the lock surface small.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Iterator, TYPE_CHECKING

from .._atomic_write import write_secret_bytes_atomic
from .models import ApiKeyRecord

if TYPE_CHECKING:
    from ..config import SuiteConfig


_FILENAME = "api-keys.json"


def api_keys_path(user_dir: Path) -> Path:
    return user_dir / _FILENAME


# Reuse a per-user asyncio lock identical in spirit to
# :func:`user_store.connections_lock`. Kept local so the api-keys module stays
# independent of user_store internals.
_locks: dict[str, asyncio.Lock] = {}


def api_keys_lock(username: str) -> asyncio.Lock:
    lock = _locks.get(username)
    if lock is None:
        lock = asyncio.Lock()
        _locks[username] = lock
    return lock


def load(user_dir: Path) -> list[ApiKeyRecord]:
    """Read the user's records. Returns ``[]`` if the file is missing."""
    path = api_keys_path(user_dir)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    items = raw.get("api_keys", []) if isinstance(raw, dict) else raw
    out: list[ApiKeyRecord] = []
    for item in items:
        try:
            out.append(ApiKeyRecord.model_validate(item))
        except Exception:
            # Skip malformed entries rather than breaking every other key.
            continue
    return out


def save(user_dir: Path, records: list[ApiKeyRecord]) -> None:
    """Atomic write with 0600 permissions.

    Delegates to the shared helper in :mod:`modern_opalx_regsuite._atomic_write`
    so the record file never transiently exists with a more permissive mode.
    """
    user_dir.mkdir(parents=True, exist_ok=True)
    path = api_keys_path(user_dir)
    payload = {
        "api_keys": [r.model_dump(mode="json") for r in records],
    }
    encoded = json.dumps(payload, indent=2).encode("utf-8")
    write_secret_bytes_atomic(path, encoded)


def append(user_dir: Path, record: ApiKeyRecord) -> None:
    records = load(user_dir)
    records.append(record)
    save(user_dir, records)


def remove(user_dir: Path, key_id: str) -> ApiKeyRecord | None:
    records = load(user_dir)
    removed: ApiKeyRecord | None = None
    kept: list[ApiKeyRecord] = []
    for r in records:
        if r.id == key_id and removed is None:
            removed = r
        else:
            kept.append(r)
    if removed is None:
        return None
    save(user_dir, kept)
    return removed


def replace_by_id(
    user_dir: Path, key_id: str, new_record: ApiKeyRecord
) -> ApiKeyRecord | None:
    records = load(user_dir)
    previous: ApiKeyRecord | None = None
    for i, r in enumerate(records):
        if r.id == key_id:
            previous = r
            records[i] = new_record
            break
    if previous is None:
        return None
    save(user_dir, records)
    return previous


def touch_last_used(user_dir: Path, key_id: str, when) -> None:
    """Persist a fresh ``last_used_at``. Quiet-fails if the key is gone."""
    records = load(user_dir)
    changed = False
    for r in records:
        if r.id == key_id:
            r.last_used_at = when
            changed = True
            break
    if changed:
        save(user_dir, records)


def list_all_users(cfg: "SuiteConfig") -> Iterator[tuple[str, Path]]:
    """Yield ``(username, user_dir)`` for every user that has a per-user dir.

    Used on startup to rebuild the in-memory hash index. Safe to call when
    ``users_root`` does not yet exist.
    """
    root = cfg.resolved_users_root
    if not root.is_dir():
        return
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        # Users keep their own sub-dir even if they've never minted an API key,
        # so don't filter by api-keys.json presence here -- the caller does.
        yield child.name, child
