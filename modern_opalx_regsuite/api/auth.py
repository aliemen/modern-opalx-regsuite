"""JWT authentication and user management."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
import bcrypt
from pydantic import BaseModel

from ..config import SuiteConfig
from .deps import get_config
from .tokens import (
    REFRESH_TOKEN_EXPIRE_DAYS,
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
)

REFRESH_COOKIE_NAME = "refresh_token"

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
def login(body: LoginRequest, response: Response, cfg: SuiteConfig = Depends(get_config)):
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
