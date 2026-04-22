"""JWT authentication and user management."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
import bcrypt
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from ..config import SuiteConfig
from ..user_store import ensure_user_dir
from .deps import get_config, require_auth
from .tokens import (
    REFRESH_TOKEN_EXPIRE_DAYS,
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
)

REFRESH_COOKIE_NAME = "refresh_token"

# Per-IP login rate limit. ``get_remote_address`` picks up the client IP from
# the ASGI scope; behind nginx we rely on X-Forwarded-For being forwarded as
# the request's client.host (nginx default with proxy_set_header).
# Exported so api/app.py can register the handler on the FastAPI app.
login_limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── User store ────────────────────────────────────────────────────────────────

def load_users(cfg: SuiteConfig) -> dict[str, str]:
    path = cfg.resolved_users_file
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_users(cfg: SuiteConfig, users: dict[str, str]) -> None:
    path = cfg.resolved_users_file
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def add_user(cfg: SuiteConfig, username: str, plain_password: str) -> None:
    users = load_users(cfg)
    users[username] = hash_password(plain_password)
    save_users(cfg, users)


def delete_user(cfg: SuiteConfig, username: str) -> bool:
    users = load_users(cfg)
    if username not in users:
        return False
    del users[username]
    save_users(cfg, users)
    return True


# ── Schemas ───────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
@login_limiter.limit("10/minute")
def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    cfg: SuiteConfig = Depends(get_config),
):
    # ``request`` is required by slowapi's decorator so it can extract the
    # client IP; it is otherwise unused in the handler body.
    users = load_users(cfg)
    hashed = users.get(body.username)
    if hashed is None or not verify_password(body.password, hashed):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    access_token = create_access_token(body.username)
    refresh_token = create_refresh_token(body.username)
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path="/api/auth",
    )
    return TokenResponse(access_token=access_token)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path="/api/auth")
    return {"ok": True}


class MeResponse(BaseModel):
    username: str


@router.get("/me", response_model=MeResponse)
def me(
    username: Annotated[str, Depends(require_auth)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
):
    """Return the authenticated user's identity.

    Side-effect: idempotently materializes the per-user directory tree under
    ``<users_root>/<username>/`` so pre-existing users (created before per-user
    state existed) self-heal on first call.
    """
    ensure_user_dir(cfg, username)
    return MeResponse(username=username)


# ── Password change ──────────────────────────────────────────────────────────

MIN_PASSWORD_LENGTH = 12


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=1)


def _validate_new_password(current: str, new: str) -> Optional[str]:
    if len(new) < MIN_PASSWORD_LENGTH:
        return f"New password must be at least {MIN_PASSWORD_LENGTH} characters."
    if new == current:
        return "New password must differ from the current password."
    return None


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    response: Response,
    username: Annotated[str, Depends(require_auth)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
):
    """Rotate the caller's password.

    Requires the current password to prevent session-hijack attacks. On success
    the refresh-token cookie is cleared so the user is forced to re-authenticate
    with the new credentials on their next refresh.
    """
    users = load_users(cfg)
    hashed = users.get(username)
    if hashed is None or not verify_password(body.current_password, hashed):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect.",
        )
    problem = _validate_new_password(body.current_password, body.new_password)
    if problem is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=problem,
        )
    users[username] = hash_password(body.new_password)
    save_users(cfg, users)
    # Invalidate the long-lived refresh session so the attacker path (stolen
    # refresh cookie) cannot outlive the rotation.
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path="/api/auth")
    return {"ok": True}
