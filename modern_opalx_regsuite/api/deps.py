"""FastAPI dependency helpers shared across all routers."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..config import SuiteConfig, load_config
from ..user_store import ensure_user_dir
from .tokens import verify_access_token

_bearer = HTTPBearer(auto_error=False)


@lru_cache(maxsize=1)
def get_config() -> SuiteConfig:
    """Load config once at startup and cache it."""
    return load_config()


def require_auth(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer)
    ],
) -> str:
    """Return the username from a valid Bearer token, or raise 401."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username = verify_access_token(credentials.credentials)
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username


def require_user_paths(
    username: Annotated[str, Depends(require_auth)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
) -> tuple[str, Path]:
    """Return ``(username, user_dir)`` and idempotently create the user dir.

    Use this dependency for any endpoint that touches per-user state (SSH keys,
    connections, profile). It ensures users added by hand or pre-existing in
    ``users.json`` self-heal on first access.
    """
    udir = ensure_user_dir(cfg, username)
    return username, udir
