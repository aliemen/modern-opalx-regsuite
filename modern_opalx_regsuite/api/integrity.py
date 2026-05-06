from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from ..artifacts import RunIntegrityReport, check_run_integrity
from ..config import SuiteConfig
from ..data_model import resolve_run_dir, runs_index_path
from .deps import get_config, require_auth


router = APIRouter(prefix="/api/integrity", tags=["integrity"])


def _index_entry(cfg: SuiteConfig, branch: str, arch: str, run_id: str) -> dict | None:
    path = runs_index_path(cfg.resolved_data_root, branch, arch)
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            entries = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if isinstance(entry, dict) and entry.get("run_id") == run_id:
            return entry
    return None


@router.get(
    "/runs/{branch}/{arch}/{run_id}",
    response_model=RunIntegrityReport,
)
def run_integrity(
    branch: str,
    arch: str,
    run_id: str,
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
) -> RunIntegrityReport:
    entry = _index_entry(cfg, branch, arch, run_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found.",
        )
    run_root = resolve_run_dir(
        cfg.resolved_data_root,
        cfg.resolved_archive_root,
        branch,
        arch,
        run_id,
        bool(entry.get("archived", False)),
    )
    return check_run_integrity(run_root)
