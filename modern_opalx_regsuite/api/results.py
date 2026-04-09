"""Endpoints for browsing and managing historical run data."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel

from ..archive_service import filter_entries_by_view, list_visible_branches
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
from .deps import get_config, require_auth
from .state import get_active_run

router = APIRouter(prefix="/api/results", tags=["results"])

ViewMode = Literal["active", "archived", "all"]


class RunDetail(BaseModel):
    meta: RunMeta
    unit: UnitTestsReport
    regression: RegressionTestsReport


class PaginatedRuns(BaseModel):
    runs: list[RunIndexEntry]
    total: int


@router.get("/branches")
def list_branches(
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
    view: ViewMode = Query("active"),
) -> dict[str, list[str]]:
    """Return ``{branch: [arch, ...]}`` filtered by *view*.

    With ``view="all"`` returns ``branches.json`` verbatim (every branch+arch
    that has ever produced a run). With ``view="active"`` (default) or
    ``"archived"`` only includes branch+arch combinations that currently
    contain at least one matching index entry.
    """
    return list_visible_branches(cfg.resolved_data_root, view)


@router.get("/branches/{branch}/archs/{arch}/runs", response_model=list[RunIndexEntry])
def list_runs(
    branch: str,
    arch: str,
    response: Response,
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    view: ViewMode = Query("active"),
) -> list[RunIndexEntry]:
    path = runs_index_path(cfg.resolved_data_root, branch, arch)
    if not path.is_file():
        response.headers["X-Total-Count"] = "0"
        return []
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    raw = filter_entries_by_view(raw, view)
    entries = [RunIndexEntry.model_validate(e) for e in raw]
    response.headers["X-Total-Count"] = str(len(entries))
    return entries[offset : offset + limit]


@router.get("/all-runs", response_model=PaginatedRuns)
def list_all_runs(
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    view: ViewMode = Query("active"),
) -> PaginatedRuns:
    """Return all runs across every branch/arch, sorted by started_at descending.

    Filtered by *view* (``active`` by default).
    """
    data_root = cfg.resolved_data_root
    branches_path = branches_index_path(data_root)
    if not branches_path.is_file():
        return PaginatedRuns(runs=[], total=0)

    with branches_path.open("r", encoding="utf-8") as f:
        branches: dict[str, list[str]] = json.load(f)

    all_entries: list[RunIndexEntry] = []
    for branch, archs in branches.items():
        for arch in archs:
            idx_path = runs_index_path(data_root, branch, arch)
            if not idx_path.is_file():
                continue
            try:
                with idx_path.open("r", encoding="utf-8") as f:
                    raw = json.load(f)
                raw = filter_entries_by_view(raw, view)
                all_entries.extend(RunIndexEntry.model_validate(e) for e in raw)
            except (json.JSONDecodeError, OSError):
                continue

    all_entries.sort(key=lambda e: e.started_at, reverse=True)
    return PaginatedRuns(
        runs=all_entries[offset : offset + limit],
        total=len(all_entries),
    )


@router.get("/branches/{branch}/archs/{arch}/runs/{run_id}", response_model=RunDetail)
def get_run(
    branch: str,
    arch: str,
    run_id: str,
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
) -> RunDetail:
    rdir = run_dir(cfg.resolved_data_root, branch, arch, run_id)
    if not rdir.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")

    def _load(name: str) -> Any:
        p = rdir / name
        if not p.is_file():
            return {}
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)

    meta_data = _load("run-meta.json")
    unit_data = _load("unit-tests.json")
    reg_data = _load("regression-tests.json")

    return RunDetail(
        meta=RunMeta.model_validate(meta_data),
        unit=UnitTestsReport.model_validate(unit_data) if unit_data else UnitTestsReport(),
        regression=RegressionTestsReport.model_validate(reg_data) if reg_data else RegressionTestsReport(),
    )


@router.delete("/branches/{branch}/archs/{arch}/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_run(
    branch: str,
    arch: str,
    run_id: str,
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
) -> None:
    # Refuse to delete the currently active run.
    active = get_active_run()
    if active is not None and active.run_id == run_id and active.status == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete a run that is currently in progress.",
        )

    rdir = run_dir(cfg.resolved_data_root, branch, arch, run_id)
    if not rdir.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")

    shutil.rmtree(rdir)

    # Remove the entry from the runs index.
    idx_path = runs_index_path(cfg.resolved_data_root, branch, arch)
    if idx_path.is_file():
        with idx_path.open("r", encoding="utf-8") as f:
            entries = json.load(f)
        entries = [e for e in entries if e.get("run_id") != run_id]
        with idx_path.open("w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
