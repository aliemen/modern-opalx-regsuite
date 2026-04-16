"""Background scheduler task: fires schedules at their day/time.

Runs as a single asyncio task started from the FastAPI lifespan. On every
minute boundary it loads the current list of schedules, checks which match
``datetime.now()`` in server-local time, and calls
:func:`api.runs_core.start_run` for each match.

There is no backfill: runs missed during server downtime are simply skipped.
A ``last_triggered_at`` field on each schedule prevents double-firing within
the same minute (edge case: the loop wakes slightly early and sees the same
minute twice).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from ..config import SuiteConfig
from ..user_store import get_connection
from .matcher import matches, same_minute, seconds_to_next_minute
from .models import Schedule
from .store import list_schedules, update_schedule_runtime_state

log = logging.getLogger("opalx.scheduler")

# Simple in-process health flag: True while the scheduler loop is alive.
# Exposed via GET /api/schedules/status so operators can tell whether the
# scheduler task was ever started (e.g. to diagnose a config-load failure).
_scheduler_running: bool = False
_last_tick_at: datetime | None = None


def scheduler_is_running() -> bool:
    return _scheduler_running


def scheduler_last_tick() -> datetime | None:
    return _last_tick_at


def _now_local() -> datetime:
    """Return the current wall-clock time in server-local time (naive)."""
    return datetime.now()


def _run_id_from_time(now: datetime) -> str:
    return now.strftime("%Y%m%d-%H%M%S")


async def _fire(cfg: SuiteConfig, schedule: Schedule, now: datetime) -> None:
    """Attempt to fire one schedule and persist its runtime state."""
    # Local import so the scheduler package does not pull api/ at import time.
    from ..api.runs_core import start_run

    # Pre-check: the owner may have swapped their connection to one with an
    # interactive 2FA gateway since the schedule was created. In that case we
    # skip (never block, never queue) and log the reason.
    if schedule.connection_name and schedule.connection_name.lower() != "local":
        conn = get_connection(cfg, schedule.owner, schedule.connection_name)
        if conn is None:
            await update_schedule_runtime_state(
                cfg,
                schedule.id,
                last_triggered_at=datetime.now(timezone.utc),
                last_run_id=None,
                last_status="error",
                last_message=(
                    f"Connection '{schedule.connection_name}' no longer exists "
                    f"for owner '{schedule.owner}'."
                ),
            )
            log.warning(
                "Schedule %s (%s): connection %r missing for owner %r",
                schedule.id,
                schedule.name,
                schedule.connection_name,
                schedule.owner,
            )
            return
        if conn.gateway is not None and conn.gateway.auth_method == "interactive":
            await update_schedule_runtime_state(
                cfg,
                schedule.id,
                last_triggered_at=datetime.now(timezone.utc),
                last_run_id=None,
                last_status="skipped_2fa",
                last_message=(
                    "Connection now uses an interactive 2FA gateway; "
                    "scheduled runs cannot supply OTPs."
                ),
            )
            log.warning(
                "Schedule %s (%s): connection %r now uses 2FA; skipping",
                schedule.id,
                schedule.name,
                schedule.connection_name,
            )
            return

    run_id = _run_id_from_time(now)
    log.info(
        "Schedule %s (%s): firing now=%s branch=%s arch=%s connection=%s clean_build=%s",
        schedule.id,
        schedule.name,
        now.isoformat(timespec="seconds"),
        schedule.branch,
        schedule.arch,
        schedule.connection_name,
        schedule.clean_build,
    )
    try:
        result = await start_run(
            cfg,
            run_id=run_id,
            triggered_by=schedule.owner,
            owner_for_connection=schedule.owner,
            branch=schedule.branch,
            arch=schedule.arch,
            regtests_branch=schedule.regtests_branch,
            skip_unit=schedule.skip_unit,
            skip_regression=schedule.skip_regression,
            clean_build=schedule.clean_build,
            connection_name=schedule.connection_name,
            public=schedule.public,
        )
    except Exception as exc:  # noqa: BLE001 — never let one schedule kill the loop
        log.exception("Schedule %s (%s): start_run raised", schedule.id, schedule.name)
        await update_schedule_runtime_state(
            cfg,
            schedule.id,
            last_triggered_at=datetime.now(timezone.utc),
            last_run_id=None,
            last_status="error",
            last_message=f"{type(exc).__name__}: {exc}",
        )
        return

    await update_schedule_runtime_state(
        cfg,
        schedule.id,
        last_triggered_at=datetime.now(timezone.utc),
        last_run_id=result.run_id,
        last_status=result.outcome,
        last_message=result.detail,
    )
    log.info(
        "Schedule %s (%s): fired → %s (run_id=%s)",
        schedule.id,
        schedule.name,
        result.outcome,
        result.run_id,
    )


async def _tick(cfg: SuiteConfig, now: datetime) -> None:
    """Run one scheduler iteration: find all matching schedules and fire them."""
    global _last_tick_at
    _last_tick_at = now
    try:
        schedules = await list_schedules(cfg)
    except Exception:
        log.exception("Scheduler tick: failed to load schedules")
        return
    enabled = [s for s in schedules if s.enabled]
    log.debug(
        "Scheduler tick at %s: %d schedule(s) loaded, %d enabled",
        now.isoformat(timespec="seconds"),
        len(schedules),
        len(enabled),
    )
    for s in enabled:
        if not matches(s.spec, now):
            continue
        # Idempotency: if we already fired for this minute (e.g. loop woke
        # slightly early and re-entered), skip the re-fire.
        if s.last_triggered_at is not None:
            # last_triggered_at is stored as UTC; convert both sides to local
            # naive for the minute compare. The worst-case here is that we
            # skip a legitimate second fire within the same minute, which is
            # exactly the semantics we want anyway.
            try:
                last_local = s.last_triggered_at.astimezone().replace(tzinfo=None)
            except Exception:
                last_local = None
            if last_local is not None and same_minute(last_local, now):
                continue
        await _fire(cfg, s, now)


async def scheduler_loop(cfg: SuiteConfig, stop: asyncio.Event) -> None:
    """Main scheduler loop. Aligns its wake-ups to wall-clock minute boundaries."""
    global _scheduler_running
    _scheduler_running = True
    tz_name = datetime.now().astimezone().tzname() or "local"
    log.info(
        "Scheduler loop starting (server time=%s tz=%s)",
        _now_local().isoformat(timespec="seconds"),
        tz_name,
    )
    try:
        # Run one tick right away so a freshly enabled schedule fires at its
        # next minute boundary without a 60s delay on startup.
        try:
            await _tick(cfg, _now_local())
        except Exception:
            log.exception("Scheduler: initial tick failed")

        while not stop.is_set():
            delay = seconds_to_next_minute(_now_local())
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
                # stop was set during the wait — exit cleanly
                break
            except asyncio.TimeoutError:
                pass
            if stop.is_set():
                break
            try:
                await _tick(cfg, _now_local())
            except Exception:
                log.exception("Scheduler: tick failed")
    finally:
        # Always flip to False on exit, including cancellation or unexpected
        # exceptions — otherwise /api/schedules/status would wrongly report
        # the scheduler as "running" after the task has died.
        _scheduler_running = False
        log.info("Scheduler loop stopped")
