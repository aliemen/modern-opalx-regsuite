"""In-process singleton tracking the one active pipeline run.

The server MUST run with a single uvicorn worker (--workers 1) for this to work
correctly, since the state lives in process memory.
"""
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class ActiveRun:
    run_id: str
    branch: str
    arch: str
    started_at: datetime
    status: str = "running"  # running | passed | failed | cancelled
    phase: str = "git"       # git | cmake | build | unit | regression | done
    log_path: Optional[Path] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    sse_queues: list[asyncio.Queue] = field(default_factory=list)


# Module-level state.
_active_run: Optional[ActiveRun] = None
_run_lock: Optional[asyncio.Lock] = None


def _get_lock() -> asyncio.Lock:
    global _run_lock
    if _run_lock is None:
        _run_lock = asyncio.Lock()
    return _run_lock


def get_active_run() -> Optional[ActiveRun]:
    return _active_run


async def acquire_run_slot(
    run_id: str,
    branch: str,
    arch: str,
    log_path: Path,
) -> Optional[ActiveRun]:
    """Try to acquire the run slot. Returns None if another run is active."""
    lock = _get_lock()
    async with lock:
        global _active_run
        if _active_run is not None and _active_run.status == "running":
            return None
        _active_run = ActiveRun(
            run_id=run_id,
            branch=branch,
            arch=arch,
            started_at=datetime.now(timezone.utc),
            log_path=log_path,
        )
        return _active_run


async def release_run_slot(final_status: str) -> None:
    """Mark the run done and release the slot (keeps the object for one last status read)."""
    global _active_run
    if _active_run is not None:
        _active_run.status = final_status
        _active_run.phase = "done"
        # Notify all SSE subscribers of the final status.
        for q in _active_run.sse_queues:
            await q.put({"type": "status", "status": final_status})
        _active_run.sse_queues.clear()
        # We intentionally leave _active_run set so the /current endpoint can
        # return the final state briefly; it is cleared on the next trigger.


def clear_active_run() -> None:
    """Called at startup to reset any stale running state."""
    global _active_run
    _active_run = None


def subscribe_sse() -> asyncio.Queue:
    """Register a new SSE client queue on the active run, or return a closed one."""
    q: asyncio.Queue = asyncio.Queue(maxsize=10_000)
    if _active_run is not None and _active_run.status == "running":
        _active_run.sse_queues.append(q)
    return q


def unsubscribe_sse(q: asyncio.Queue) -> None:
    if _active_run is not None and q in _active_run.sse_queues:
        _active_run.sse_queues.remove(q)
