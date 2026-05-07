"""Internal helper that starts a pipeline run.

This module exists so the HTTP trigger endpoint (``api/runs.py``) and the
background scheduler (``scheduler/task.py``) share a single code path for
resolving the connection, acquiring a machine slot, and handing control to the
run coordinator. The HTTP endpoint does input validation / credential handling;
this helper does the machine-level orchestration and returns a rich result so
the caller can shape its response appropriately.

The result uses two soft outcomes that the HTTP layer maps to HTTP status
codes: ``busy_interactive`` (409) and ``missing_key`` (409 or 404). The
scheduler maps both to "skipped" plus a message.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..config import Connection, SuiteConfig
from ..data_model import RerunReference
from ..user_store import get_connection, resolve_connection_key_paths
from .coordinator import get_coordinator
from .state import (
    QueuedRun,
    acquire_run_slot,
    enqueue_run,
    resolve_machine_id,
)


StartOutcome = str  # "started" | "queued" | "busy_interactive" | "missing_connection" | "missing_key"


def _describe_key_problem(
    key_path: Optional[Path],
    *,
    key_name: str,
    role: str,
) -> Optional[str]:
    """Return a precise, user-facing description of why *key_path* is unusable,
    or ``None`` if the key is present and readable.

    ``role`` is ``"target"`` or ``"gateway"``; it is included verbatim so the
    caller does not have to massage the sentence downstream. The distinction
    between "never resolved", "not on disk", "not readable" and "mode too
    permissive" matters for operators: each implies a different remediation
    (configure the connection, re-upload the key, fix permissions, re-chmod).
    """
    if key_path is None:
        return (
            f"{role.capitalize()} SSH key '{key_name}' could not be resolved "
            "to a filesystem path (is the connection fully configured?)."
        )
    if not key_path.exists():
        return (
            f"{role.capitalize()} SSH key '{key_name}' is not on disk at "
            f"{key_path} - it may have been deleted or never uploaded."
        )
    if not key_path.is_file():
        return (
            f"{role.capitalize()} SSH key '{key_name}' at {key_path} is not "
            "a regular file."
        )
    if not os.access(key_path, os.R_OK):
        return (
            f"{role.capitalize()} SSH key '{key_name}' at {key_path} is not "
            "readable by the server process; check ownership and permissions."
        )
    try:
        mode = key_path.stat().st_mode & 0o777
    except OSError as exc:
        return (
            f"{role.capitalize()} SSH key '{key_name}' at {key_path} could "
            f"not be stat'd ({exc.strerror or exc})."
        )
    if mode & 0o077:
        return (
            f"{role.capitalize()} SSH key '{key_name}' at {key_path} has "
            f"permissions {oct(mode)}; SSH refuses keys readable by others. "
            "Run 'chmod 600' on the key."
        )
    return None


@dataclass
class StartRunResult:
    outcome: StartOutcome
    run_id: str
    queue_id: Optional[str] = None
    position: Optional[int] = None
    detail: Optional[str] = None
    # The resolved connection name ("local" when no remote) — useful for logging.
    connection_name: str = "local"


async def start_run(
    cfg: SuiteConfig,
    *,
    run_id: str,
    triggered_by: str,
    owner_for_connection: str,
    branch: str,
    arch: str,
    regtests_branch: Optional[str],
    skip_unit: bool,
    skip_regression: bool,
    connection_name: Optional[str],
    public: bool = False,
    clean_build: bool = False,
    custom_cmake_args: Optional[list[str]] = None,
    rerun_of: Optional[RerunReference] = None,
    gateway_password: Optional[str] = None,
    gateway_otp: Optional[str] = None,
) -> StartRunResult:
    """Acquire a machine slot and start (or enqueue) a pipeline run.

    Parameters
    ----------
    cfg
        Suite config.
    run_id
        The caller-generated run identifier (``YYYYMMDD-HHMMSS`` format).
    triggered_by
        Username stamped on the run record and log header. For scheduler
        invocations, this is the schedule owner.
    owner_for_connection
        Username whose per-user connection store holds ``connection_name``.
        Normally the same as ``triggered_by``; separated only because both
        the HTTP endpoint and the scheduler use the "owner's connection" rule.
    branch, arch
        Run parameters.
    regtests_branch
        Optional override for the regression-tests repo branch.
    skip_unit, skip_regression
        Phase skips.
    connection_name
        ``None`` or ``"local"`` → local run. Otherwise → resolve from
        ``owner_for_connection``'s store.
    gateway_password, gateway_otp
        Only used for interactive 2FA gateways (HTTP trigger path).
    """
    data_root = cfg.resolved_data_root
    log_path = data_root / "runs" / branch / arch / run_id / "logs" / "pipeline.log"
    effective_custom_cmake_args = [
        arg.strip()
        for arg in (custom_cmake_args or [])
        if arg.strip() and not arg.strip().startswith("#")
    ]
    effective_clean_build = clean_build or bool(effective_custom_cmake_args)

    # Override regtests_branch if provided (model_copy keeps caller's cfg intact).
    effective_cfg = cfg
    if regtests_branch:
        effective_cfg = cfg.model_copy(update={"regtests_branch": regtests_branch})

    connection: Optional[Connection] = None
    target_key_path: Optional[Path] = None
    gateway_key_path: Optional[Path] = None

    if connection_name and connection_name.lower() != "local":
        connection = get_connection(effective_cfg, owner_for_connection, connection_name)
        if connection is None:
            return StartRunResult(
                outcome="missing_connection",
                run_id=run_id,
                detail=(
                    f"Connection '{connection_name}' not found for user "
                    f"'{owner_for_connection}'."
                ),
                connection_name=connection_name,
            )
        target_key_path, gateway_key_path = resolve_connection_key_paths(
            effective_cfg, owner_for_connection, connection
        )
        target_problem = _describe_key_problem(
            target_key_path,
            key_name=connection.key_name,
            role="target",
        )
        if target_problem is not None:
            return StartRunResult(
                outcome="missing_key",
                run_id=run_id,
                detail=target_problem,
                connection_name=connection.name,
            )
        if (
            connection.gateway is not None
            and connection.gateway.auth_method != "interactive"
        ):
            gateway_problem = _describe_key_problem(
                gateway_key_path,
                key_name=connection.gateway.key_name,
                role="gateway",
            )
            if gateway_problem is not None:
                return StartRunResult(
                    outcome="missing_key",
                    run_id=run_id,
                    detail=gateway_problem,
                    connection_name=connection.name,
                )

    machine_id = resolve_machine_id(connection)
    resolved_conn_name = connection.name if connection is not None else "local"

    active = await acquire_run_slot(
        run_id=run_id,
        branch=branch,
        arch=arch,
        machine_id=machine_id,
        connection_name=resolved_conn_name,
        log_path=log_path,
        triggered_by=triggered_by,
        public=public,
        rerun_of=rerun_of,
        custom_cmake_args=effective_custom_cmake_args,
        connection=connection,
        target_key_path=target_key_path,
        gateway_key_path=gateway_key_path,
        gateway_password=gateway_password,
        gateway_otp=gateway_otp,
    )
    if active is not None:
        coordinator = get_coordinator()
        asyncio.create_task(
            coordinator.run_pipeline_async(
                effective_cfg,
                active,
                skip_unit,
                skip_regression,
                effective_clean_build,
                effective_custom_cmake_args,
            )
        )
        return StartRunResult(
            outcome="started",
            run_id=run_id,
            connection_name=resolved_conn_name,
        )

    # Machine busy. Interactive 2FA connections cannot queue (OTP expiry).
    if (
        connection is not None
        and connection.gateway is not None
        and connection.gateway.auth_method == "interactive"
    ):
        return StartRunResult(
            outcome="busy_interactive",
            run_id=run_id,
            detail=(
                "Machine busy and connection uses interactive 2FA gateway; "
                "queueing would let the OTP expire before run starts."
            ),
            connection_name=resolved_conn_name,
        )

    queued = QueuedRun(
        queue_id=str(uuid.uuid4()),
        run_id=run_id,
        branch=branch,
        arch=arch,
        machine_id=machine_id,
        connection_name=resolved_conn_name,
        triggered_by=triggered_by,
        public=public,
        rerun_of=rerun_of,
        custom_cmake_args=effective_custom_cmake_args,
        connection=connection,
        target_key_path=target_key_path,
        gateway_key_path=gateway_key_path,
        gateway_password=gateway_password,
        gateway_otp=gateway_otp,
        cfg=effective_cfg,
        skip_unit=skip_unit,
        skip_regression=skip_regression,
        clean_build=effective_clean_build,
        log_path=log_path,
    )
    position = await enqueue_run(queued)
    return StartRunResult(
        outcome="queued",
        run_id=run_id,
        queue_id=queued.queue_id,
        position=position,
        connection_name=resolved_conn_name,
    )
