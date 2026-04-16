"""API-key management endpoints (per-user).

All endpoints here require a **JWT** session (``require_auth``), never an API
key -- you cannot mint, list, rotate, or revoke keys with another API key.
That way, a leaked scoped SSH-keys key can't bootstrap itself into broader
access.

Scope of the keys themselves is controlled separately via the ``scopes`` field
on :class:`..api_keys.ApiKeyCreateRequest`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from ..api_keys import ApiKeyCreated, ApiKeyInfo, service as api_keys_service
from ..api_keys.models import NAME_RE, ApiKeyCreateRequest
from ..api_keys.store import api_keys_lock
from .deps import require_user_paths

router = APIRouter(prefix="/api/settings/api-keys", tags=["settings"])


def _validate_name(name: str) -> None:
    if not NAME_RE.fullmatch(name):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="API key name must match [a-zA-Z0-9_-]+.",
        )


@router.get("", response_model=list[ApiKeyInfo])
def list_api_keys(
    user_paths: Annotated[tuple[str, Path], Depends(require_user_paths)],
) -> list[ApiKeyInfo]:
    """Return the user's API keys, newest first. Never exposes the secret hash."""
    _, user_dir = user_paths
    records = api_keys_service.list_records(user_dir)
    records.sort(key=lambda r: r.created_at, reverse=True)
    return [ApiKeyInfo.from_record(r) for r in records]


@router.post("", status_code=201, response_model=ApiKeyCreated)
async def create_api_key(
    body: ApiKeyCreateRequest,
    user_paths: Annotated[tuple[str, Path], Depends(require_user_paths)],
) -> ApiKeyCreated:
    """Mint a new API key. The returned ``secret`` is visible **only in this response**.

    After this response is closed, the server keeps only the sha256 hash --
    the plaintext cannot be recovered.
    """
    _validate_name(body.name)
    username, user_dir = user_paths
    async with api_keys_lock(username):
        existing = api_keys_service.list_records(user_dir)
        if any(r.name == body.name for r in existing):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"An API key named '{body.name}' already exists.",
            )
        record, plaintext = api_keys_service.create(user_dir, username, body)
    return ApiKeyCreated(
        **ApiKeyInfo.from_record(record).model_dump(),
        secret=plaintext,
    )


@router.post("/{key_id}/rotate", response_model=ApiKeyCreated)
async def rotate_api_key(
    key_id: str,
    user_paths: Annotated[tuple[str, Path], Depends(require_user_paths)],
) -> ApiKeyCreated:
    """Mint a new secret for an existing key id. Old secret stops working immediately.

    Preserves the key's ``id``, ``name``, ``scopes``, and ``expires_at``.
    """
    username, user_dir = user_paths
    async with api_keys_lock(username):
        result = api_keys_service.rotate(user_dir, username, key_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key '{key_id}' not found.",
        )
    record, plaintext = result
    return ApiKeyCreated(
        **ApiKeyInfo.from_record(record).model_dump(),
        secret=plaintext,
    )


@router.delete("/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: str,
    user_paths: Annotated[tuple[str, Path], Depends(require_user_paths)],
) -> None:
    username, user_dir = user_paths
    async with api_keys_lock(username):
        ok = api_keys_service.revoke(user_dir, username, key_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key '{key_id}' not found.",
        )
