"""FastAPI application factory."""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from ..archive_service import locked_index
from ..config import load_config
from ..data_model import branches_index_path, run_dir, runs_index_path
from ..scheduler.task import scheduler_loop
from .archive import router as archive_router
from .auth import REFRESH_COOKIE_NAME, TokenResponse, login_limiter
from .tokens import create_access_token, validate_secret_configuration, verify_refresh_token
from .branches import router as branches_router
from .catalog import router as catalog_router
from .deps import user_exists
from .integrity import router as integrity_router
from .public import router as public_router
from .results import router as results_router
from .runs import router as runs_router
from .schedules import router as schedules_router
from .coordinator import shutdown_coordinator
from .state import clear_all_state, get_active_run
from .stream import router as stream_router

log = logging.getLogger("opalx.app")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """On startup, heal any stale 'running' runs left by a previous crash,
    and launch the weekly-schedule background task."""
    scheduler_task: asyncio.Task | None = None
    scheduler_stop = asyncio.Event()
    cfg = None
    # Fail fast if the JWT signing secret is not configured. Catching the
    # RuntimeError here means the server logs a clear error instead of dying
    # halfway through booting with a partially initialised state.
    try:
        validate_secret_configuration()
    except RuntimeError as exc:
        log.error("JWT secret configuration is invalid: %s", exc)
        raise
    try:
        cfg = load_config()
        data_root = cfg.resolved_data_root
        archive_root = cfg.resolved_archive_root
        if archive_root is not None:
            _reconcile_archive_layout(data_root, archive_root)
        _heal_stale_runs(data_root)
        try:
            from ..runner.migrations import migrate_all_regression_json
            migrate_all_regression_json(data_root)
        except Exception:
            log.error(
                "regression-tests.json migration failed on startup.",
                exc_info=True,
            )
    except Exception:
        log.error(
            "Failed to load config on startup — scheduled triggers will NOT run. "
            "Check that config.toml exists and is valid.",
            exc_info=True,
        )
    if cfg is not None:
        try:
            from ..api_keys import index as api_keys_index
            n = api_keys_index.rebuild(cfg)
            log.info("api-keys: loaded %d key(s) into index.", n)
        except Exception:
            log.error("api-keys: failed to build index on startup.", exc_info=True)
    clear_all_state()
    if cfg is not None:
        scheduler_task = asyncio.create_task(
            scheduler_loop(cfg, scheduler_stop),
            name="opalx-scheduler",
        )
        log.info("Scheduler task started.")
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


def _patch_meta_archived(rdir: Path, archived: bool) -> None:
    meta_path = rdir / "run-meta.json"
    if not meta_path.is_file():
        return
    try:
        with meta_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if bool(data.get("archived", False)) == archived:
            return
        data["archived"] = archived
        with meta_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
    except Exception:
        log.exception("archive reconcile: failed to patch %s", meta_path)


def _clean_staging_dirs(root: Path) -> int:
    runs_root = root / "runs"
    if not runs_root.is_dir():
        return 0
    cleaned = 0
    for staging in sorted(runs_root.rglob("*.staging")):
        if staging.is_dir():
            try:
                shutil.rmtree(staging)
                cleaned += 1
            except Exception:
                log.exception("archive reconcile: failed to remove %s", staging)
    return cleaned


def _reconcile_archive_layout(data_root: Path, archive_root: Path) -> None:
    """Repair index/archive-layout mismatches left by interrupted moves."""
    cleaned = _clean_staging_dirs(data_root) + _clean_staging_dirs(archive_root)
    if cleaned:
        log.info("archive reconcile: removed %d stale staging directorie(s).", cleaned)

    branches_path = branches_index_path(data_root)
    if not branches_path.is_file():
        return
    try:
        with branches_path.open("r", encoding="utf-8") as f:
            branches = json.load(f)
    except Exception:
        log.exception("archive reconcile: failed to read %s", branches_path)
        return
    if not isinstance(branches, dict):
        return

    for branch, archs in branches.items():
        if not isinstance(branch, str) or not isinstance(archs, list):
            continue
        for arch in archs:
            if not isinstance(arch, str):
                continue
            idx_path = runs_index_path(data_root, branch, arch)
            if not idx_path.is_file():
                continue
            try:
                with locked_index(idx_path):
                    with idx_path.open("r", encoding="utf-8") as f:
                        entries = json.load(f)
                    if not isinstance(entries, list):
                        continue
                    changed = False
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        run_id = entry.get("run_id")
                        if not isinstance(run_id, str):
                            continue
                        data_dir = run_dir(data_root, branch, arch, run_id)
                        archive_dir = run_dir(archive_root, branch, arch, run_id)
                        on_data = data_dir.is_dir()
                        on_archive = archive_dir.is_dir()
                        indexed_archived = bool(entry.get("archived", False))

                        if on_data and on_archive:
                            if indexed_archived:
                                shutil.rmtree(data_dir)
                                _patch_meta_archived(archive_dir, True)
                            else:
                                shutil.rmtree(archive_dir)
                                _patch_meta_archived(data_dir, False)
                            continue
                        if on_data and indexed_archived:
                            entry["archived"] = False
                            _patch_meta_archived(data_dir, False)
                            changed = True
                            continue
                        if on_archive and not indexed_archived:
                            entry["archived"] = True
                            _patch_meta_archived(archive_dir, True)
                            changed = True
                    if changed:
                        with idx_path.open("w", encoding="utf-8") as f:
                            json.dump(entries, f, indent=2, default=str)
            except Exception:
                log.exception("archive reconcile: failed for %s", idx_path)


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

    # Rate-limit /api/auth/login. The limiter state lives on ``app.state`` so
    # slowapi can read it from the request scope; the exception handler maps
    # RateLimitExceeded to HTTP 429 with a ``Retry-After`` header.
    app.state.limiter = login_limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Register API routers.
    app.include_router(runs_router)
    app.include_router(schedules_router)
    app.include_router(stream_router)
    app.include_router(results_router)
    app.include_router(archive_router)
    app.include_router(branches_router)
    app.include_router(catalog_router)
    app.include_router(integrity_router)
    # Public unauthenticated surface — explicitly mounted without any auth
    # dependency. See api/public.py for the security invariants.
    app.include_router(public_router)

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

    # API-key management router (per-user). JWT-only; the keys themselves are
    # scoped to the SSH-keys endpoints above.
    from .api_keys import router as api_keys_router
    app.include_router(api_keys_router)

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
        try:
            cfg = load_config()
        except Exception:
            cfg = None
        if cfg is None or not user_exists(cfg, username):
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
