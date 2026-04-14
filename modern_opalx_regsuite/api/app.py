"""FastAPI application factory."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import load_config
from ..data_model import runs_index_path
from ..scheduler.task import scheduler_loop
from .archive import router as archive_router
from .auth import REFRESH_COOKIE_NAME, TokenResponse
from .tokens import create_access_token, verify_refresh_token
from .branches import router as branches_router
from .results import router as results_router
from .runs import router as runs_router
from .schedules import router as schedules_router
from .coordinator import shutdown_coordinator
from .state import clear_all_state, get_active_run
from .stream import router as stream_router


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """On startup, heal any stale 'running' runs left by a previous crash,
    and launch the weekly-schedule background task."""
    scheduler_task: asyncio.Task | None = None
    scheduler_stop = asyncio.Event()
    cfg = None
    try:
        cfg = load_config()
        data_root = cfg.resolved_data_root
        _heal_stale_runs(data_root)
    except Exception:
        pass  # Config might not be initialised yet; non-fatal.
    clear_all_state()
    if cfg is not None:
        scheduler_task = asyncio.create_task(
            scheduler_loop(cfg, scheduler_stop),
            name="opalx-scheduler",
        )
    try:
        yield
    finally:
        # Stop the scheduler loop cleanly, then shut down the pipeline thread pool.
        scheduler_stop.set()
        if scheduler_task is not None:
            try:
                await asyncio.wait_for(scheduler_task, timeout=5.0)
            except (asyncio.TimeoutError, Exception):
                scheduler_task.cancel()
        shutdown_coordinator()


def _heal_stale_runs(data_root: Path) -> None:
    """Find any run-meta.json with status='running' and mark it 'failed'.

    Also patches the corresponding runs_index.json so the dashboard doesn't
    show a stale 'running' badge after a server crash.

    Invariant: this function only writes ``status`` and ``finished_at``. It
    must NOT touch the ``archived`` field — a crash recovery should preserve
    whatever archive state the run had before the crash.
    """
    runs_root = data_root / "runs"
    if not runs_root.is_dir():
        return
    for meta_path in runs_root.glob("*/*/*/run-meta.json"):
        try:
            with meta_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("status") == "running":
                import datetime as _dt
                finished = _dt.datetime.now(_dt.timezone.utc).isoformat()
                data["status"] = "failed"
                data.setdefault("finished_at", finished)
                with meta_path.open("w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, default=str)
                # Patch the runs index entry to match.
                _heal_index_entry(data_root, data)
        except Exception:
            pass


def _heal_index_entry(data_root: Path, meta: dict) -> None:
    """Update a single entry in runs_index.json to reflect healed status."""
    branch = meta.get("branch", "")
    arch = meta.get("arch", "")
    run_id = meta.get("run_id", "")
    if not (branch and arch and run_id):
        return
    idx_path = runs_index_path(data_root, branch, arch)
    if not idx_path.is_file():
        return
    try:
        with idx_path.open("r", encoding="utf-8") as f:
            entries = json.load(f)
        for entry in entries:
            if entry.get("run_id") == run_id:
                entry["status"] = "failed"
                entry.setdefault("finished_at", meta.get("finished_at"))
                break
        with idx_path.open("w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, default=str)
    except Exception:
        pass


def create_app() -> FastAPI:
    app = FastAPI(
        title="OPALX Regression Suite",
        description="Web interface for running and browsing OPALX regression tests.",
        version="1.0.0",
        lifespan=_lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    # Allow all origins in development; in production nginx handles CORS.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Total-Count"],
    )

    # Register API routers.
    app.include_router(runs_router)
    app.include_router(schedules_router)
    app.include_router(stream_router)
    app.include_router(results_router)
    app.include_router(archive_router)
    app.include_router(branches_router)

    from .stats import router as stats_router
    app.include_router(stats_router)

    from .stats_developer import router as stats_developer_router
    app.include_router(stats_developer_router)

    # Auth router — login, logout endpoints.
    from .auth import router as auth_router
    app.include_router(auth_router)

    # SSH key management router (per-user).
    from .keys import router as keys_router
    app.include_router(keys_router)

    # Per-user named SSH connections router.
    from .connections import router as connections_router
    app.include_router(connections_router)

    # Inline /api/auth/refresh-cookie endpoint (needs raw Request to read cookies).
    @app.post("/api/auth/refresh-cookie", response_model=TokenResponse)
    async def refresh_cookie(request: Request, response: Response):
        token = request.cookies.get(REFRESH_COOKIE_NAME)
        if token is None:
            return JSONResponse(
                {"detail": "No refresh token cookie."},
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        username = verify_refresh_token(token)
        if username is None:
            return JSONResponse(
                {"detail": "Invalid or expired refresh token."},
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        access_token = create_access_token(username)
        return TokenResponse(access_token=access_token)

    # Serve the data directory so the frontend can access logs and plots.
    try:
        cfg = load_config()
        data_root = cfg.resolved_data_root
        if data_root.is_dir():
            app.mount("/data", StaticFiles(directory=str(data_root)), name="data")
    except Exception:
        pass  # data_root might not exist at app creation time.

    # Serve the built React frontend.  The frontend's index.html handles all
    # client-side routing via the catch-all below.
    static_dir = Path(__file__).resolve().parent.parent / "static"
    if static_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            index = static_dir / "index.html"
            if index.is_file():
                from fastapi.responses import FileResponse
                return FileResponse(str(index))
            return JSONResponse(
                {"detail": "Frontend not built. Run 'make build-frontend'."},
                status_code=404,
            )

    return app
