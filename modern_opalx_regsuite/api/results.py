"""Endpoints for browsing and managing historical run data."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel

from ..archive_service import (
    filter_entries_by_user,
    filter_entries_by_view,
    list_visible_branches,
    locked_index,
    set_public_for_runs,
)
from ..config import SuiteConfig
from ..data_model import (
    RegressionTestsReport,
    RunIndexEntry,
    RunMeta,
    UnitTestsReport,
    branches_index_path,
    resolve_run_dir,
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
    archived_on_cold_storage: bool = False


class PaginatedRuns(BaseModel):
    runs: list[RunIndexEntry]
    total: int


class ArchiveSummary(BaseModel):
    total: int = 0
    by_branch: dict[str, int] = {}
    by_regtest_branch: dict[str, int] = {}


class VisibilityBody(BaseModel):
    public: bool


def _index_entry_for_run(
    data_root: Path, branch: str, arch: str, run_id: str
) -> Optional[dict]:
    idx_path = runs_index_path(data_root, branch, arch)
    if not idx_path.is_file():
        return None
    try:
        with idx_path.open("r", encoding="utf-8") as f:
            entries = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if isinstance(entry, dict) and entry.get("run_id") == run_id:
            return entry
    return None


@router.get("/branches")
def list_branches(
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
    view: ViewMode = Query("active"),
    triggered_by: Optional[str] = Query(None),
) -> dict[str, list[str]]:
    """Return ``{branch: [arch, ...]}`` filtered by *view* and *triggered_by*.

    With ``view="all"`` and no user filter, returns ``branches.json`` verbatim
    (every branch+arch that has ever produced a run). Otherwise only includes
    branch+arch combinations that currently contain at least one matching
    index entry (matching both archive state and, if given, the user).
    """
    return list_visible_branches(
        cfg.resolved_data_root, view, triggered_by=triggered_by
    )


@router.get("/archive-summary", response_model=ArchiveSummary)
def archive_summary(
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
) -> ArchiveSummary:
    data_root = cfg.resolved_data_root
    index_root = data_root / "runs-index"
    if not index_root.is_dir():
        return ArchiveSummary()

    total = 0
    by_branch: dict[str, int] = {}
    by_regtest_branch: dict[str, int] = {}
    for idx_path in sorted(index_root.glob("*/*.json")):
        branch = idx_path.parent.name
        if not branch:
            continue
        try:
            with idx_path.open("r", encoding="utf-8") as f:
                entries = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or not bool(entry.get("archived", False)):
                continue
            reg_branch = entry.get("regtest_branch") or "(unknown)"
            if not isinstance(reg_branch, str):
                reg_branch = "(unknown)"
            total += 1
            by_branch[branch] = by_branch.get(branch, 0) + 1
            by_regtest_branch[reg_branch] = (
                by_regtest_branch.get(reg_branch, 0) + 1
            )

    return ArchiveSummary(
        total=total,
        by_branch=by_branch,
        by_regtest_branch=by_regtest_branch,
    )


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
    triggered_by: Optional[str] = Query(None),
) -> list[RunIndexEntry]:
    path = runs_index_path(cfg.resolved_data_root, branch, arch)
    if not path.is_file():
        response.headers["X-Total-Count"] = "0"
        return []
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    raw = filter_entries_by_view(raw, view)
    if triggered_by is not None:
        raw = filter_entries_by_user(raw, triggered_by)
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
    triggered_by: Optional[str] = Query(None),
) -> PaginatedRuns:
    """Return all runs across every branch/arch, sorted by started_at descending.

    Filtered by *view* (``active`` by default) and optionally by the username
    that triggered each run.
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
                if triggered_by is not None:
                    raw = filter_entries_by_user(raw, triggered_by)
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
    data_root = cfg.resolved_data_root
    archive_root = cfg.resolved_archive_root
    index_entry = _index_entry_for_run(data_root, branch, arch, run_id)
    if index_entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    archived = bool(index_entry.get("archived", False))
    rdir = resolve_run_dir(data_root, archive_root, branch, arch, run_id, archived)
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
    meta = RunMeta.model_validate(meta_data)
    meta.archived = archived
    if "public" in index_entry:
        meta.public = bool(index_entry.get("public", False))

    return RunDetail(
        meta=meta,
        unit=UnitTestsReport.model_validate(unit_data) if unit_data else UnitTestsReport(),
        regression=RegressionTestsReport.model_validate(reg_data) if reg_data else RegressionTestsReport(),
        archived_on_cold_storage=archived and archive_root is not None,
    )


@router.patch(
    "/branches/{branch}/archs/{arch}/runs/{run_id}/visibility",
    response_model=RunIndexEntry,
)
def set_run_visibility(
    branch: str,
    arch: str,
    run_id: str,
    body: VisibilityBody,
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
) -> RunIndexEntry:
    """Publish or unpublish a single run.

    Flips both the ``run-meta.json`` and the ``runs-index/<branch>/<arch>.json``
    entry under the same ``fcntl.flock`` used by archive mutations and the
    pipeline completion writer. Any authenticated user may toggle visibility
    of any run (same policy as archive/delete).
    """
    # Guard: make sure the run actually exists on disk before mutating state,
    # so a typo returns 404 instead of silently succeeding with 0 changes.
    data_root = cfg.resolved_data_root
    archive_root = cfg.resolved_archive_root
    index_entry = _index_entry_for_run(data_root, branch, arch, run_id)
    if index_entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Run not found."
        )
    rdir = resolve_run_dir(
        data_root,
        archive_root,
        branch,
        arch,
        run_id,
        bool(index_entry.get("archived", False)),
    )
    if not rdir.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Run not found."
        )

    result = set_public_for_runs(
        data_root,
        branch,
        arch,
        [run_id],
        body.public,
        archive_root=archive_root,
    )
    if result.not_found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' is missing from the runs index.",
        )

    # Return the updated index entry so the frontend can update its cache
    # without a second round trip.
    idx_path = runs_index_path(data_root, branch, arch)
    if idx_path.is_file():
        with idx_path.open("r", encoding="utf-8") as f:
            entries = json.load(f)
        for e in entries:
            if e.get("run_id") == run_id:
                return RunIndexEntry.model_validate(e)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Run '{run_id}' disappeared from the index after update.",
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

    data_root = cfg.resolved_data_root
    archive_root = cfg.resolved_archive_root
    index_entry = _index_entry_for_run(data_root, branch, arch, run_id)
    if index_entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    rdir = resolve_run_dir(
        data_root,
        archive_root,
        branch,
        arch,
        run_id,
        bool(index_entry.get("archived", False)),
    )
    if not rdir.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")

    shutil.rmtree(rdir)

    # Remove the entry from the runs index.
    idx_path = runs_index_path(data_root, branch, arch)
    if idx_path.is_file():
        with locked_index(idx_path):
            with idx_path.open("r", encoding="utf-8") as f:
                entries = json.load(f)
            entries = [e for e in entries if e.get("run_id") != run_id]
            with idx_path.open("w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2)
