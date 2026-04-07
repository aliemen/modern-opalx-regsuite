"""SSE log streaming endpoints for active runs."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from .tokens import verify_access_token
from .state import (
    get_active_run,
    get_active_run_by_id,
    is_run_queued,
    subscribe_sse,
    unsubscribe_sse,
)

router = APIRouter(prefix="/api/runs", tags=["stream"])

# Regex that matches the structured phase markers emitted by runner._phase().
_PHASE_RE = re.compile(r"^== PHASE: (\S+?) ==")


def _parse_phase(line: str) -> str | None:
    m = _PHASE_RE.match(line)
    if m:
        val = m.group(1)
        # "done status=passed" → "done"
        return val.split()[0]
    return None


def _validate_token(request: Request, token: str | None) -> bool:
    """Validate bearer token from query param or Authorization header."""
    bearer = request.headers.get("Authorization", "")
    auth_token = token or (
        bearer.removeprefix("Bearer ").strip()
        if bearer.startswith("Bearer ")
        else None
    )
    return bool(auth_token and verify_access_token(auth_token) is not None)


def _stream_run(run, run_id: str | None, request: Request):
    """Build an SSE StreamingResponse for a specific active run."""
    if run is None or run.log_path is None:
        # Check if queued.
        if run_id and is_run_queued(run_id):
            async def _queued():
                yield 'data: {"type": "status", "status": "queued"}\n\n'
            return StreamingResponse(_queued(), media_type="text/event-stream")
        async def _empty():
            yield 'data: {"type": "status", "status": "none"}\n\n'
        return StreamingResponse(_empty(), media_type="text/event-stream")

    last_id_header = request.headers.get("Last-Event-ID", "")
    try:
        start_line = int(last_id_header) + 1
    except (ValueError, TypeError):
        start_line = 0

    effective_run_id = run_id or run.run_id
    q = subscribe_sse(effective_run_id)

    async def _event_gen() -> AsyncIterator[str]:
        # First, replay any lines that exist before the SSE connection.
        log_path = run.log_path
        assert log_path is not None
        if log_path.exists():
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            for i, ln in enumerate(lines):
                if i < start_line:
                    continue
                phase = _parse_phase(ln)
                if phase:
                    payload = json.dumps({"type": "phase", "phase": phase})
                else:
                    payload = json.dumps({"type": "log", "line": ln})
                yield f"id: {i}\ndata: {payload}\n\n"

        # If the run already finished, send the final status and close.
        if run.status != "running":
            yield f"data: {json.dumps({'type': 'status', 'status': run.status})}\n\n"
            unsubscribe_sse(q, run_id=effective_run_id)
            return

        # Then stream live events from the queue.
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    # Send a heartbeat comment to keep the connection alive.
                    yield ": heartbeat\n\n"
                    continue

                event_id = event.get("id", "")
                payload = json.dumps({k: v for k, v in event.items() if k != "id"})
                if event_id != "":
                    yield f"id: {event_id}\ndata: {payload}\n\n"
                else:
                    yield f"data: {payload}\n\n"

                if event.get("type") == "status":
                    break
        finally:
            unsubscribe_sse(q, run_id=effective_run_id)

    return StreamingResponse(
        _event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx hint to disable buffering
        },
    )


@router.get("/current/stream")
async def stream_current_run(
    request: Request,
    token: str | None = Query(None, description="Bearer token (for EventSource clients)"),
):
    """SSE endpoint. Streams log lines for the first active run (backward compat)."""
    if not _validate_token(request, token):
        from fastapi.responses import Response
        return Response("Unauthorized", status_code=401)

    run = get_active_run()
    return _stream_run(run, None, request)


@router.get("/{run_id}/stream")
async def stream_run_by_id(
    run_id: str,
    request: Request,
    token: str | None = Query(None, description="Bearer token (for EventSource clients)"),
):
    """SSE endpoint. Streams log lines for a specific active run."""
    if not _validate_token(request, token):
        from fastapi.responses import Response
        return Response("Unauthorized", status_code=401)

    run = get_active_run_by_id(run_id)
    return _stream_run(run, run_id, request)
