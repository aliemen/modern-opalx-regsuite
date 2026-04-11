"""Per-user named SSH connection management.

Each authenticated regsuite user owns a set of named connections stored in
``<users_root>/<username>/connections.json``. The :class:`Connection` schema
captures everything needed to reach a remote target, including optional
``ProxyJump`` gateway and an :class:`EnvActivation` (modules or prologue).

Endpoints under ``/api/settings/connections``:

* ``GET /``                — list this user's connections
* ``POST /``               — create a connection
* ``GET /{name}``          — fetch one
* ``PUT /{name}``          — update one (full replace)
* ``DELETE /{name}``       — delete one
* ``POST /{name}/test``    — open the SSH chain (gateway included) and run
                              ``whoami`` as a smoke test

Validation: ``key_name`` (and ``gateway.key_name`` if present) must reference
an existing key in the user's ``ssh-keys/`` dir on create/update. CRUD is
serialized per-user via ``user_store.connections_lock``.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..config import Connection, SuiteConfig
from ..user_store import (
    connections_lock,
    delete_connection as _delete_connection,
    get_connection,
    load_connections,
    resolve_connection_key_paths,
    upsert_connection,
    user_keys_dir,
)
from .deps import get_config, require_user_paths

router = APIRouter(prefix="/api/settings/connections", tags=["settings"])


# ── Helpers ──────────────────────────────────────────────────────────────────

def _validate_keys_exist(cfg: SuiteConfig, username: str, conn: Connection) -> None:
    keys = user_keys_dir(cfg, username)
    target_key = keys / f"{conn.key_name}.pem"
    missing: list[str] = []
    if not target_key.is_file():
        missing.append(conn.key_name)
    if conn.gateway is not None and conn.gateway.auth_method != "interactive":
        gw_key = keys / f"{conn.gateway.key_name}.pem"
        if not gw_key.is_file() and conn.gateway.key_name not in missing:
            missing.append(conn.gateway.key_name)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Referenced SSH key(s) do not exist for this user.",
                "missing_keys": missing,
            },
        )


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=list[Connection])
async def list_user_connections(
    user_paths: Annotated[tuple[str, Path], Depends(require_user_paths)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
) -> list[Connection]:
    username, _ = user_paths
    return load_connections(cfg, username)


@router.post("", status_code=201, response_model=Connection)
async def create_user_connection(
    body: Connection,
    user_paths: Annotated[tuple[str, Path], Depends(require_user_paths)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
) -> Connection:
    username, _ = user_paths
    _validate_keys_exist(cfg, username, body)
    async with connections_lock(username):
        existing = get_connection(cfg, username, body.name)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Connection '{body.name}' already exists.",
            )
        upsert_connection(cfg, username, body)
    return body


@router.get("/{name}", response_model=Connection)
async def get_user_connection(
    name: str,
    user_paths: Annotated[tuple[str, Path], Depends(require_user_paths)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
) -> Connection:
    username, _ = user_paths
    conn = get_connection(cfg, username, name)
    if conn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection '{name}' not found.",
        )
    return conn


@router.put("/{name}", response_model=Connection)
async def update_user_connection(
    name: str,
    body: Connection,
    user_paths: Annotated[tuple[str, Path], Depends(require_user_paths)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
) -> Connection:
    if body.name != name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path name must match body.name (renames are not supported).",
        )
    username, _ = user_paths
    _validate_keys_exist(cfg, username, body)
    async with connections_lock(username):
        existing = get_connection(cfg, username, name)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Connection '{name}' not found.",
            )
        upsert_connection(cfg, username, body)
    return body


@router.delete("/{name}", status_code=204)
async def delete_user_connection(
    name: str,
    user_paths: Annotated[tuple[str, Path], Depends(require_user_paths)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
) -> None:
    username, _ = user_paths
    async with connections_lock(username):
        if not _delete_connection(cfg, username, name):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Connection '{name}' not found.",
            )


# ── Test endpoint ────────────────────────────────────────────────────────────

class ConnectionTestResult(BaseModel):
    ok: bool
    whoami: str | None = None
    error: str | None = None


class ConnectionTestRequest(BaseModel):
    """Optional request body for testing interactive gateway connections."""
    gateway_password: str | None = None
    gateway_otp: str | None = None


@router.post("/{name}/test", response_model=ConnectionTestResult)
async def test_user_connection(
    name: str,
    user_paths: Annotated[tuple[str, Path], Depends(require_user_paths)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
    body: ConnectionTestRequest | None = None,
) -> ConnectionTestResult:
    """Open the SSH chain (gateway included) and run ``whoami``.

    The ``whoami`` output is returned to the caller — it confirms that the
    user landed on the *target* host, not the gateway. This endpoint is
    explicit about leaking the SSH username to the API caller (the user is
    looking at their own connection).
    """
    username, _ = user_paths
    conn = get_connection(cfg, username, name)
    if conn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection '{name}' not found.",
        )

    target_key, gateway_key = resolve_connection_key_paths(cfg, username, conn)
    if not target_key.is_file():
        return ConnectionTestResult(
            ok=False, error=f"target key '{conn.key_name}' is missing"
        )
    if (
        conn.gateway is not None
        and conn.gateway.auth_method != "interactive"
        and (gateway_key is None or not gateway_key.is_file())
    ):
        return ConnectionTestResult(
            ok=False, error=f"gateway key '{conn.gateway.key_name}' is missing"
        )
    # Validate interactive gateway credentials are provided for testing.
    if (
        conn.gateway is not None
        and conn.gateway.auth_method == "interactive"
        and (not (body and body.gateway_password) or not (body and body.gateway_otp))
    ):
        return ConnectionTestResult(
            ok=False,
            error=(
                "Interactive gateway requires 'gateway_password' and "
                "'gateway_otp' in the request body for testing."
            ),
        )

    # Run the blocking SSH call in a worker thread so we don't stall the loop.
    def _do_test() -> ConnectionTestResult:
        import io
        import logging
        from ..remote import RemoteExecutor

        # Capture paramiko DEBUG output for this test so we can surface
        # the full auth negotiation trace in the error message.
        log_buf = io.StringIO()
        handler = logging.StreamHandler(log_buf)
        handler.setLevel(logging.DEBUG)
        paramiko_logger = logging.getLogger("paramiko")
        old_level = paramiko_logger.level
        paramiko_logger.setLevel(logging.DEBUG)
        paramiko_logger.addHandler(handler)

        executor = RemoteExecutor(
            host=conn.host,
            user=conn.user,
            key_path=target_key,
            port=conn.port,
            connection_name=conn.name,
            gateway=conn.gateway,
            gateway_key_path=gateway_key,
            env=None,  # transport-only check; do not apply env activation
            keepalive_interval=conn.keepalive_interval,
            gateway_password=body.gateway_password if body else None,
            gateway_otp=body.gateway_otp if body else None,
        )
        try:
            who = executor.whoami()
            return ConnectionTestResult(ok=True, whoami=who)
        except Exception as exc:  # noqa: BLE001 — surface to the user
            debug_log = log_buf.getvalue()
            # Extract the most useful lines (auth-related) to keep the
            # error message short enough to display in the UI.
            useful = [
                l for l in debug_log.splitlines()
                if any(k in l.lower() for k in (
                    "auth", "userauth", "banner", "key", "host", "connect",
                    "transport", "error", "exception", "failed", "reject",
                ))
            ]
            detail = "\n".join(useful[-30:]) if useful else debug_log[-2000:]
            return ConnectionTestResult(
                ok=False,
                error=f"{type(exc).__name__}: {exc}\n\nParamiko trace:\n{detail}",
            )
        finally:
            executor.close()
            paramiko_logger.removeHandler(handler)
            paramiko_logger.setLevel(old_level)

    return await asyncio.to_thread(_do_test)
