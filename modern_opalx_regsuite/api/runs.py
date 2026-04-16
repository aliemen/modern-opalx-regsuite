"""Endpoints to trigger, query, cancel, and queue pipeline runs."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..config import SuiteConfig
from ..user_store import get_connection
from .deps import get_config, require_auth
from .runs_core import start_run
from .state import (
    cancel_active_run,
    cancel_queued_run,
    get_active_run,
    get_all_active_runs,
    get_queue_snapshot,
)

router = APIRouter(prefix="/api/runs", tags=["runs"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class TriggerRequest(BaseModel):
    branch: str
    arch: str
    regtests_branch: Optional[str] = None
    skip_unit: bool = False
    skip_regression: bool = False
    # Wipe the per-branch/arch build directory before cmake. Forces a full
    # reconfigure + recompile; leaves source checkouts and run data intact.
    clean_build: bool = False
    # None or "local" → local execution. Otherwise → load the calling user's
    # named connection from <users_root>/<username>/connections.json.
    connection_name: Optional[str] = None
    # Interactive gateway credentials — required when the connection's gateway
    # uses auth_method="interactive".  Held in memory only; never persisted.
    gateway_password: Optional[str] = None
    gateway_otp: Optional[str] = None


class TriggerResponse(BaseModel):
    run_id: str
    queued: bool = False
    queue_id: Optional[str] = None
    position: Optional[int] = None


class CurrentRunStatus(BaseModel):
    run_id: str
    branch: str
    arch: str
    status: str
    phase: str
    started_at: datetime
    machine_id: Optional[str] = None
    connection_name: Optional[str] = None


class QueuedRunInfo(BaseModel):
    queue_id: str
    run_id: str
    branch: str
    arch: str
    queued_at: datetime
    connection_name: Optional[str] = None


class MachineStatus(BaseModel):
    machine_id: str
    active_run: Optional[CurrentRunStatus] = None
    queue: list[QueuedRunInfo] = []


class QueueStateResponse(BaseModel):
    machines: list[MachineStatus]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run_id_from_time() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/archs", response_model=list[str])
def list_archs(
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
):
    """Return all configured architecture identifiers."""
    names = list(cfg.default_architectures)
    for ac in cfg.arch_configs:
        if ac.arch not in names:
            names.append(ac.arch)
    return names


@router.get("/current", response_model=Optional[CurrentRunStatus])
def get_current_run(_user: Annotated[str, Depends(require_auth)]):
    """Return the first active run (backward compat for navbar / live page)."""
    run = get_active_run()
    if run is None:
        return None
    return CurrentRunStatus(
        run_id=run.run_id,
        branch=run.branch,
        arch=run.arch,
        status=run.status,
        phase=run.phase,
        started_at=run.started_at,
        machine_id=run.machine_id,
        connection_name=run.connection_name,
    )


@router.get("/active", response_model=list[CurrentRunStatus])
def list_active_runs(_user: Annotated[str, Depends(require_auth)]):
    """Return all currently running runs."""
    return [
        CurrentRunStatus(
            run_id=r.run_id,
            branch=r.branch,
            arch=r.arch,
            status=r.status,
            phase=r.phase,
            started_at=r.started_at,
            machine_id=r.machine_id,
            connection_name=r.connection_name,
        )
        for r in get_all_active_runs()
    ]


@router.get("/queue", response_model=QueueStateResponse)
def get_queue_state_endpoint(_user: Annotated[str, Depends(require_auth)]):
    """Return the full queue state for all machines."""
    snapshot = get_queue_snapshot()
    machines = []
    for m in snapshot:
        active = None
        if m["active_run"] is not None:
            active = CurrentRunStatus(**m["active_run"])
        queue_items = [QueuedRunInfo(**qi) for qi in m["queue"]]
        machines.append(MachineStatus(
            machine_id=m["machine_id"],
            active_run=active,
            queue=queue_items,
        ))
    return QueueStateResponse(machines=machines)


@router.post("/trigger", response_model=TriggerResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_run(
    body: TriggerRequest,
    username: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
):
    run_id = _run_id_from_time()

    # HTTP-specific pre-validation: interactive 2FA gateways must receive
    # credentials in the request body. start_run() doesn't know about the
    # request body so we enforce this here before calling it.
    if body.connection_name and body.connection_name.lower() != "local":
        conn = get_connection(cfg, username, body.connection_name)
        if conn is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"Connection '{body.connection_name}' not found for user "
                    f"'{username}'."
                ),
            )
        if (
            conn.gateway is not None
            and conn.gateway.auth_method == "interactive"
            and (not body.gateway_password or not body.gateway_otp)
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "This connection uses an interactive gateway (password + 2FA). "
                    "Provide 'gateway_password' and 'gateway_otp' in the request body."
                ),
            )

    result = await start_run(
        cfg,
        run_id=run_id,
        triggered_by=username,
        owner_for_connection=username,
        branch=body.branch,
        arch=body.arch,
        regtests_branch=body.regtests_branch,
        skip_unit=body.skip_unit,
        skip_regression=body.skip_regression,
        clean_build=body.clean_build,
        connection_name=body.connection_name,
        gateway_password=body.gateway_password,
        gateway_otp=body.gateway_otp,
    )

    if result.outcome == "started":
        return TriggerResponse(run_id=result.run_id)
    if result.outcome == "queued":
        return TriggerResponse(
            run_id=result.run_id,
            queued=True,
            queue_id=result.queue_id,
            position=result.position,
        )
    if result.outcome == "missing_connection":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result.detail or "Connection not found.",
        )
    if result.outcome == "missing_key":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=result.detail or "Required SSH key is missing on disk.",
        )
    if result.outcome == "busy_interactive":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This machine is currently busy and the connection uses an "
                "interactive gateway with single-use 2FA credentials. "
                "Queuing is not possible - the OTP would expire before the "
                "run starts. Please try again when the machine is free."
            ),
        )
    # Should be unreachable.
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Unknown start_run outcome: {result.outcome}",
    )


@router.post("/current/cancel")
def cancel_current_run_legacy(_user: Annotated[str, Depends(require_auth)]):
    """Cancel the first active run (backward compat)."""
    run = get_active_run()
    if run is None or run.status != "running":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active run to cancel.",
        )
    run.cancel_event.set()
    return {"ok": True}


@router.post("/{run_id}/cancel")
async def cancel_run_by_id(
    run_id: str,
    _user: Annotated[str, Depends(require_auth)],
):
    """Cancel a specific active run by its run_id."""
    ok = await cancel_active_run(run_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active run with that ID.",
        )
    return {"ok": True}


@router.delete("/queue/{queue_id}")
async def cancel_queued_run_endpoint(
    queue_id: str,
    _user: Annotated[str, Depends(require_auth)],
):
    """Remove a queued run before it starts."""
    ok = await cancel_queued_run(queue_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Queued run not found.",
        )
    return {"ok": True}
