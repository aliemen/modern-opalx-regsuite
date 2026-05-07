"""In-process per-machine run queues.

The server MUST run with a single uvicorn worker (--workers 1) for this to work
correctly, since the state lives in process memory.

Concurrency model:
- Each "machine" (identified by ``machine_id``) has at most one active run.
- ``machine_id`` is ``"local"`` for local runs, or ``connection.host`` for
  remote runs (so two regsuite users with different connections to the same
  physical host correctly serialize against each other).
- Different machines can run in parallel.
- When a machine is busy, new runs are queued (FIFO) and auto-started when the
  slot is released.

Sensitive-data rule: ``ActiveRun`` and ``QueuedRun`` may carry an in-memory
``Connection`` object containing the actual SSH host/user/work_dir, but the
public state surface (``connection_name``) is the user-chosen label only. The
queue snapshot endpoint exposes only the safe fields.
"""
from __future__ import annotations

import asyncio
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..config import Connection
    from ..data_model import RerunReference


@dataclass
class ActiveRun:
    run_id: str
    branch: str
    arch: str
    machine_id: str
    connection_name: str  # "local" or the user-chosen connection label
    triggered_by: str = ""  # username that triggered the run
    # Visibility flag carried from start_run → pipeline. Scheduler fills this
    # from the schedule's public option; HTTP trigger leaves it False.
    public: bool = False
    rerun_of: Optional["RerunReference"] = None
    custom_cmake_args: list[str] = field(default_factory=list)
    # Identity-bearing fields kept in memory only — never serialized to disk.
    connection: Optional["Connection"] = None
    target_key_path: Optional[Path] = None
    gateway_key_path: Optional[Path] = None
    # Interactive gateway credentials — held in memory only, never serialized.
    gateway_password: Optional[str] = None
    gateway_otp: Optional[str] = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "running"  # running | passed | failed | cancelled
    phase: str = "git"       # git | cmake | build | unit | regression | done
    log_path: Optional[Path] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    sse_queues: list[asyncio.Queue] = field(default_factory=list)


@dataclass
class QueuedRun:
    queue_id: str
    run_id: str
    branch: str
    arch: str
    machine_id: str
    connection_name: str
    triggered_by: str = ""  # username that triggered the run
    public: bool = False
    rerun_of: Optional["RerunReference"] = None
    custom_cmake_args: list[str] = field(default_factory=list)
    connection: Optional["Connection"] = None
    target_key_path: Optional[Path] = None
    gateway_key_path: Optional[Path] = None
    # Interactive gateway credentials — held in memory only, never serialized.
    gateway_password: Optional[str] = None
    gateway_otp: Optional[str] = None
    queued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    cfg: object = None  # SuiteConfig snapshot
    skip_unit: bool = False
    skip_regression: bool = False
    clean_build: bool = False
    log_path: Optional[Path] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)


@dataclass
class MachineQueue:
    machine_id: str
    active_run: Optional[ActiveRun] = None
    queue: deque[QueuedRun] = field(default_factory=deque)


# ── Module-level state ──────────────────────────────────────────────────────

_machines: dict[str, MachineQueue] = {}
_run_lock: Optional[asyncio.Lock] = None


def _get_lock() -> asyncio.Lock:
    global _run_lock
    if _run_lock is None:
        _run_lock = asyncio.Lock()
    return _run_lock


def _get_machine(machine_id: str) -> MachineQueue:
    if machine_id not in _machines:
        _machines[machine_id] = MachineQueue(machine_id=machine_id)
    return _machines[machine_id]


# ── Machine ID resolution ───────────────────────────────────────────────────

def resolve_machine_id(connection: Optional["Connection"]) -> str:
    """Return the queue serialization key for a run.

    For local runs (``connection is None``): ``"local"``.
    For remote runs: ``connection.host`` (just the host string — per-physical-
    machine identity, not per-user, so two regsuite users with different
    connections to the same host serialize against each other).
    """
    if connection is None:
        return "local"
    return connection.host


# ── Slot acquisition & release ──────────────────────────────────────────────

async def acquire_run_slot(
    run_id: str,
    branch: str,
    arch: str,
    machine_id: str,
    connection_name: str,
    log_path: Optional[Path],
    triggered_by: str = "",
    public: bool = False,
    rerun_of: Optional["RerunReference"] = None,
    custom_cmake_args: Optional[list[str]] = None,
    connection: Optional["Connection"] = None,
    target_key_path: Optional[Path] = None,
    gateway_key_path: Optional[Path] = None,
    gateway_password: Optional[str] = None,
    gateway_otp: Optional[str] = None,
) -> Optional[ActiveRun]:
    """Try to acquire the run slot for *machine_id*.

    Returns the new ``ActiveRun`` if the slot was free, or ``None`` if the
    machine is busy.
    """
    lock = _get_lock()
    async with lock:
        mq = _get_machine(machine_id)
        if mq.active_run is not None and mq.active_run.status == "running":
            return None
        active = ActiveRun(
            run_id=run_id,
            branch=branch,
            arch=arch,
            machine_id=machine_id,
            connection_name=connection_name,
            triggered_by=triggered_by,
            public=public,
            rerun_of=rerun_of,
            custom_cmake_args=list(custom_cmake_args or []),
            connection=connection,
            target_key_path=target_key_path,
            gateway_key_path=gateway_key_path,
            gateway_password=gateway_password,
            gateway_otp=gateway_otp,
            log_path=log_path,
        )
        mq.active_run = active
        return active


async def enqueue_run(queued: QueuedRun) -> int:
    """Append *queued* to the machine's queue.  Returns the 1-based position."""
    lock = _get_lock()
    async with lock:
        mq = _get_machine(queued.machine_id)
        mq.queue.append(queued)
        return len(mq.queue)


