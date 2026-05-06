"""JWT authentication and user management."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
import bcrypt
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from ..archive_service import locked_index
from ..data_model import (
    resolve_run_dir,
)
from ..scheduler.store import schedules_path
from ..config import SuiteConfig
from ..user_store import ensure_user_dir, profile_path, user_dir
from ..api_keys import index as api_keys_index
from .deps import get_config, require_auth
from .state import user_has_active_run, user_has_queued_run
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
    _write_json_atomic(cfg.resolved_users_file, users)


def _write_json_atomic(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)


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
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=1)


class ChangeUsernameRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_username: str = Field(..., min_length=1)
    confirm_username: str = Field(..., min_length=1)


class ChangeUsernameResponse(BaseModel):
    old_username: str
    new_username: str
    run_index_entries_changed: int
    run_meta_files_changed: int
    user_dir_moved: bool


def _validate_new_password(current: str, new: str) -> Optional[str]:
    if len(new) < MIN_PASSWORD_LENGTH:
        return f"New password must be at least {MIN_PASSWORD_LENGTH} characters."
    if new == current:
        return "New password must differ from the current password."
    return None


def _owned_schedule_count(cfg: SuiteConfig, username: str) -> int:
    path = schedules_path(cfg)
    if not path.is_file():
        return 0
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0
    items = raw.get("schedules", []) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return 0
    return sum(
        1
        for item in items
        if isinstance(item, dict) and item.get("owner") == username
    )


def _patch_profile_username(cfg: SuiteConfig, old_username: str, new_username: str) -> None:
    path = profile_path(cfg, new_username)
    data = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    if not isinstance(data, dict):
        data = {}
    data["username"] = new_username
    if "created_at" not in data:
        old_profile = profile_path(cfg, old_username)
        if old_profile.is_file():
            try:
                old_data = json.loads(old_profile.read_text(encoding="utf-8"))
                if isinstance(old_data, dict) and old_data.get("created_at"):
                    data["created_at"] = old_data["created_at"]
            except json.JSONDecodeError:
                pass
    _write_json_atomic(path, data)


def _move_user_dir(cfg: SuiteConfig, old_username: str, new_username: str) -> bool:
    ensure_user_dir(cfg, old_username)
    src = user_dir(cfg, old_username)
    dst = user_dir(cfg, new_username)
    if dst.exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User directory for '{new_username}' already exists.",
        )
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dst)
    _patch_profile_username(cfg, old_username, new_username)
    return True


def _patch_run_meta_triggered_by(run_path: Path, old_username: str, new_username: str) -> bool:
    meta_path = run_path / "run-meta.json"
    if not meta_path.is_file():
        return False
    try:
        with meta_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(data, dict) or data.get("triggered_by") != old_username:
        return False
    data["triggered_by"] = new_username
    _write_json_atomic(meta_path, data)
    return True


def _migrate_run_usernames(
    cfg: SuiteConfig, old_username: str, new_username: str
) -> tuple[int, int]:
    data_root = cfg.resolved_data_root
    archive_root = cfg.resolved_archive_root
    index_root = data_root / "runs-index"
    if not index_root.is_dir():
        return 0, 0

    index_changed = 0
    meta_changed = 0
    for idx_path in sorted(index_root.glob("*/*.json")):
        branch = idx_path.parent.name
        arch = idx_path.stem
        if not branch or not arch:
            continue
        with locked_index(idx_path):
            try:
                with idx_path.open("r", encoding="utf-8") as f:
                    entries = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(entries, list):
                continue
            changed = False
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                if entry.get("triggered_by") != old_username:
                    continue
                run_id = entry.get("run_id")
                if not isinstance(run_id, str):
                    continue
                entry["triggered_by"] = new_username
                index_changed += 1
                changed = True
                run_path = resolve_run_dir(
                    data_root,
                    archive_root,
                    branch,
                    arch,
                    run_id,
                    bool(entry.get("archived", False)),
                )
                if _patch_run_meta_triggered_by(
                    run_path, old_username, new_username
                ):
                    meta_changed += 1
            if changed:
                with idx_path.open("w", encoding="utf-8") as f:
                    json.dump(entries, f, indent=2, default=str)
    return index_changed, meta_changed


def _validate_username_change(
    cfg: SuiteConfig,
    username: str,
    body: ChangeUsernameRequest,
) -> dict[str, str]:
    users = load_users(cfg)
    hashed = users.get(username)
    if hashed is None or not verify_password(body.current_password, hashed):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect.",
        )

    new_username = body.new_username.strip()
    confirm_username = body.confirm_username.strip()
    if new_username != confirm_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username confirmation does not match.",
        )
    if new_username == username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New username must differ from the current username.",
        )
    if not USERNAME_RE.fullmatch(new_username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Username must be 3-64 characters and may contain only "
                "letters, numbers, underscores, dots, and hyphens."
            ),
        )
    if new_username in users:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{new_username}' already exists.",
        )
    if user_has_active_run(username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot rename while you have a running run.",
        )
    if user_has_queued_run(username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot rename while you have a queued run.",
        )
    schedule_count = _owned_schedule_count(cfg, username)
    if schedule_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot rename while you own {schedule_count} schedule"
                f"{'' if schedule_count == 1 else 's'}. Delete them first."
            ),
        )
    return users


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


@router.post("/change-username", response_model=ChangeUsernameResponse)
def change_username(
    body: ChangeUsernameRequest,
    response: Response,
    username: Annotated[str, Depends(require_auth)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
) -> ChangeUsernameResponse:
    """Rename the caller's account and historical run ownership records.

    This is intentionally strict: users with running/queued runs or any owned
    schedules must clear those first, so no scheduler or pipeline can write the
    old username while this synchronous migration is running.
    """
    users = _validate_username_change(cfg, username, body)
    new_username = body.new_username.strip()

    run_index_changed, run_meta_changed = _migrate_run_usernames(
        cfg, username, new_username
    )
    user_dir_moved = _move_user_dir(cfg, username, new_username)

    users[new_username] = users.pop(username)
    save_users(cfg, users)
    api_keys_index.rebuild(cfg)

    response.delete_cookie(key=REFRESH_COOKIE_NAME, path="/api/auth")
    return ChangeUsernameResponse(
        old_username=username,
        new_username=new_username,
        run_index_entries_changed=run_index_changed,
        run_meta_files_changed=run_meta_changed,
        user_dir_moved=user_dir_moved,
    )
