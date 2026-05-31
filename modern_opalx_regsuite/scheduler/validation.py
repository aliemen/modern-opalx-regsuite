"""Validation helpers shared between the schedules API and the scheduler task."""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from ..user_store import get_connection
from ..execution_profiles import resolve_run_profile

if TYPE_CHECKING:
    from ..config import Connection, SuiteConfig


class ScheduleValidationError(ValueError):
    """Raised when a schedule cannot be created/updated/fired as requested."""


def resolve_scheduled_connection(
    cfg: "SuiteConfig", owner: str, connection_name: str
) -> Optional["Connection"]:
    """Resolve the owner's connection by name.

    Returns ``None`` for local runs (``connection_name == "local"``). Raises
    :class:`ScheduleValidationError` for unknown names or for connections that
    use an interactive 2FA gateway (those are forbidden for scheduled runs).
    """
    if not connection_name or connection_name.lower() == "local":
        return None

    conn = get_connection(cfg, owner, connection_name)
    if conn is None:
        raise ScheduleValidationError(
            f"Connection '{connection_name}' not found for user '{owner}'."
        )
    if conn.gateway is not None and conn.gateway.auth_method == "interactive":
        raise ScheduleValidationError(
            "Scheduled runs cannot use connections with an interactive 2FA "
            "gateway. One-time passwords would expire before the run starts."
        )
    return conn


def resolve_scheduled_profile(
    cfg: "SuiteConfig", owner: str, profile_id: str
) -> Optional["Connection"]:
    """Resolve a scheduled run profile and reject interactive 2FA gateways."""
    try:
        resolved = resolve_run_profile(cfg, owner, profile_id)
    except KeyError as exc:
        raise ScheduleValidationError(str(exc)) from exc
    except ValueError as exc:
        raise ScheduleValidationError(str(exc)) from exc

    conn = resolved.connection
    if conn is not None and conn.gateway is not None and conn.gateway.auth_method == "interactive":
        raise ScheduleValidationError(
            "Scheduled runs cannot use profiles with an interactive 2FA "
            "gateway. One-time passwords would expire before the run starts."
        )
    return conn
