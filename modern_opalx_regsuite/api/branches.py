"""Endpoints to list available git branches for OPALX and regression-tests repos."""
from __future__ import annotations

import subprocess
from typing import Annotated

from fastapi import APIRouter, Depends

from ..config import SuiteConfig
from .deps import get_config, require_auth

router = APIRouter(prefix="/api/branches", tags=["branches"])


def _list_git_branches(repo_path) -> list[str]:
    """Return sorted branch names from the local git repo via ls-remote."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", "origin"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())
        branches: list[str] = []
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 2:
                ref = parts[1].strip()
                if ref.startswith("refs/heads/"):
                    branches.append(ref[len("refs/heads/"):])
        return sorted(set(branches))
    except Exception:
        # Fall back to local branches only.
        try:
            result = subprocess.run(
                ["git", "branch", "--format=%(refname:short)"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            return sorted({b.strip() for b in result.stdout.splitlines() if b.strip()})
        except Exception:
            return []


@router.get("/opalx")
def opalx_branches(
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
) -> dict[str, list[str]]:
    return {"branches": _list_git_branches(cfg.resolved_opalx_repo_root)}


@router.get("/regtests")
def regtests_branches(
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
) -> dict[str, list[str]]:
    return {"branches": _list_git_branches(cfg.resolved_regtests_repo_root)}
