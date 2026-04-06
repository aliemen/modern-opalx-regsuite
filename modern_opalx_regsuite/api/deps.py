"""FastAPI dependency helpers shared across all routers."""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..config import SuiteConfig, load_config
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
