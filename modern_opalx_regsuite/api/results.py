"""Read-only endpoints for browsing historical run data."""
from __future__ import annotations

import json
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
