"""Endpoints to trigger, query, and cancel the active pipeline run."""
from __future__ import annotations

import asyncio
import json
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
    acquire_run_slot,
    get_active_run,
    release_run_slot,
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


class CurrentRunStatus(BaseModel):
    run_id: str
    branch: str
    arch: str
    status: str
    phase: str
    started_at: datetime


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
        )

    # Broadcast log lines while the pipeline runs (log tailer task).
    tailer_task = asyncio.create_task(_log_tailer(active))

    try:
        meta = await loop.run_in_executor(None, _sync)
        final_status = meta.status
    except Exception as exc:
        final_status = "failed"
        if active.log_path:
            with active.log_path.open("a", encoding="utf-8") as f:
                f.write(f"\n[error] Unhandled exception: {exc}\n")
    finally:
        tailer_task.cancel()
        try:
            await tailer_task
        except asyncio.CancelledError:
            pass

    await release_run_slot(final_status)


async def _log_tailer(active: ActiveRun) -> None:
    """Poll pipeline.log for new lines and push them to SSE subscriber queues."""
    import re
    _PHASE_RE = re.compile(r"^== PHASE: (\S+?) ==")

    line_no = 0
    try:
        while True:
            if active.log_path and active.log_path.exists():
                lines = active.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                while line_no < len(lines):
                    ln = lines[line_no]
                    m = _PHASE_RE.match(ln)
                    if m:
                        phase_val = m.group(1).split()[0]
                        active.phase = phase_val
                        event = {"type": "phase", "phase": phase_val, "id": line_no}
                    else:
                        event = {"type": "log", "line": ln, "id": line_no}
                    for q in list(active.sse_queues):
                        try:
                            q.put_nowait(event)
                        except asyncio.QueueFull:
                            pass
                    line_no += 1
            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        pass


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/current", response_model=Optional[CurrentRunStatus])
def get_current_run(_user: Annotated[str, Depends(require_auth)]):
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
    )


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

    active = await acquire_run_slot(
        run_id=run_id,
        branch=body.branch,
        arch=body.arch,
        log_path=log_path,
    )
    if active is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A run is already in progress.",
        )

    asyncio.create_task(
        _run_pipeline_async(cfg, active, body.skip_unit, body.skip_regression)
    )
    return TriggerResponse(run_id=run_id)


@router.post("/current/cancel")
def cancel_current_run(_user: Annotated[str, Depends(require_auth)]):
    run = get_active_run()
    if run is None or run.status != "running":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active run to cancel.",
        )
    run.cancel_event.set()
    return {"ok": True}
