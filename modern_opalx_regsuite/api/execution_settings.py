"""Dashboard-managed execution settings and private run profiles."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..config import SuiteConfig
from ..execution_profiles import (
    ExecutionSettings,
    RunProfile,
    RunProfileSummary,
    delete_run_profile,
    get_run_profile,
    load_execution_settings,
    load_run_profiles,
    profiles_lock,
    public_settings_path,
    resolve_run_profile,
    resolved_profile_key_paths,
    save_execution_settings,
    summarize_profile,
    upsert_run_profile,
)
from ..remote import RemoteExecutor
from .deps import get_config, require_user_paths

router = APIRouter(prefix="/api/settings/execution", tags=["settings"])


def _validate_profile_keys(cfg: SuiteConfig, username: str, profile: RunProfile) -> None:
    summary = summarize_profile(cfg, username, profile)
    if summary.validation_errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="; ".join(summary.validation_errors),
        )


@router.get("/public", response_model=ExecutionSettings)
async def get_public_execution_settings(
    _user_paths: Annotated[tuple[str, Path], Depends(require_user_paths)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
) -> ExecutionSettings:
    return load_execution_settings(cfg)


@router.put("/public", response_model=ExecutionSettings)
async def replace_public_execution_settings(
    body: ExecutionSettings,
    _user_paths: Annotated[tuple[str, Path], Depends(require_user_paths)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
) -> ExecutionSettings:
    async with profiles_lock("_public"):
        return save_execution_settings(cfg, body)


@router.post("/public/reset-from-config", response_model=ExecutionSettings)
async def reset_public_execution_settings_from_config(
    _user_paths: Annotated[tuple[str, Path], Depends(require_user_paths)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
) -> ExecutionSettings:
    async with profiles_lock("_public"):
        path = public_settings_path(cfg)
        if path.exists():
            path.unlink()
        return load_execution_settings(cfg)


@router.get("/profiles", response_model=list[RunProfile])
async def list_profiles(
    user_paths: Annotated[tuple[str, Path], Depends(require_user_paths)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
) -> list[RunProfile]:
    username, _ = user_paths
    return load_run_profiles(cfg, username)


@router.get("/profile-summaries", response_model=list[RunProfileSummary])
async def list_profile_summaries(
    user_paths: Annotated[tuple[str, Path], Depends(require_user_paths)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
) -> list[RunProfileSummary]:
    username, _ = user_paths
    settings = load_execution_settings(cfg)
    return [
        summarize_profile(cfg, username, profile, settings)
        for profile in load_run_profiles(cfg, username)
    ]


@router.post("/profiles", response_model=RunProfile, status_code=201)
async def create_profile(
    body: RunProfile,
    user_paths: Annotated[tuple[str, Path], Depends(require_user_paths)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
) -> RunProfile:
    username, _ = user_paths
    async with profiles_lock(username):
        if get_run_profile(cfg, username, body.id) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Run profile '{body.id}' already exists.",
            )
        _validate_profile_keys(cfg, username, body)
        upsert_run_profile(cfg, username, body)
    return body


@router.get("/profiles/{profile_id}", response_model=RunProfile)
async def get_profile(
    profile_id: str,
    user_paths: Annotated[tuple[str, Path], Depends(require_user_paths)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
) -> RunProfile:
    username, _ = user_paths
    profile = get_run_profile(cfg, username, profile_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run profile '{profile_id}' not found.",
        )
    return profile


@router.put("/profiles/{profile_id}", response_model=RunProfile)
async def update_profile(
    profile_id: str,
    body: RunProfile,
    user_paths: Annotated[tuple[str, Path], Depends(require_user_paths)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
) -> RunProfile:
    if body.id != profile_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path id must match body.id (renames are not supported).",
        )
    username, _ = user_paths
    async with profiles_lock(username):
        if get_run_profile(cfg, username, profile_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run profile '{profile_id}' not found.",
            )
        _validate_profile_keys(cfg, username, body)
        upsert_run_profile(cfg, username, body)
    return body


@router.delete("/profiles/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: str,
    user_paths: Annotated[tuple[str, Path], Depends(require_user_paths)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
) -> None:
    username, _ = user_paths
    async with profiles_lock(username):
        if not delete_run_profile(cfg, username, profile_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run profile '{profile_id}' not found.",
            )


class ProfileTestCredentials(BaseModel):
    gateway_password: str | None = None
    gateway_otp: str | None = None


class ProfileTestResult(BaseModel):
    ok: bool
    whoami: str | None = None
    error: str | None = None


@router.post("/profiles/{profile_id}/test", response_model=ProfileTestResult)
async def test_profile(
    profile_id: str,
    user_paths: Annotated[tuple[str, Path], Depends(require_user_paths)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
    body: ProfileTestCredentials | None = None,
) -> ProfileTestResult:
    username, _ = user_paths
    try:
        resolved = resolve_run_profile(cfg, username, profile_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    if resolved.connection is None:
        return ProfileTestResult(ok=True, whoami="local")

    target_key, gateway_key = resolved_profile_key_paths(cfg, username, resolved)
    conn = resolved.connection
    if target_key is None or not target_key.is_file():
        return ProfileTestResult(ok=False, error=f"target key '{conn.key_name}' is missing")
    if (
        conn.gateway is not None
        and conn.gateway.auth_method != "interactive"
        and (gateway_key is None or not gateway_key.is_file())
    ):
        return ProfileTestResult(
            ok=False, error=f"gateway key '{conn.gateway.key_name}' is missing"
        )
    if (
        conn.gateway is not None
        and conn.gateway.auth_method == "interactive"
        and (not (body and body.gateway_password) or not (body and body.gateway_otp))
    ):
        return ProfileTestResult(
            ok=False,
            error=(
                "Interactive gateway requires 'gateway_password' and "
                "'gateway_otp' in the request body for testing."
            ),
        )

    def _do_test() -> ProfileTestResult:
        executor = RemoteExecutor(
            host=conn.host,
            user=conn.user,
            key_path=target_key,
            port=conn.port,
            connection_name=conn.name,
            gateway=conn.gateway,
            gateway_key_path=gateway_key,
            env=None,
            keepalive_interval=conn.keepalive_interval,
            gateway_password=body.gateway_password if body else None,
            gateway_otp=body.gateway_otp if body else None,
        )
        try:
            return ProfileTestResult(ok=True, whoami=executor.whoami())
        except Exception as exc:  # noqa: BLE001
            return ProfileTestResult(ok=False, error=f"{type(exc).__name__}: {exc}")
        finally:
            executor.close()

    return await asyncio.to_thread(_do_test)
