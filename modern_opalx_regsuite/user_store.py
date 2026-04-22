"""Per-user filesystem state for the OPALX regression suite.

Each authenticated regsuite user owns a directory tree under
``<users_root>/<username>/`` containing:

* ``profile.json``      — display metadata (created_at, etc.)
* ``connections.json``  — list of :class:`~modern_opalx_regsuite.config.Connection`
* ``ssh-keys/``         — private SSH keys, one ``.pem`` file per name

The dashboard / runs / queue stay global. Anything in this module's filesystem
tree is identity-bearing and **never** lives under ``data_root``, which may be
shared publicly.

Concurrency: ``connections.json`` CRUD is serialized per-user via a
module-level dict of :class:`asyncio.Lock`. Callers in async context should
acquire the lock with :func:`connections_lock` before read-modify-write.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .config import Connection, SuiteConfig

log = logging.getLogger("opalx.user_store")


# ── Filesystem helpers ───────────────────────────────────────────────────────

def user_dir(cfg: "SuiteConfig", username: str) -> Path:
    """Return the absolute path of the user's directory (does not create it)."""
    return cfg.resolved_users_root / username


def user_keys_dir(cfg: "SuiteConfig", username: str) -> Path:
    """Return the user's ssh-keys directory (does not create it)."""
    return user_dir(cfg, username) / "ssh-keys"


def connections_path(cfg: "SuiteConfig", username: str) -> Path:
    return user_dir(cfg, username) / "connections.json"


def profile_path(cfg: "SuiteConfig", username: str) -> Path:
    return user_dir(cfg, username) / "profile.json"


def ensure_user_dir(cfg: "SuiteConfig", username: str) -> Path:
    """Create ``<users_root>/<username>/`` and its standard sub-paths if missing.

    Idempotent. Sets ``ssh-keys/`` to mode 0700 since it holds private keys.
    Writes a minimal ``profile.json`` on first creation. Returns the user dir path.
    """
    udir = user_dir(cfg, username)
    udir.mkdir(parents=True, exist_ok=True)

    keys = user_keys_dir(cfg, username)
    keys.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(keys, 0o700)
    except OSError as exc:
        # Filesystem may not support chmod (e.g. some network mounts). Do not
        # raise — users must remain loginnable — but warn loudly: an ssh-keys
        # dir without 0700 means other local accounts on the server can read
        # private keys, which is a real exposure. The warning lands in the
        # regular uvicorn logs where operators see it.
        log.warning(
            "Could not chmod 0700 on ssh-keys dir %s: %s. Private keys in "
            "this directory may be world-readable on disk; verify your "
            "filesystem permissions manually.",
            keys,
            exc,
        )
    else:
        # After a successful chmod, verify the mode actually took — some
        # network filesystems silently accept chmod without applying it.
        try:
            mode = os.stat(keys).st_mode & 0o777
        except OSError:
            mode = None
        if mode is not None and mode != 0o700:
            log.warning(
                "ssh-keys dir %s reports mode %s after chmod(0o700). The "
                "filesystem may be ignoring permission changes; private key "
                "material may be exposed.",
                keys,
                oct(mode),
            )

    prof = profile_path(cfg, username)
    if not prof.exists():
        prof.write_text(
            json.dumps(
                {
                    "username": username,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    return udir


# ── Connections CRUD ─────────────────────────────────────────────────────────

# Per-user asyncio lock so concurrent requests for the same user serialize
# their read-modify-write of connections.json. Different users do not block
# each other.
_connections_locks: dict[str, asyncio.Lock] = {}


def connections_lock(username: str) -> asyncio.Lock:
    """Return (and lazily create) the per-user asyncio lock."""
    lock = _connections_locks.get(username)
    if lock is None:
        lock = asyncio.Lock()
        _connections_locks[username] = lock
    return lock


def load_connections(cfg: "SuiteConfig", username: str) -> list["Connection"]:
    """Load the user's connections from disk. Returns ``[]`` if the file is missing."""
    from .config import Connection  # local import to avoid cycle

    path = connections_path(cfg, username)
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("connections", []) if isinstance(raw, dict) else raw
    return [Connection.model_validate(item) for item in items]


def save_connections(
    cfg: "SuiteConfig", username: str, connections: list["Connection"]
) -> None:
    """Atomically write the connections list back to disk.

    Caller is responsible for holding ``connections_lock(username)`` if running
    inside an async context.
    """
    ensure_user_dir(cfg, username)
    path = connections_path(cfg, username)
    payload = {
        "connections": [c.model_dump(mode="json") for c in connections],
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def get_connection(
    cfg: "SuiteConfig", username: str, name: str
) -> Optional["Connection"]:
    """Return the named connection for *username*, or None if it doesn't exist."""
    for c in load_connections(cfg, username):
        if c.name == name:
            return c
    return None


def upsert_connection(
    cfg: "SuiteConfig", username: str, conn: "Connection"
) -> None:
    """Insert or replace a connection by name. Caller holds the per-user lock."""
    items = load_connections(cfg, username)
    replaced = False
    for i, existing in enumerate(items):
        if existing.name == conn.name:
            items[i] = conn
            replaced = True
            break
    if not replaced:
        items.append(conn)
    save_connections(cfg, username, items)


def delete_connection(cfg: "SuiteConfig", username: str, name: str) -> bool:
    """Remove a connection by name. Returns True if it existed."""
    items = load_connections(cfg, username)
    new_items = [c for c in items if c.name != name]
    if len(new_items) == len(items):
        return False
    save_connections(cfg, username, new_items)
    return True


def connections_referencing_key(
    cfg: "SuiteConfig", username: str, key_name: str
) -> list[str]:
    """Return the names of connections (and their gateways) that use *key_name*."""
    referencing: list[str] = []
    for c in load_connections(cfg, username):
        if c.key_name == key_name:
            referencing.append(c.name)
            continue
        if c.gateway is not None and c.gateway.key_name and c.gateway.key_name == key_name:
            referencing.append(c.name)
    return referencing


# ── Key path resolution ──────────────────────────────────────────────────────

def resolve_connection_key_paths(
    cfg: "SuiteConfig", username: str, conn: "Connection"
) -> tuple[Path, Optional[Path]]:
    """Return ``(target_key_path, gateway_key_path)`` for a connection.

    Both paths are absolute. ``gateway_key_path`` is ``None`` when the
    connection has no gateway. **This function does not check that the files
    exist** — callers should verify before launching a run.
    """
    keys = user_keys_dir(cfg, username)
    target = keys / f"{conn.key_name}.pem"
    gateway = None
    if (
        conn.gateway is not None
        and conn.gateway.auth_method != "interactive"
        and conn.gateway.key_name
    ):
        gateway = keys / f"{conn.gateway.key_name}.pem"
    return target, gateway
