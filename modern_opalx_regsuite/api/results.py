"""Endpoints for browsing and managing historical run data."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

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


class RunDetail(BaseModel):
    meta: RunMeta
    unit: UnitTestsReport
    regression: RegressionTestsReport


@router.get("/branches")
def list_branches(
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
) -> dict[str, list[str]]:
    path = branches_index_path(cfg.resolved_data_root)
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


@router.get("/branches/{branch}/archs/{arch}/runs", response_model=list[RunIndexEntry])
def list_runs(
    branch: str,
    arch: str,
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[RunIndexEntry]:
    path = runs_index_path(cfg.resolved_data_root, branch, arch)
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    entries = [RunIndexEntry.model_validate(e) for e in raw]
    return entries[offset : offset + limit]


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
