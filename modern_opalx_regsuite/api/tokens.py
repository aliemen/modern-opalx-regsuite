"""Stateless JWT helpers with no circular dependencies.

This module only imports from the standard library and third-party packages —
never from other api sub-modules — so it can be safely imported by both
auth.py and deps.py without creating a cycle.
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


def _get_secret() -> str:
    key = os.environ.get(SECRET_KEY_ENV_VAR, "")
    if not key:
        # Try loading from config as a last resort (avoids importing config at module level).
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


def create_access_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": username, "exp": expire, "type": "access"},
        _get_secret(),
        algorithm=ALGORITHM,
    )


def create_refresh_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": username, "exp": expire, "type": "refresh"},
        _get_secret(),
        algorithm=ALGORITHM,
    )


def _decode(token: str, expected_type: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, _get_secret(), algorithms=[ALGORITHM])
        if payload.get("type") != expected_type:
            return None
        return payload.get("sub")
    except JWTError:
        return None


def verify_access_token(token: str) -> Optional[str]:
    return _decode(token, "access")


def verify_refresh_token(token: str) -> Optional[str]:
    return _decode(token, "refresh")
