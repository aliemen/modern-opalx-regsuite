"""In-memory ``sha256 -> (username, key_id)`` index for O(1) verification.

Rebuilt from ``api-keys.json`` across every user on startup
(:func:`rebuild`). Kept in sync by :mod:`.service` on create / rotate /
revoke.

This is process-local. Because the server runs single-worker (enforced by the
``serve`` CLI), we do not need cross-process coordination.
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from . import store

if TYPE_CHECKING:
    from ..config import SuiteConfig


# { sha256_hex : (username, key_id) }
_index: dict[str, tuple[str, str]] = {}
_lock = threading.Lock()


def rebuild(cfg: "SuiteConfig") -> int:
    """Discard and re-populate the index from disk. Returns the record count."""
    fresh: dict[str, tuple[str, str]] = {}
    for username, user_dir in store.list_all_users(cfg):
        for record in store.load(user_dir):
            fresh[record.secret_hash] = (username, record.id)
    with _lock:
        _index.clear()
        _index.update(fresh)
    return len(fresh)


def add(secret_hash: str, username: str, key_id: str) -> None:
    with _lock:
        _index[secret_hash] = (username, key_id)


def remove(secret_hash: str) -> None:
    with _lock:
        _index.pop(secret_hash, None)


def lookup(secret_hash: str) -> tuple[str, str] | None:
    with _lock:
        return _index.get(secret_hash)


def size() -> int:
    with _lock:
        return len(_index)


def clear() -> None:
    """For tests -- drop the entire index."""
    with _lock:
        _index.clear()
