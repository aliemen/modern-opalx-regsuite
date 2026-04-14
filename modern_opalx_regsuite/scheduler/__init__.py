"""Weekly recurring schedules for regression-test runs.

A schedule stores:
- day-of-week + time-of-day (server-local)
- run parameters (branch, arch, regtests_branch, connection_name, skips)
- the owner's username (used to resolve the connection / SSH keys at fire time)

Schedules are stored in a single shared file under ``<data_root>/schedules.json``
and are visible to every authenticated user. Only the owner can edit or toggle
a schedule, but any authenticated user may delete any schedule so stale entries
from inactive users don't block the pipeline.
"""
from .models import DayOfWeek, Schedule, ScheduleSpec
from .store import (
    create_schedule,
    delete_schedule,
    get_schedule,
    list_schedules,
    update_schedule,
    update_schedule_runtime_state,
)

__all__ = [
    "DayOfWeek",
    "Schedule",
    "ScheduleSpec",
    "create_schedule",
    "delete_schedule",
    "get_schedule",
    "list_schedules",
    "update_schedule",
    "update_schedule_runtime_state",
]
