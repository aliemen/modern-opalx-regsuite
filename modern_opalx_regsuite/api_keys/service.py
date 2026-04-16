"""High-level create / verify / rotate / revoke for API keys.

The router (:mod:`..api.api_keys`) and the ``require_scoped`` auth dependency
(:mod:`..api.deps`) go through this module; they never touch
:mod:`.store` / :mod:`.index` directly.

Key format on the wire::

    opalx_<prefix>_<secret>

* ``prefix``  - 8 base64url chars, shown in the UI for at-a-glance recognition.
* ``secret``  - 43 base64url chars (32 random bytes); the security surface.

Only ``sha256(full_token).hexdigest()`` is persisted; plaintext lives for the
lifetime of one create/rotate HTTP response.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from . import index, store
from .models import (
    ApiKeyCreateRequest,
    ApiKeyRecord,
    ApiKeyScope,
    NAME_RE,
    TOKEN_PREFIX,
)

if TYPE_CHECKING:
    from ..config import SuiteConfig


log = logging.getLogger("opalx.api_keys")

_PREFIX_LEN = 8
_SECRET_BYTES = 32

# Smoothing for last_used_at: writes are coalesced to at most one per minute
# per key. The UI only shows minute-level resolution anyway, and this avoids
# a write storm when a CI runner hammers the API.
_LAST_USED_WRITE_THROTTLE_SEC = 60


# --- token construction --------------------------------------------------


def _mint_token() -> tuple[str, str, str]:
    """Return ``(full_token, prefix, sha256_hex)`` for a freshly minted secret."""
    prefix = secrets.token_urlsafe(6)[:_PREFIX_LEN]
    secret = secrets.token_urlsafe(_SECRET_BYTES)
    full = f"{TOKEN_PREFIX}{prefix}_{secret}"
    digest = hashlib.sha256(full.encode("ascii")).hexdigest()
    return full, prefix, digest


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _validate_name(name: str) -> None:
    if not name or not NAME_RE.fullmatch(name):
        raise ValueError("API key name must match [a-zA-Z0-9_-]+.")


# --- create / rotate / revoke -------------------------------------------


def create(
    user_dir: Path,
    username: str,
    req: ApiKeyCreateRequest,
) -> tuple[ApiKeyRecord, str]:
    """Mint a new API key, persist it, update the in-memory index.

    Returns ``(record, plaintext_token)``. The plaintext is returned exactly
    once -- callers must ship it to the user in the HTTP response and discard
    it. Never log it.
    """
    _validate_name(req.name)

    full, prefix, digest = _mint_token()
    now = datetime.now(timezone.utc)
    expires_at = None
    if req.expires_in_days is not None:
        expires_at = now + timedelta(days=req.expires_in_days)

    record = ApiKeyRecord(
        id=uuid.uuid4().hex,
        name=req.name,
        prefix=prefix,
        secret_hash=digest,
        scopes=list(dict.fromkeys(req.scopes)),  # de-dup while preserving order
        created_at=now,
        last_used_at=None,
        expires_at=expires_at,
    )
    store.append(user_dir, record)
    index.add(digest, username, record.id)
    log.info(
        "api-keys: minted id=%s user=%s prefix=%s scopes=%s",
        record.id,
        username,
        record.prefix,
        [s.value for s in record.scopes],
    )
    return record, full


def rotate(
    user_dir: Path, username: str, key_id: str
) -> tuple[ApiKeyRecord, str] | None:
    """Replace the secret of an existing key. Name / scopes / expiry preserved.

    Old secret is invalidated immediately (removed from the index); callers
    must redistribute the new secret to their clients atomically.
    """
    records = store.load(user_dir)
    previous: ApiKeyRecord | None = None
    for r in records:
        if r.id == key_id:
            previous = r
            break
    if previous is None:
        return None

    full, prefix, digest = _mint_token()
    new_record = previous.model_copy(
        update={
            "prefix": prefix,
            "secret_hash": digest,
            "created_at": datetime.now(timezone.utc),
            "last_used_at": None,
        }
    )
    store.replace_by_id(user_dir, key_id, new_record)
    index.remove(previous.secret_hash)
    index.add(digest, username, new_record.id)
    log.info(
        "api-keys: rotated id=%s user=%s old_prefix=%s new_prefix=%s",
        new_record.id,
        username,
        previous.prefix,
        new_record.prefix,
    )
    return new_record, full


def revoke(user_dir: Path, username: str, key_id: str) -> bool:
    """Delete a key. Returns ``False`` if the id was unknown."""
    removed = store.remove(user_dir, key_id)
    if removed is None:
        return False
    index.remove(removed.secret_hash)
    log.info(
        "api-keys: revoked id=%s user=%s prefix=%s",
        removed.id,
        username,
        removed.prefix,
    )
    return True


def list_records(user_dir: Path) -> list[ApiKeyRecord]:
    return store.load(user_dir)


# --- verify (the hot path) ---------------------------------------------


def verify(
    cfg: "SuiteConfig",
    token: str,
) -> tuple[ApiKeyRecord, str] | None:
    """Authenticate a bearer token as an API key.

    Returns ``(record, username)`` on success. Returns ``None`` if the token
    is not an API key, is unknown, or is expired. Side-effect: throttled
    update of ``last_used_at`` on success.

    Callers do **not** need to guard against non-API tokens; we return
    ``None`` if the token doesn't start with :data:`TOKEN_PREFIX`.
    """
    if not token or not token.startswith(TOKEN_PREFIX):
        return None

    digest = _hash_token(token)
    found = index.lookup(digest)
    if found is None:
        return None
    username, key_id = found

    user_dir = cfg.resolved_users_root / username
    records = store.load(user_dir)
    record: ApiKeyRecord | None = None
    for r in records:
        if r.id == key_id:
            # Defence in depth: re-compare the stored hash directly instead of
            # trusting the index alone. ``compare_digest`` to avoid timing
            # leaks on the byte-by-byte comparison.
            if hmac.compare_digest(r.secret_hash, digest):
                record = r
            break

    if record is None:
        # Index was stale (key was deleted out-of-band). Clean it up.
        index.remove(digest)
        return None

    now = datetime.now(timezone.utc)
    if record.expires_at is not None and record.expires_at <= now:
        return None

    _maybe_touch_last_used(user_dir, record, now)
    return record, username


def _maybe_touch_last_used(
    user_dir: Path, record: ApiKeyRecord, now: datetime
) -> None:
    """Coalesced write of ``last_used_at`` (at most once per 60 s)."""
    prev = record.last_used_at
    if prev is not None:
        delta = (now - prev).total_seconds()
        if delta < _LAST_USED_WRITE_THROTTLE_SEC:
            return
    try:
        store.touch_last_used(user_dir, record.id, now)
        record.last_used_at = now
    except Exception:
        # Never fail a request because of a housekeeping write.
        log.debug("api-keys: failed to touch last_used_at", exc_info=True)


def has_scope(record: ApiKeyRecord, required: tuple[ApiKeyScope, ...]) -> bool:
    return set(required).issubset(set(record.scopes))
