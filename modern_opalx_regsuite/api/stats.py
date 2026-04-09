"""Dashboard statistics endpoint."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..archive_service import filter_entries_by_view
from ..config import SuiteConfig
from ..data_model import branches_index_path, runs_index_path
from .deps import get_config, require_auth

router = APIRouter(prefix="/api", tags=["stats"])

ViewMode = Literal["active", "archived", "all"]


class DashboardStats(BaseModel):
    last_run: Optional[datetime] = None
    last_run_branch: Optional[str] = None
    last_run_arch: Optional[str] = None
    last_run_status: Optional[str] = None
    runs_total: int = 0
    runs_last_week: int = 0
    branches_covered: int = 0
    avg_unit_pass_rate_master: Optional[float] = None
    avg_regression_pass_rate_master: Optional[float] = None


@router.get("/stats", response_model=DashboardStats)
def get_dashboard_stats(
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
    view: ViewMode = Query("active"),
) -> DashboardStats:
    """Compute aggregate statistics from run index files (filtered by *view*)."""
    data_root = cfg.resolved_data_root
    branches_path = branches_index_path(data_root)

    if not branches_path.is_file():
        return DashboardStats()

    with branches_path.open("r", encoding="utf-8") as f:
        branches: dict[str, list[str]] = json.load(f)

    now = datetime.now(timezone.utc)
    one_week_ago = now - timedelta(days=7)

    runs_total = 0
    runs_last_week = 0
    last_run_time: Optional[datetime] = None
    last_run_branch: Optional[str] = None
    last_run_arch: Optional[str] = None
    last_run_status: Optional[str] = None

    master_unit_rates: list[float] = []
    master_reg_rates: list[float] = []
    branches_with_visible_runs: set[str] = set()

    for branch, archs in branches.items():
        for arch in archs:
            idx_path = runs_index_path(data_root, branch, arch)
            if not idx_path.is_file():
                continue
            try:
                with idx_path.open("r", encoding="utf-8") as f:
                    entries = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
            entries = filter_entries_by_view(entries, view)
            if entries:
                branches_with_visible_runs.add(branch)

            for entry in entries:
                runs_total += 1

                started_raw = entry.get("started_at")
                if not started_raw:
                    continue
                try:
                    started = datetime.fromisoformat(started_raw)
                except (ValueError, TypeError):
                    continue
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)

                finished_raw = entry.get("finished_at")
                if finished_raw:
                    try:
                        finished = datetime.fromisoformat(finished_raw)
                        if finished.tzinfo is None:
                            finished = finished.replace(tzinfo=timezone.utc)
                        if last_run_time is None or finished > last_run_time:
                            last_run_time = finished
                            last_run_branch = branch
                            last_run_arch = arch
                            last_run_status = entry.get("status")
                    except (ValueError, TypeError):
                        pass

                if started >= one_week_ago:
                    runs_last_week += 1

                # Master pass rates (only from completed runs).
                if branch == "master" and entry.get("status") in ("passed", "failed"):
                    total_unit = entry.get("unit_tests_total", 0)
                    failed_unit = entry.get("unit_tests_failed", 0)
                    if total_unit > 0:
                        master_unit_rates.append(
                            (total_unit - failed_unit) / total_unit * 100
                        )

                    total_reg = entry.get("regression_total", 0)
                    passed_reg = entry.get("regression_passed", 0)
                    if total_reg > 0:
                        master_reg_rates.append(passed_reg / total_reg * 100)

    avg_unit = (
        round(sum(master_unit_rates) / len(master_unit_rates), 1)
        if master_unit_rates
        else None
    )
    avg_reg = (
        round(sum(master_reg_rates) / len(master_reg_rates), 1)
        if master_reg_rates
        else None
    )

    return DashboardStats(
        last_run=last_run_time,
        last_run_branch=last_run_branch,
        last_run_arch=last_run_arch,
        last_run_status=last_run_status,
        runs_total=runs_total,
        runs_last_week=runs_last_week,
        branches_covered=len(branches_with_visible_runs),
        avg_unit_pass_rate_master=avg_unit,
        avg_regression_pass_rate_master=avg_reg,
    )
