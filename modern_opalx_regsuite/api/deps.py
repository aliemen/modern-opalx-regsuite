"""FastAPI dependency helpers shared across all routers."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..api_keys import ApiKeyScope, TOKEN_PREFIX, service as api_keys_service
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
    """Return the username from a valid JWT Bearer token, or raise 401.

    This dependency is **JWT-only**. Long-lived API keys are explicitly
    rejected here so that a leaked scoped API key cannot authenticate on
    routers that have not been audited for the scope model (runs, connections,
    archive, api-key management itself, etc.). API-key-capable endpoints must
    use :func:`require_scoped` instead.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    if token.startswith(TOKEN_PREFIX):
        # Clear, specific message -- the client is using the wrong credential
        # type, not the wrong token value.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "This endpoint requires a session JWT. API keys only work on "
                "SSH-key endpoints under /api/settings/ssh-keys."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )
    username = verify_access_token(token)
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


def require_scoped(*required_scopes: ApiKeyScope) -> Callable[..., str]:
    """Accept **either** a JWT (all scopes) **or** an API key with the given scopes.

    Use on routers that are reachable both from the web UI (JWT) and from the
    scripted bash client (scoped API key). Today only SSH-key endpoints use
    this -- every other endpoint stays on :func:`require_auth`.

    ``Depends(...)`` is attached via **default-parameter** syntax rather than
    ``Annotated[..., Depends(...)]`` here because this function is a nested
    closure over ``required``; combined with ``from __future__ import
    annotations``, the ``Annotated`` form becomes an unresolvable forward
    reference at FastAPI's type-hint introspection time.
    """
    required: tuple[ApiKeyScope, ...] = tuple(required_scopes)

    def _check(
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
        cfg: SuiteConfig = Depends(get_config),
    ) -> str:
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = credentials.credentials
        if token.startswith(TOKEN_PREFIX):
            result = api_keys_service.verify(cfg, token)
            if result is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired API key",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            record, username = result
            if not api_keys_service.has_scope(record, required):
                missing = sorted(
                    s.value for s in required if s not in record.scopes
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "API key missing required scope(s): "
                        + ", ".join(missing)
                    ),
                )
            return username
        # Fall through: JWT. JWTs implicitly carry every scope.
        username = verify_access_token(token)
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return username

    return _check


def require_user_paths_scoped(
    *required_scopes: ApiKeyScope,
) -> Callable[..., tuple[str, Path]]:
    """Scoped analogue of :func:`require_user_paths`.

    Authenticates via :func:`require_scoped` and materializes the user's
    filesystem tree, so SSH-key endpoints keep working the first time a new
    user hits them via API key (no prior web-UI login needed).
    """
    scoped = require_scoped(*required_scopes)

    # Default-param Depends() for the same forward-reference reason as above.
    def _inner(
        username: str = Depends(scoped),
        cfg: SuiteConfig = Depends(get_config),
    ) -> tuple[str, Path]:
        udir = ensure_user_dir(cfg, username)
        return username, udir

    return _inner
