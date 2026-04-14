"""Time-of-day / day-of-week matching helpers for the scheduler loop."""
from __future__ import annotations

from datetime import datetime, timedelta

from .models import DAY_INDEX, DAYS_ORDER, ScheduleSpec


def matches(spec: ScheduleSpec, now: datetime) -> bool:
    """Return True if ``now`` falls on one of the spec's days at the spec's HH:MM.

    Matching is minute-precise: we compare the current weekday and HH:MM to the
    schedule. Seconds are ignored. ``now`` is expected in server-local time.
    """
    weekday = DAYS_ORDER[now.weekday()]  # MON..SUN
    if weekday not in spec.days:
        return False
    hh, mm = spec.time.split(":")
    return now.hour == int(hh) and now.minute == int(mm)


def seconds_to_next_minute(now: datetime) -> float:
    """Return seconds until the start of the next wall-clock minute.

    Adds a small positive offset so we wake up a hair *after* the minute
    boundary, ensuring ``now.minute`` reflects the new minute on our tick.
    """
    next_minute = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
    delta = (next_minute - now).total_seconds()
    return max(0.1, delta + 0.05)


def same_minute(a: datetime, b: datetime) -> bool:
    """Return True if two datetimes fall in the same calendar minute."""
    return (
        a.year == b.year
        and a.month == b.month
        and a.day == b.day
        and a.hour == b.hour
        and a.minute == b.minute
    )


def next_fire_at(spec: ScheduleSpec, now: datetime) -> datetime:
    """Return the next datetime (>= now, strictly future if now matches) at
    which this spec will fire. Used purely for UI display / debugging."""
    hh, mm = (int(x) for x in spec.time.split(":"))
    # Search the next 8 days so we always find a hit (spec has >= 1 day).
    for offset in range(0, 8):
        candidate = (now + timedelta(days=offset)).replace(
            hour=hh, minute=mm, second=0, microsecond=0
        )
        weekday = DAYS_ORDER[candidate.weekday()]
        if weekday not in spec.days:
            continue
        if candidate <= now:
            continue
        return candidate
    # Unreachable given the 1..7-day cycle, but satisfy type-checkers.
    return now
