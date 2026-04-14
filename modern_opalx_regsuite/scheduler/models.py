"""Pydantic models for weekly recurring schedules."""
from __future__ import annotations

import re
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


DayOfWeek = Literal["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

DAYS_ORDER: tuple[DayOfWeek, ...] = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")

# Python's datetime.weekday(): Monday=0 ... Sunday=6.
DAY_INDEX: dict[DayOfWeek, int] = {d: i for i, d in enumerate(DAYS_ORDER)}

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class ScheduleSpec(BaseModel):
    """When a schedule fires: set of weekdays + a HH:MM time in server-local time."""

    model_config = ConfigDict(extra="forbid")

    days: List[DayOfWeek] = Field(..., min_length=1, description="At least one weekday.")
    time: str = Field(..., description="24-hour HH:MM in server-local time.")

    @field_validator("time")
    @classmethod
    def _validate_time(cls, v: str) -> str:
        if not _TIME_RE.match(v):
            raise ValueError("time must be HH:MM in 24-hour format")
        return v

    @field_validator("days")
    @classmethod
    def _dedupe_and_order(cls, v: List[DayOfWeek]) -> List[DayOfWeek]:
        seen = set(v)
        return [d for d in DAYS_ORDER if d in seen]


class Schedule(BaseModel):
    """A weekly recurring schedule owned by one user but visible to all."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str = Field(..., min_length=1, max_length=80)
    enabled: bool = True

    spec: ScheduleSpec

    # Run parameters
    branch: str
    arch: str
    regtests_branch: Optional[str] = None
    connection_name: str = "local"  # "local" or the owner's named connection
    skip_unit: bool = False
    skip_regression: bool = False
    # When True, runs produced by this schedule are stamped public=True in
    # their RunMeta / RunIndexEntry and appear on the unauthenticated
    # /api/public/* surface.
    public: bool = False

    # Ownership / audit
    owner: str  # username that created the schedule
    created_at: datetime
    modified_at: datetime

    # Runtime state (updated by the scheduler task; not user-editable)
    last_triggered_at: Optional[datetime] = None
    last_run_id: Optional[str] = None
    last_status: Optional[str] = None  # "started" | "queued" | "skipped_busy" | "error" | "skipped_2fa"
    last_message: Optional[str] = None  # short human-readable reason


class ScheduleCreateRequest(BaseModel):
    """Body for ``POST /api/schedules`` — owner and id are server-assigned."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=80)
    enabled: bool = True
    spec: ScheduleSpec
    branch: str
    arch: str
    regtests_branch: Optional[str] = None
    connection_name: str = "local"
    skip_unit: bool = False
    skip_regression: bool = False
    public: bool = False


class ScheduleUpdateRequest(BaseModel):
    """Body for ``PUT /api/schedules/{id}`` — same shape as create."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=80)
    enabled: bool = True
    spec: ScheduleSpec
    branch: str
    arch: str
    regtests_branch: Optional[str] = None
    connection_name: str = "local"
    skip_unit: bool = False
    skip_regression: bool = False
    public: bool = False
