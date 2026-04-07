"""Endpoints to trigger, query, cancel, and queue pipeline runs."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..config import SuiteConfig
from ..data_model import run_dir
from ..runner import run_pipeline
from .deps import get_config, require_auth
from .state import (
    ActiveRun,
    QueuedRun,
    acquire_run_slot,
    cancel_active_run,
    cancel_queued_run,
    enqueue_run,
    get_active_run,
    get_active_run_by_id,
    get_all_active_runs,
    get_queue_snapshot,
    release_run_slot,
    resolve_machine_id,
    subscribe_sse,
)

router = APIRouter(prefix="/api/runs", tags=["runs"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class TriggerRequest(BaseModel):
    branch: str
    arch: str
    regtests_branch: Optional[str] = None
    skip_unit: bool = False
    skip_regression: bool = False


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


class QueuedRunInfo(BaseModel):
    queue_id: str
    run_id: str
    branch: str
    arch: str
    queued_at: datetime


class MachineStatus(BaseModel):
    machine_id: str
    active_run: Optional[CurrentRunStatus] = None
    queue: list[QueuedRunInfo] = []


class QueueStateResponse(BaseModel):
    machines: list[MachineStatus]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run_id_from_time() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


async def _run_pipeline_async(
    cfg: SuiteConfig,
    active: ActiveRun,
    skip_unit: bool,
    skip_regression: bool,
) -> None:
    """Execute the pipeline in a thread pool so the event loop stays responsive."""
    loop = asyncio.get_running_loop()

    def _sync():
        return run_pipeline(
            cfg,
            branch=active.branch,
            arch=active.arch,
            run_id=active.run_id,
            skip_unit=skip_unit,
            skip_regression=skip_regression,
            cancel_event=active.cancel_event,
            execution_host=active.execution_host,
            execution_user=active.execution_user,
        )

    # Broadcast log lines while the pipeline runs (log tailer task).
    tailer_task = asyncio.create_task(_log_tailer(active))
    final_status = "failed"

    try:
        meta = await loop.run_in_executor(None, _sync)
        final_status = meta.status
    except Exception as exc:
        if active.log_path:
            try:
                active.log_path.parent.mkdir(parents=True, exist_ok=True)
                with active.log_path.open("a", encoding="utf-8") as f:
                    f.write(f"\n[error] Unhandled exception: {exc}\n")
            except Exception:
                pass
    finally:
        tailer_task.cancel()
        try:
            await tailer_task
        except asyncio.CancelledError:
            pass

        # Release slot and auto-start next queued run.
        next_queued = await release_run_slot(active.machine_id, final_status)
        if next_queued is not None:
            await _start_queued_run(next_queued)


async def _start_queued_run(queued: QueuedRun) -> None:
    """Promote a queued run to active and start it."""
    next_active = await acquire_run_slot(
        run_id=queued.run_id,
        branch=queued.branch,
        arch=queued.arch,
        machine_id=queued.machine_id,
        execution_host=queued.execution_host,
        execution_user=queued.execution_user,
        log_path=queued.log_path,
    )
    if next_active is not None:
        # Carry over the cancel event from the queued run.
        next_active.cancel_event = queued.cancel_event
        asyncio.create_task(
            _run_pipeline_async(
                queued.cfg,  # type: ignore[arg-type]
                next_active,
                queued.skip_unit,
                queued.skip_regression,
            )
        )


async def _log_tailer(active: ActiveRun) -> None:
    """Poll pipeline.log for new lines and push them to SSE subscriber queues."""
    import re
    _PHASE_RE = re.compile(r"^== PHASE: (\S+?) ==")

    line_no = 0

    def _push_new_lines() -> None:
        nonlocal line_no
        if not (active.log_path and active.log_path.exists()):
            return
        lines = active.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        while line_no < len(lines):
            ln = lines[line_no]
            m = _PHASE_RE.match(ln)
            if m:
                phase_val = m.group(1).split()[0]
                active.phase = phase_val
                event: dict = {"type": "phase", "phase": phase_val, "id": line_no}
            else:
                event = {"type": "log", "line": ln, "id": line_no}
            for q in list(active.sse_queues):
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    pass
            line_no += 1

    try:
        while True:
            _push_new_lines()
            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        # Final sweep: capture any lines written after the last poll so that
        # the last test's END event reaches SSE clients before release_run_slot
        # sends the final status event.
        _push_new_lines()


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
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
):
    run_id = _run_id_from_time()
    data_root = cfg.resolved_data_root
    log_path = data_root / "runs" / body.branch / body.arch / run_id / "logs" / "pipeline.log"

    # Override regtests_branch if provided.
    if body.regtests_branch:
        cfg = cfg.model_copy(update={"regtests_branch": body.regtests_branch})

    # Resolve which machine this arch runs on.
    machine_id, remote_user = resolve_machine_id(cfg, body.arch)
    execution_host = machine_id

    active = await acquire_run_slot(
        run_id=run_id,
        branch=body.branch,
        arch=body.arch,
        machine_id=machine_id,
        execution_host=execution_host,
        execution_user=remote_user,
        log_path=log_path,
    )
    if active is not None:
        # Machine is free — start immediately.
        asyncio.create_task(
            _run_pipeline_async(cfg, active, body.skip_unit, body.skip_regression)
        )
        return TriggerResponse(run_id=run_id)
    else:
        # Machine is busy — enqueue.
        queued = QueuedRun(
            queue_id=str(uuid.uuid4()),
            run_id=run_id,
            branch=body.branch,
            arch=body.arch,
            machine_id=machine_id,
            execution_host=execution_host,
            execution_user=remote_user,
            cfg=cfg,
            skip_unit=body.skip_unit,
            skip_regression=body.skip_regression,
            log_path=log_path,
        )
        position = await enqueue_run(queued)
        return TriggerResponse(
            run_id=run_id,
            queued=True,
            queue_id=queued.queue_id,
            position=position,
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
