"""Unauthenticated public endpoints.

Exposes a minimal read-only surface for runs whose ``public`` flag is True
(and which are not archived). Used by the public panel on the login page
and by the read-only PublicRunDetailPage.

Security notes
--------------
* No ``Depends(require_auth)``: these routes are mounted outside the auth
  fence on purpose. Mutation endpoints live in ``api/results.py`` and remain
  authenticated.
* Defense in depth on the detail endpoint: the runs-index filter and a
  second check against ``run-meta.json.public`` must both pass before any
  payload is returned. A stale index entry cannot leak a private run.
* No username enumeration: no leaderboard, no ``triggered_by`` filter. The
  individual run payload may reveal ``triggered_by`` — publishing the run
  is the user's consent to surface that field.
* Logs are intentionally not exposed by the public detail endpoint; only
  the run metadata, unit report, and regression report are returned, so
  paths that may appear in ``logs/pipeline.log`` stay private.
"""
from __future__ import annotations

import json
from datetime import datetime, date, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from ..archive_service import filter_public_entries
from ..config import SuiteConfig
from ..data_model import (
    RegressionTestsReport,
    RunIndexEntry,
    RunMeta,
    UnitTestsReport,
    branches_index_path,
    run_dir,
    runs_index_path,
)
from .deps import get_config

router = APIRouter(prefix="/api/public", tags=["public"])


class PublicPaginatedRuns(BaseModel):
    runs: list[RunIndexEntry]
    total: int


class PublicActivityDay(BaseModel):
    date: date
    passed: int = 0
    failed: int = 0
    broken: int = 0


class PublicActivityReport(BaseModel):
    days: list[PublicActivityDay]


class PublicRunDetail(BaseModel):
    meta: RunMeta
    unit: UnitTestsReport
    regression: RegressionTestsReport


def _iter_public_entries(cfg: SuiteConfig) -> list[RunIndexEntry]:
    """Return every public, non-archived run across all branches/archs."""
    data_root = cfg.resolved_data_root
    branches_path = branches_index_path(data_root)
    if not branches_path.is_file():
        return []
    try:
        with branches_path.open("r", encoding="utf-8") as f:
            branches: dict[str, list[str]] = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    out: list[RunIndexEntry] = []
    for branch, archs in branches.items():
        for arch in archs:
            idx_path = runs_index_path(data_root, branch, arch)
            if not idx_path.is_file():
                continue
            try:
                with idx_path.open("r", encoding="utf-8") as f:
                    raw = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(raw, list):
                continue
            out.extend(
                RunIndexEntry.model_validate(e) for e in filter_public_entries(raw)
            )
    out.sort(key=lambda e: e.started_at, reverse=True)
    return out


@router.get("/all-runs", response_model=PublicPaginatedRuns)
def list_public_runs(
    cfg: SuiteConfig = Depends(get_config),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> PublicPaginatedRuns:
    entries = _iter_public_entries(cfg)
    return PublicPaginatedRuns(
        runs=entries[offset : offset + limit],
        total=len(entries),
    )


@router.get("/stats/activity", response_model=PublicActivityReport)
def public_activity(
    cfg: SuiteConfig = Depends(get_config),
    days: int = Query(14, ge=1, le=90),
) -> PublicActivityReport:
    """Daily run-count breakdown over the last *days* days, public runs only."""
    entries = _iter_public_entries(cfg)

    today = datetime.now(timezone.utc).date()
    earliest = today - timedelta(days=days - 1)
    counters: dict[date, dict[str, int]] = {
        earliest + timedelta(days=i): {"passed": 0, "failed": 0, "broken": 0}
        for i in range(days)
    }

    for e in entries:
        d = e.started_at.date()
        if d < earliest or d > today:
            continue
        bucket = counters.get(d)
        if bucket is None:
            continue
        if e.status == "passed":
            bucket["passed"] += 1
        elif e.status == "failed":
            bucket["failed"] += 1
        elif e.status == "broken":
            bucket["broken"] += 1

    return PublicActivityReport(
        days=[
            PublicActivityDay(
                date=d,
                passed=counters[d]["passed"],
                failed=counters[d]["failed"],
                broken=counters[d]["broken"],
            )
            for d in sorted(counters.keys())
        ]
    )


@router.get(
    "/runs/{branch}/{arch}/{run_id}",
    response_model=PublicRunDetail,
)
def get_public_run(
    branch: str,
    arch: str,
    run_id: str,
    cfg: SuiteConfig = Depends(get_config),
) -> PublicRunDetail:
    """Return the public-facing run detail.

    Re-validates ``meta.public`` and ``not meta.archived`` directly from
    ``run-meta.json`` — a stale runs-index entry cannot expose a private run.
    """
    rdir = run_dir(cfg.resolved_data_root, branch, arch, run_id)
    if not rdir.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Run not found."
        )

    def _load(name: str) -> Any:
        p = rdir / name
        if not p.is_file():
            return {}
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)

    meta_data = _load("run-meta.json")
    try:
        meta = RunMeta.model_validate(meta_data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Run not found."
        ) from exc

    if not meta.public or meta.archived:
        # Uniform 404 so unauthenticated scrapers can't distinguish "not
        # published" from "does not exist".
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Run not found."
        )

    unit_data = _load("unit-tests.json")
    reg_data = _load("regression-tests.json")

    return PublicRunDetail(
        meta=meta,
        unit=UnitTestsReport.model_validate(unit_data) if unit_data else UnitTestsReport(),
        regression=RegressionTestsReport.model_validate(reg_data)
        if reg_data
        else RegressionTestsReport(),
    )
