"""Bulk archive / unarchive / hard-delete endpoints.

Thin router that delegates to ``archive_service``. The router's only job is
to:

* Resolve the protected (running + queued) run-id set from the in-process
  state singleton.
* Map service results into FastAPI responses.

The service module knows nothing about FastAPI or run state, so the same
code path is exercised by the CLI ``archive`` command.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..archive_service import (
    ArchiveResult,
    ProtectedBranchError,
    hard_delete_arch_archived,
    hard_delete_runs,
    set_archived_for_arch,
    set_archived_for_branch,
    set_archived_for_runs,
)
from ..config import SuiteConfig
from .deps import get_config, require_auth
from .state import get_all_active_runs, get_queue_snapshot

router = APIRouter(prefix="/api/archive", tags=["archive"])


class RunIdsPayload(BaseModel):
    run_ids: list[str]


def _protected_run_ids() -> set[str]:
    """Return the set of run ids that must not be archived or hard-deleted.

    Includes every actively-running run on every machine, plus every queued
    run still waiting in any machine queue.
    """
    protected: set[str] = {r.run_id for r in get_all_active_runs()}
    for machine in get_queue_snapshot():
        for qr in machine.get("queue", []):
            rid = qr.get("run_id")
            if isinstance(rid, str):
                protected.add(rid)
    return protected


def _conflict_for_protected_branch(exc: ProtectedBranchError) -> HTTPException:
    """Translate a ProtectedBranchError into HTTP 409."""
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# ── Branch-scope ────────────────────────────────────────────────────────────


@router.post("/branches/{branch}", response_model=ArchiveResult)
def archive_branch(
    branch: str,
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
) -> ArchiveResult:
    """Soft-delete every run on *branch* (across all archs)."""
    try:
        return set_archived_for_branch(
            cfg.resolved_data_root,
            branch,
            archived=True,
            protect_run_ids=_protected_run_ids(),
            archive_root=cfg.resolved_archive_root,
        )
    except ProtectedBranchError as exc:
        raise _conflict_for_protected_branch(exc) from exc


@router.delete("/branches/{branch}", response_model=ArchiveResult)
def unarchive_branch(
    branch: str,
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
) -> ArchiveResult:
    """Restore every archived run on *branch*."""
    return set_archived_for_branch(
        cfg.resolved_data_root,
        branch,
        archived=False,
        protect_run_ids=_protected_run_ids(),
        archive_root=cfg.resolved_archive_root,
    )


# ── Branch+arch scope ───────────────────────────────────────────────────────


@router.post("/branches/{branch}/archs/{arch}", response_model=ArchiveResult)
def archive_arch(
    branch: str,
    arch: str,
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
) -> ArchiveResult:
    try:
        return set_archived_for_arch(
            cfg.resolved_data_root,
            branch,
            arch,
            archived=True,
            protect_run_ids=_protected_run_ids(),
            archive_root=cfg.resolved_archive_root,
        )
    except ProtectedBranchError as exc:
        raise _conflict_for_protected_branch(exc) from exc


@router.delete("/branches/{branch}/archs/{arch}", response_model=ArchiveResult)
def unarchive_arch(
    branch: str,
    arch: str,
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
) -> ArchiveResult:
    return set_archived_for_arch(
        cfg.resolved_data_root,
        branch,
        arch,
        archived=False,
        protect_run_ids=_protected_run_ids(),
        archive_root=cfg.resolved_archive_root,
    )


# ── Per-run scope ───────────────────────────────────────────────────────────


@router.post("/branches/{branch}/archs/{arch}/runs", response_model=ArchiveResult)
def archive_runs(
    branch: str,
    arch: str,
    payload: RunIdsPayload,
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
) -> ArchiveResult:
    return set_archived_for_runs(
        cfg.resolved_data_root,
        branch,
        arch,
        payload.run_ids,
        archived=True,
        protect_run_ids=_protected_run_ids(),
        archive_root=cfg.resolved_archive_root,
    )


@router.delete("/branches/{branch}/archs/{arch}/runs", response_model=ArchiveResult)
def unarchive_runs(
    branch: str,
    arch: str,
    payload: RunIdsPayload,
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
) -> ArchiveResult:
    return set_archived_for_runs(
        cfg.resolved_data_root,
        branch,
        arch,
        payload.run_ids,
        archived=False,
        protect_run_ids=_protected_run_ids(),
        archive_root=cfg.resolved_archive_root,
    )


@router.post(
    "/branches/{branch}/archs/{arch}/runs/{run_id}/restore",
    response_model=ArchiveResult,
)
def restore_run(
    branch: str,
    arch: str,
    run_id: str,
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
) -> ArchiveResult:
    return set_archived_for_runs(
        cfg.resolved_data_root,
        branch,
        arch,
        [run_id],
        archived=False,
        protect_run_ids=_protected_run_ids(),
        archive_root=cfg.resolved_archive_root,
    )


# ── Hard delete (POST, not DELETE — explicit destructive path) ──────────────


@router.post(
    "/branches/{branch}/archs/{arch}/runs/hard-delete",
    response_model=ArchiveResult,
)
def hard_delete(
    branch: str,
    arch: str,
    payload: RunIdsPayload,
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
) -> ArchiveResult:
    """Permanently remove run directories from disk and the index entry.

    Defense in depth: even though the dashboard only invokes this from the
    Archive page (where active runs cannot appear), the service still
    refuses to delete any run currently in the protected set.
    """
    try:
        return hard_delete_runs(
            cfg.resolved_data_root,
            branch,
            arch,
            payload.run_ids,
            protect_run_ids=_protected_run_ids(),
            archive_root=cfg.resolved_archive_root,
        )
    except ProtectedBranchError as exc:
        raise _conflict_for_protected_branch(exc) from exc


@router.post(
    "/branches/{branch}/archs/{arch}/hard-delete-arch",
    response_model=ArchiveResult,
)
def hard_delete_archived_cell(
    branch: str,
    arch: str,
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
) -> ArchiveResult:
    """Permanently delete every *archived* run for one (branch, arch) cell.

    The Archive page invokes this when the user bulk-hard-deletes selected
    cells. Active (non-archived) runs in the same cell are untouched, so
    this is safe even when the cell still has live runs underneath.
    """
    try:
        return hard_delete_arch_archived(
            cfg.resolved_data_root,
            branch,
            arch,
            protect_run_ids=_protected_run_ids(),
            archive_root=cfg.resolved_archive_root,
        )
    except ProtectedBranchError as exc:
        raise _conflict_for_protected_branch(exc) from exc
