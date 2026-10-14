"""Global test skip configs (Settings -> Execution -> Test Skips)."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from ..config import SuiteConfig
from ..execution_profiles import profiles_lock
from ..skip_configs import (
    SkipCandidates,
    SkipConfig,
    SkipConfigInput,
    collect_skip_candidates,
    create_skip_config,
    delete_skip_config,
    load_skip_configs,
    update_skip_config,
)
from .deps import get_config, require_user_paths

router = APIRouter(prefix="/api/settings/execution/test-skips", tags=["settings"])
_LOCK_KEY = "_public-test-skips"

UserPaths = Annotated[tuple[str, Path], Depends(require_user_paths)]
Config = Annotated[SuiteConfig, Depends(get_config)]


@router.get("", response_model=list[SkipConfig])
async def list_skip_configs(_user_paths: UserPaths, cfg: Config) -> list[SkipConfig]:
    return load_skip_configs(cfg).configs


@router.get("/candidates", response_model=SkipCandidates)
def skip_candidates(_user_paths: UserPaths, cfg: Config) -> SkipCandidates:
    return collect_skip_candidates(cfg)


@router.post("", response_model=SkipConfig, status_code=status.HTTP_201_CREATED)
async def create(
    body: SkipConfigInput, _user_paths: UserPaths, cfg: Config
) -> SkipConfig:
    async with profiles_lock(_LOCK_KEY):
        try:
            return create_skip_config(cfg, body)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)
            ) from exc


@router.put("/{config_id}", response_model=SkipConfig)
async def replace(
    config_id: str, body: SkipConfigInput, _user_paths: UserPaths, cfg: Config
) -> SkipConfig:
    async with profiles_lock(_LOCK_KEY):
        try:
            return update_skip_config(cfg, config_id, body)
        except KeyError as exc:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "Skip config not found."
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)
            ) from exc


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(config_id: str, _user_paths: UserPaths, cfg: Config) -> Response:
    async with profiles_lock(_LOCK_KEY):
        if not delete_skip_config(cfg, config_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Skip config not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
