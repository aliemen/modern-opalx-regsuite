"""Git operations: fetch, checkout, pull, and URL resolution."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from .execution import _append_pipeline_line, _run_command


def _git_update_repo(repo_path: Path, branch: str, pipeline_log_path: Path) -> bool:
    """Fetch, checkout, and pull a given branch if this looks like a git repo."""
    git_dir = repo_path / ".git"
    if not git_dir.exists():
        _append_pipeline_line(
            pipeline_log_path,
            f"[git] Skipping update; {repo_path} is not a git repository.",
        )
        return False

    def run_git(args: str) -> bool:
        cmd = f"git {args}"
        _append_pipeline_line(pipeline_log_path, f"[git] {cmd}")
        rc, _ = _run_command(
            cmd,
            cwd=repo_path,
            log_path=pipeline_log_path,
            pipeline_log_path=pipeline_log_path,
            append_log=True,
        )
        return rc == 0

    # Fetch all remote tracking refs first; using "git fetch origin" (no branch
    # arg) guarantees origin/{branch} is updated via the configured refspec,
    # which is required for the reset --hard step below.
    if not run_git("fetch origin"):
        return False
    if not run_git(f"checkout {branch}"):
        return False
    # Hard-reset to the remote tracking ref instead of ff-only pull so the
    # local branch always matches origin exactly, even if it diverged.
    return run_git(f"reset --hard origin/{branch}")


def _git_head_short(repo_path: Path) -> Optional[str]:
    git_dir = repo_path / ".git"
    if not git_dir.exists():
        return None
    proc = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(repo_path),
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _get_repo_url(repo_path: Path, config_url: Optional[str]) -> str:
    """Resolve a git clone URL: use config value or derive from local origin."""
    if config_url:
        return config_url
    proc = subprocess.run(
        ["git", "-C", str(repo_path), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    raise ValueError(
        f"Cannot determine git URL for {repo_path}. "
        "Set opalx_repo_url / regtests_repo_url in config."
    )