async def release_run_slot(
    machine_id: str,
    final_status: str,
) -> Optional[QueuedRun]:
    """Mark the active run done and pop the next queued run (if any).

    Atomically releases the slot and dequeues under the same lock so no race
    can occur between a new ``trigger_run`` and the dequeue.
    """
    lock = _get_lock()
    async with lock:
        mq = _get_machine(machine_id)
        if mq.active_run is not None:
            mq.active_run.status = final_status
            mq.active_run.phase = "done"
            for q in mq.active_run.sse_queues:
                try:
                    q.put_nowait({"type": "status", "status": final_status})
                except asyncio.QueueFull:
                    pass
            mq.active_run.sse_queues.clear()
            # Keep the object briefly for the /current endpoint.

        # Pop next queued run.
        if mq.queue:
            return mq.queue.popleft()
        return None


# ── Querying state ──────────────────────────────────────────────────────────

def get_active_run() -> Optional[ActiveRun]:
    """Backward-compat: return the first active run found (for navbar)."""
    for mq in _machines.values():
        if mq.active_run is not None and mq.active_run.status == "running":
            return mq.active_run
    return None


def get_all_active_runs() -> list[ActiveRun]:
    """Return all currently running ``ActiveRun`` objects."""
    return [
        mq.active_run
        for mq in _machines.values()
        if mq.active_run is not None and mq.active_run.status == "running"
    ]


def user_has_active_run(username: str) -> bool:
    """Return True if *username* currently owns any running run."""
    return any(r.triggered_by == username for r in get_all_active_runs())


def user_has_queued_run(username: str) -> bool:
    """Return True if *username* currently owns any queued run."""
    for mq in _machines.values():
        for qr in mq.queue:
            if qr.triggered_by == username:
                return True
    return False


def get_active_run_by_id(run_id: str) -> Optional[ActiveRun]:
    """Find an active run by *run_id* across all machines."""
    for mq in _machines.values():
        if mq.active_run is not None and mq.active_run.run_id == run_id:
            return mq.active_run
    return None


def is_run_queued(run_id: str) -> bool:
    """Check if *run_id* is in any machine's queue."""
    for mq in _machines.values():
        for qr in mq.queue:
            if qr.run_id == run_id:
                return True
    return False


def get_queue_snapshot() -> list[dict]:
    """Return a serialisable snapshot of all machines with activity."""
    result = []
    for mq in _machines.values():
        active = mq.active_run
        if active is None and not mq.queue:
            continue
        active_dict = None
        if active is not None and active.status == "running":
            active_dict = {
                "run_id": active.run_id,
                "branch": active.branch,
                "arch": active.arch,
                "status": active.status,
                "phase": active.phase,
                "started_at": active.started_at.isoformat(),
                "machine_id": active.machine_id,
                "connection_name": active.connection_name,
            }
        queue_list = [
            {
                "queue_id": qr.queue_id,
                "run_id": qr.run_id,
                "branch": qr.branch,
                "arch": qr.arch,
                "queued_at": qr.queued_at.isoformat(),
                "connection_name": qr.connection_name,
            }
            for qr in mq.queue
        ]
        result.append({
            "machine_id": mq.machine_id,
            "active_run": active_dict,
            "queue": queue_list,
        })
    return result


# ── SSE subscription ────────────────────────────────────────────────────────

def subscribe_sse(run_id: Optional[str] = None) -> asyncio.Queue:
    """Register a new SSE client queue on the active run matching *run_id*.

    If *run_id* is ``None``, falls back to the first active run (backward compat).
    """
    q: asyncio.Queue = asyncio.Queue(maxsize=10_000)
    if run_id is not None:
        run = get_active_run_by_id(run_id)
        if run is not None and run.status == "running":
            run.sse_queues.append(q)
        return q
    # Backward compat: attach to first active run.
    run = get_active_run()
    if run is not None:
        run.sse_queues.append(q)
    return q


def unsubscribe_sse(q: asyncio.Queue, run_id: Optional[str] = None) -> None:
    """Detach *q* from the run's SSE queue list."""
    if run_id is not None:
        run = get_active_run_by_id(run_id)
        if run is not None and q in run.sse_queues:
            run.sse_queues.remove(q)
        return
    # Backward compat: search all machines.
    for mq in _machines.values():
        if mq.active_run is not None and q in mq.active_run.sse_queues:
            mq.active_run.sse_queues.remove(q)
            return


# ── Cancellation ────────────────────────────────────────────────────────────

async def cancel_active_run(run_id: str) -> bool:
    """Set the cancel event on the active run matching *run_id*."""
    for mq in _machines.values():
        if (
            mq.active_run is not None
            and mq.active_run.run_id == run_id
            and mq.active_run.status == "running"
        ):
            mq.active_run.cancel_event.set()
            # Immediately push a log line so the UI shows feedback before the
            # pipeline thread notices the event and writes to the log file.
            for q in list(mq.active_run.sse_queues):
                try:
                    q.put_nowait({"type": "log", "line": "== Cancelling run… =="})
                except asyncio.QueueFull:
                    pass
            return True
    return False


async def cancel_queued_run(queue_id: str) -> bool:
    """Remove a queued run by *queue_id*.  Returns True if found and removed."""
    lock = _get_lock()
    async with lock:
        for mq in _machines.values():
            for i, qr in enumerate(mq.queue):
                if qr.queue_id == queue_id:
                    del mq.queue[i]
                    return True
        return False


# ── Cleanup ─────────────────────────────────────────────────────────────────

def clear_all_state() -> None:
    """Called at startup to reset any stale in-memory state."""
    _machines.clear()
