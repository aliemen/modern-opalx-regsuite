"""Public schedules API.

Endpoints under ``/api/schedules``:

* ``GET    /``           list every schedule (visible to all authenticated users)
* ``POST   /``           create a schedule owned by the caller
* ``GET    /{id}``       fetch one
* ``PUT    /{id}``       update one (owner only)
* ``POST   /{id}/toggle`` flip the ``enabled`` flag (owner only)
* ``DELETE /{id}``       delete one (**any** authenticated user, by design —
                          lets live users remove stale schedules from inactive
                          users so the pipeline doesn't get blocked)

On create and update, the schedule's ``connection_name`` is validated against
the owner's per-user connection store: unknown names and interactive-2FA
gateways are rejected (the scheduler cannot handle single-use OTPs).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from ..config import SuiteConfig
from ..scheduler.models import (
    Schedule,
    ScheduleCreateRequest,
    ScheduleUpdateRequest,
)
from ..scheduler.store import (
    create_schedule,
    delete_schedule,
    get_schedule,
    list_schedules,
    update_schedule,
)
from ..scheduler.validation import (
    ScheduleValidationError,
    resolve_scheduled_connection,
)
from .deps import get_config, require_auth

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


def _validate_connection_for_owner(
    cfg: SuiteConfig, owner: str, connection_name: str
) -> None:
    """Raise HTTP errors if the connection is unknown or uses 2FA."""
    try:
        resolve_scheduled_connection(cfg, owner, connection_name)
    except ScheduleValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("", response_model=list[Schedule])
async def list_all_schedules(
    _user: Annotated[str, Depends(require_auth)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
) -> list[Schedule]:
    """Return every schedule, sorted newest-first by creation time."""
    items = await list_schedules(cfg)
    return sorted(items, key=lambda s: s.created_at, reverse=True)


@router.post("", response_model=Schedule, status_code=status.HTTP_201_CREATED)
async def create_schedule_endpoint(
    body: ScheduleCreateRequest,
    username: Annotated[str, Depends(require_auth)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
) -> Schedule:
    _validate_connection_for_owner(cfg, username, body.connection_name)
    return await create_schedule(cfg, owner=username, body=body)


@router.get("/{schedule_id}", response_model=Schedule)
async def get_schedule_endpoint(
    schedule_id: str,
    _user: Annotated[str, Depends(require_auth)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
) -> Schedule:
    schedule = await get_schedule(cfg, schedule_id)
    if schedule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule '{schedule_id}' not found.",
        )
    return schedule


@router.put("/{schedule_id}", response_model=Schedule)
async def update_schedule_endpoint(
    schedule_id: str,
    body: ScheduleUpdateRequest,
    username: Annotated[str, Depends(require_auth)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
) -> Schedule:
    existing = await get_schedule(cfg, schedule_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule '{schedule_id}' not found.",
        )
    if existing.owner != username:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Only the owner ('{existing.owner}') can edit this schedule."
            ),
        )
    _validate_connection_for_owner(cfg, username, body.connection_name)
    updated = await update_schedule(cfg, schedule_id, body)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule '{schedule_id}' not found.",
        )
    return updated


@router.post("/{schedule_id}/toggle", response_model=Schedule)
async def toggle_schedule_endpoint(
    schedule_id: str,
    username: Annotated[str, Depends(require_auth)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
) -> Schedule:
    """Flip the ``enabled`` flag. Owner only."""
    existing = await get_schedule(cfg, schedule_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule '{schedule_id}' not found.",
        )
    if existing.owner != username:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Only the owner ('{existing.owner}') can toggle this schedule."
            ),
        )
    body = ScheduleUpdateRequest(
        name=existing.name,
        enabled=not existing.enabled,
        spec=existing.spec,
        branch=existing.branch,
        arch=existing.arch,
        regtests_branch=existing.regtests_branch,
        connection_name=existing.connection_name,
        skip_unit=existing.skip_unit,
        skip_regression=existing.skip_regression,
    )
    # Re-validate the connection on enable in case it has since gained 2FA.
    if body.enabled:
        _validate_connection_for_owner(cfg, username, body.connection_name)
    updated = await update_schedule(cfg, schedule_id, body)
    assert updated is not None  # existence confirmed above
    return updated


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule_endpoint(
    schedule_id: str,
    _user: Annotated[str, Depends(require_auth)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
) -> None:
    """Delete a schedule.

    **Any** authenticated user may delete any schedule. This is intentional:
    otherwise stale schedules from inactive users could permanently block the
    pipeline. The owner controls create/edit/toggle, but delete is open.
    """
    if not await delete_schedule(cfg, schedule_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule '{schedule_id}' not found.",
        )
