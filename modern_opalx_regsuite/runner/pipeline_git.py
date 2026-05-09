from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from ..config import SuiteConfig
from ..data_model import RunMeta
from .execution import RunPaths, _append_pipeline_line, _write_json
from .git import _get_repo_url, _git_head_short, _git_update_repo


def sync_repositories(
    *,
    cfg: SuiteConfig,
    meta: RunMeta,
    paths: RunPaths,
    branch: str,
    connection_name: str,
    remote: Optional["RemoteExecutor"],  # type: ignore[name-defined]
    remote_base: Optional[str],
    opalx_repo: Path,
    regtests_repo: Path,
    repo_locks: Optional[dict[str, threading.Lock]],
    cancel_event: Optional[threading.Event],
) -> tuple[bool, bool]:
    """Update local or remote source checkouts and write commit metadata."""
    if remote is not None:
        assert remote_base is not None
        meta.opalx_commit = _git_head_short(opalx_repo)
        meta.tests_repo_commit = _git_head_short(regtests_repo)
        _write_json(paths.meta_path, meta.model_dump())

        opalx_url = _get_repo_url(opalx_repo, cfg.opalx_repo_url)
        regtests_url = _get_repo_url(regtests_repo, cfg.regtests_repo_url)

        _append_pipeline_line(
            paths.pipeline_log_path,
            f"[{connection_name}] Cloning/updating OPALX (branch={branch})",
        )
        remote_opalx_ok = remote.git_clone_or_update(
            opalx_url,
            f"{remote_base}/opalx-src",
            branch,
            log_path=paths.pipeline_log_path,
            cancel_event=cancel_event,
        )
        _append_pipeline_line(
            paths.pipeline_log_path,
            f"[{connection_name}] Cloning/updating regression-tests (branch={cfg.regtests_branch})",
        )
        remote_regtests_ok = remote.git_clone_or_update(
            regtests_url,
            f"{remote_base}/regtests",
            cfg.regtests_branch,
            log_path=paths.pipeline_log_path,
            cancel_event=cancel_event,
        )
        opalx_git_ok = remote_opalx_ok and remote_regtests_ok
        if opalx_git_ok:
            meta.opalx_commit = remote.git_rev_parse_short(
                f"{remote_base}/opalx-src"
            )
            meta.tests_repo_commit = remote.git_rev_parse_short(
                f"{remote_base}/regtests"
            )
            _write_json(paths.meta_path, meta.model_dump())
            _append_pipeline_line(
                paths.pipeline_log_path,
                f"[{connection_name}] OPALX and regression-tests ready.",
            )
        return opalx_git_ok, True

    _opalx_lock = (repo_locks or {}).get(str(opalx_repo))
    _regtests_lock = (repo_locks or {}).get(str(regtests_repo))

    if _opalx_lock:
        _opalx_lock.acquire()
    try:
        _append_pipeline_line(
            paths.pipeline_log_path,
            f"Updating OPALX repo at {opalx_repo}",
        )
        opalx_git_ok = _git_update_repo(
            repo_path=opalx_repo,
            branch=branch,
            pipeline_log_path=paths.pipeline_log_path,
        )
        meta.opalx_commit = _git_head_short(opalx_repo)
    finally:
        if _opalx_lock:
            _opalx_lock.release()

    if _regtests_lock:
        _regtests_lock.acquire()
    try:
        _append_pipeline_line(
            paths.pipeline_log_path,
            f"Updating regression-tests repo at {regtests_repo} (branch {cfg.regtests_branch})",
        )
        reg_git_ok = _git_update_repo(
            repo_path=regtests_repo,
            branch=cfg.regtests_branch,
            pipeline_log_path=paths.pipeline_log_path,
        )
        meta.tests_repo_commit = _git_head_short(regtests_repo)
    finally:
        if _regtests_lock:
            _regtests_lock.release()

    _write_json(paths.meta_path, meta.model_dump())
    return opalx_git_ok, reg_git_ok
