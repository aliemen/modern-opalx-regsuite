"""Developer-facing dashboard statistics.

Replaces the vanity-metric-only ``/api/stats`` panel with a small set of
actionable signals computed from the existing on-disk data:

* ``GET /api/stats/latest-master``     — current master state per arch
* ``GET /api/stats/newly-broken``      — regression sims that broke vs prev run
* ``GET /api/stats/suite-duration``    — current vs avg-of-last-10 master suite duration
* ``GET /api/stats/activity``          — 14-day daily run-count breakdown

All endpoints honour the ``view`` query param so the archive page can show
its own historical context if we ever want it (default: active runs only).
Cost is bounded by O(archs) JSON file reads per request — well under the
60-second polling cadence used by the StatsPanel cards.
"""
from __future__ import annotations

import json
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..archive_service import filter_entries_by_view
from ..config import SuiteConfig
from ..data_model import (
    RegressionTestsReport,
    branches_index_path,
    run_dir,
    runs_index_path,
)
from .deps import get_config, require_auth

router = APIRouter(prefix="/api/stats", tags=["stats"])

ViewMode = Literal["active", "archived", "all"]


# ── Schemas ─────────────────────────────────────────────────────────────────


class LatestMasterCell(BaseModel):
    arch: str
    run_id: Optional[str] = None
    status: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    unit_total: int = 0
    unit_failed: int = 0
    regression_total: int = 0
    regression_passed: int = 0
    regression_failed: int = 0
    regression_broken: int = 0


class LatestMasterMatrix(BaseModel):
    cells: list[LatestMasterCell]


class NewlyBrokenEntry(BaseModel):
    arch: str
    current_run_id: Optional[str] = None
    previous_run_id: Optional[str] = None
    sim_names: list[str] = []
    enough_runs: bool = True


class NewlyBrokenReport(BaseModel):
    entries: list[NewlyBrokenEntry]


class SuiteDurationCell(BaseModel):
    arch: str
    current_seconds: Optional[float] = None
    avg_last_10_seconds: Optional[float] = None
    delta_pct: Optional[float] = None


class SuiteDurationReport(BaseModel):
    cells: list[SuiteDurationCell]


class ActivityDay(BaseModel):
    date: date
    passed: int = 0
    failed: int = 0
    broken: int = 0


class ActivityReport(BaseModel):
    days: list[ActivityDay]


# ── Internal helpers ────────────────────────────────────────────────────────


def _load_index(data_root: Path, branch: str, arch: str, view: ViewMode) -> list[dict]:
    idx_path = runs_index_path(data_root, branch, arch)
    if not idx_path.is_file():
        return []
    try:
        with idx_path.open("r", encoding="utf-8") as f:
            entries = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(entries, list):
        return []
    return filter_entries_by_view(entries, view)


def _list_master_archs(data_root: Path) -> list[str]:
    branches_path = branches_index_path(data_root)
    if not branches_path.is_file():
        return []
    try:
        with branches_path.open("r", encoding="utf-8") as f:
            branches = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    archs = branches.get("master", [])
    return list(archs) if isinstance(archs, list) else []


def _parse_dt(raw) -> Optional[datetime]:
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def _failing_sim_names(report: RegressionTestsReport) -> set[str]:
    """Return the set of regression simulation names that have at least one
    failing or broken metric, OR whose own ``state`` is failed/broken.
    """
    out: set[str] = set()
    for sim in report.simulations:
        sim_state = (sim.state or "").lower()
        if sim_state in {"failed", "broken"}:
            out.add(sim.name)
            continue
        for metric in sim.metrics:
            metric_state = (metric.state or "").lower()
            if metric_state in {"failed", "broken"}:
                out.add(sim.name)
                break
    return out


def _load_regression_report(
    data_root: Path, branch: str, arch: str, run_id: str
) -> Optional[RegressionTestsReport]:
    path = run_dir(data_root, branch, arch, run_id) / "regression-tests.json"
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    try:
        return RegressionTestsReport.model_validate(data)
    except Exception:
        return None


def _duration_seconds_from_entry(entry: dict) -> Optional[float]:
    started = _parse_dt(entry.get("started_at"))
    finished = _parse_dt(entry.get("finished_at"))
    if started is None or finished is None:
        return None
    return max(0.0, (finished - started).total_seconds())


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/latest-master", response_model=LatestMasterMatrix)
def latest_master(
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
    view: ViewMode = Query("active"),
) -> LatestMasterMatrix:
    """Latest master run per architecture (one row per arch)."""
    data_root = cfg.resolved_data_root
    cells: list[LatestMasterCell] = []
    for arch in _list_master_archs(data_root):
        entries = _load_index(data_root, "master", arch, view)
        if not entries:
            cells.append(LatestMasterCell(arch=arch))
            continue
        # Index entries are sorted started_at desc — first is the latest.
        e = entries[0]
        started = _parse_dt(e.get("started_at"))
        finished = _parse_dt(e.get("finished_at"))
        cells.append(
            LatestMasterCell(
                arch=arch,
                run_id=e.get("run_id"),
                status=e.get("status"),
                started_at=started,
                finished_at=finished,
                duration_seconds=_duration_seconds_from_entry(e),
                unit_total=int(e.get("unit_tests_total", 0) or 0),
                unit_failed=int(e.get("unit_tests_failed", 0) or 0),
                regression_total=int(e.get("regression_total", 0) or 0),
                regression_passed=int(e.get("regression_passed", 0) or 0),
                regression_failed=int(e.get("regression_failed", 0) or 0),
                regression_broken=int(e.get("regression_broken", 0) or 0),
            )
        )
    return LatestMasterMatrix(cells=cells)


