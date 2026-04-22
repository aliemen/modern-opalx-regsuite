"""Stateless JWT helpers with no circular dependencies.

This module only imports from the standard library and third-party packages —
never from other api sub-modules — so it can be safely imported by both
auth.py and deps.py without creating a cycle.

JWT secret rotation
-------------------

``OPALX_SECRET_KEY`` holds the **primary** signing secret. Every newly issued
token is signed with this key. To rotate the secret without invalidating
in-flight sessions, set ``OPALX_SECRET_KEY_OLD`` to a comma-separated list of
**previously used** secrets that should still be accepted for *verification*.
Old secrets are never used to sign new tokens.

Typical rotation procedure:

1. Generate a fresh secret: ``python -c "import secrets; print(secrets.token_hex(32))"``.
2. Set ``OPALX_SECRET_KEY_OLD=<current value of OPALX_SECRET_KEY>``.
3. Set ``OPALX_SECRET_KEY=<new secret>``.
4. Restart the server. New tokens use the new secret; existing tokens keep
   working until they expire (access: 30 min, refresh: 30 days).
5. After the refresh-token expiry has passed, drop ``OPALX_SECRET_KEY_OLD``
   on the next restart.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 30
CONFIG_ENV_VAR = "OPALX_REGSUITE_CONFIG"
SECRET_KEY_ENV_VAR = "OPALX_SECRET_KEY"
OLD_SECRETS_ENV_VAR = "OPALX_SECRET_KEY_OLD"


def _get_primary_secret() -> str:
    """Return the current signing secret, raising if nothing is configured."""
    key = os.environ.get(SECRET_KEY_ENV_VAR, "")
    if not key:
        # Fall back to the config file only when no env var is set, so the
        # env var always wins for operators doing a zero-downtime rotation.
        try:
            from ..config import load_config
            key = load_config().resolved_secret_key
        except Exception:
            pass
    if not key:
        raise RuntimeError(
            "OPALX_SECRET_KEY env var is not set. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    return key


def _get_verification_secrets() -> list[str]:
    """Return every secret that should currently verify a token.

    Order is: primary first (most common), then any rotated-out secrets from
    ``OPALX_SECRET_KEY_OLD``. Empty / whitespace entries are skipped.
    """
    secrets = [_get_primary_secret()]
    raw_old = os.environ.get(OLD_SECRETS_ENV_VAR, "")
    for entry in raw_old.split(","):
        entry = entry.strip()
        if entry and entry not in secrets:
            secrets.append(entry)
    return secrets


def validate_secret_configuration() -> None:
    """Raise immediately if the JWT secret is not configured.

    Call this at app startup so the failure mode is "server refuses to boot"
    instead of "login endpoint crashes the first time anyone hits it". Safe
    to call more than once; idempotent.
    """
    _get_primary_secret()


def create_access_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": username, "exp": expire, "type": "access"},
        _get_primary_secret(),
        algorithm=ALGORITHM,
    )


def create_refresh_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": username, "exp": expire, "type": "refresh"},
        _get_primary_secret(),
        algorithm=ALGORITHM,
    )


def _decode(token: str, expected_type: str) -> Optional[str]:
    """Try each configured secret until one verifies the token, or return None.

    Rotation support: when ``OPALX_SECRET_KEY_OLD`` lists previously used
    secrets, tokens signed under any of them still verify until they expire.
    """
    for secret in _get_verification_secrets():
        try:
            payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
        except JWTError:
            continue
        if payload.get("type") != expected_type:
            return None
        return payload.get("sub")
    return None


def verify_access_token(token: str) -> Optional[str]:
    return _decode(token, "access")


def verify_refresh_token(token: str) -> Optional[str]:
    return _decode(token, "refresh")