@router.get("/newly-broken", response_model=NewlyBrokenReport)
def newly_broken(
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
    view: ViewMode = Query("active"),
) -> NewlyBrokenReport:
    """Per arch, list regression sims failing in the latest master run that
    were passing in the previous master run.
    """
    data_root = cfg.resolved_data_root
    out: list[NewlyBrokenEntry] = []
    for arch in _list_master_archs(data_root):
        entries = _load_index(data_root, "master", arch, view)
        # Need two completed runs to compute a diff. "Completed" = status in
        # passed/failed (not running, not cancelled, not unknown).
        completed = [
            e for e in entries if e.get("status") in ("passed", "failed")
        ]
        if len(completed) < 2:
            out.append(
                NewlyBrokenEntry(
                    arch=arch,
                    current_run_id=completed[0].get("run_id") if completed else None,
                    previous_run_id=None,
                    sim_names=[],
                    enough_runs=False,
                )
            )
            continue
        curr_id = completed[0].get("run_id")
        prev_id = completed[1].get("run_id")
        if not (isinstance(curr_id, str) and isinstance(prev_id, str)):
            out.append(NewlyBrokenEntry(arch=arch, enough_runs=False))
            continue

        curr_report = _load_regression_report(data_root, "master", arch, curr_id)
        prev_report = _load_regression_report(data_root, "master", arch, prev_id)
        curr_failing = _failing_sim_names(curr_report) if curr_report else set()
        prev_failing = _failing_sim_names(prev_report) if prev_report else set()
        delta = sorted(curr_failing - prev_failing)
        out.append(
            NewlyBrokenEntry(
                arch=arch,
                current_run_id=curr_id,
                previous_run_id=prev_id,
                sim_names=delta,
                enough_runs=True,
            )
        )
    return NewlyBrokenReport(entries=out)


@router.get("/suite-duration", response_model=SuiteDurationReport)
def suite_duration(
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
    view: ViewMode = Query("active"),
) -> SuiteDurationReport:
    """Master suite duration: latest vs average of the previous 10 completed runs."""
    data_root = cfg.resolved_data_root
    out: list[SuiteDurationCell] = []
    for arch in _list_master_archs(data_root):
        entries = _load_index(data_root, "master", arch, view)
        completed = [
            e for e in entries if e.get("status") in ("passed", "failed")
        ]
        if not completed:
            out.append(SuiteDurationCell(arch=arch))
            continue
        curr = _duration_seconds_from_entry(completed[0])
        history = [
            d
            for d in (
                _duration_seconds_from_entry(e) for e in completed[1:11]
            )
            if d is not None and d > 0
        ]
        avg = (sum(history) / len(history)) if history else None
        delta_pct = None
        if curr is not None and avg is not None and avg > 0:
            delta_pct = round((curr / avg - 1.0) * 100, 1)
        out.append(
            SuiteDurationCell(
                arch=arch,
                current_seconds=round(curr, 1) if curr is not None else None,
                avg_last_10_seconds=round(avg, 1) if avg is not None else None,
                delta_pct=delta_pct,
            )
        )
    return SuiteDurationReport(cells=out)


@router.get("/activity", response_model=ActivityReport)
def activity(
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
    view: ViewMode = Query("active"),
    days: int = Query(14, ge=1, le=90),
) -> ActivityReport:
    """Daily run-count breakdown over the last *days* days, all branches."""
    data_root = cfg.resolved_data_root
    branches_path = branches_index_path(data_root)
    if not branches_path.is_file():
        return ActivityReport(days=[])
    try:
        with branches_path.open("r", encoding="utf-8") as f:
            branches = json.load(f)
    except (json.JSONDecodeError, OSError):
        return ActivityReport(days=[])

    # Build the canonical list of dates so empty days still appear in the chart.
    today = datetime.now(timezone.utc).date()
    earliest = today - timedelta(days=days - 1)
    counters: dict[date, dict[str, int]] = {
        earliest + timedelta(days=i): {"passed": 0, "failed": 0, "broken": 0}
        for i in range(days)
    }

    for branch, archs in branches.items():
        for arch in archs:
            for entry in _load_index(data_root, branch, arch, view):
                started = _parse_dt(entry.get("started_at"))
                if started is None:
                    continue
                d = started.date()
                if d < earliest or d > today:
                    continue
                bucket = counters.get(d)
                if bucket is None:
                    continue
                status = entry.get("status")
                if status == "passed":
                    bucket["passed"] += 1
                elif status == "failed":
                    bucket["failed"] += 1
                elif status == "broken":
                    bucket["broken"] += 1

    return ActivityReport(
        days=[
            ActivityDay(
                date=d,
                passed=counters[d]["passed"],
                failed=counters[d]["failed"],
                broken=counters[d]["broken"],
            )
            for d in sorted(counters.keys())
        ]
    )
