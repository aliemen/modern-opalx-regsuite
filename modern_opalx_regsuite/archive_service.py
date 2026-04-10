"""Pure service for archive / unarchive / hard-delete of run data.

Used by both the API layer (``api/archive.py``) and the CLI (``cli.py``) so
the same code path is exercised in both contexts.

Design notes
------------
* Archive is a soft-delete: the ``archived`` boolean is flipped on every
  affected ``run-meta.json`` plus the corresponding entry in
  ``runs-index/<branch>/<arch>.json``. No files are moved on disk.
* Hard delete uses ``shutil.rmtree`` on the run directory plus a rewrite of
  the index file (mirrors the existing single-run delete in ``api/results.py``).
* Index reads/writes are serialised with ``fcntl.flock`` so concurrent
  pipeline-completion writes (in ``runner/pipeline.py``) and archive
  mutations cannot clobber each other.
* The currently-running and queued runs are protected by the caller passing
  ``protect_run_ids``. The service never imports from ``api.state`` directly
  (keeps the dependency graph one-way: api → service, never service → api).
"""
from __future__ import annotations

import fcntl
import json
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, Literal, Optional

from pydantic import BaseModel

from .data_model import (
    RunIndexEntry,
    RunMeta,
    branches_index_path,
    run_dir,
    runs_index_path,
)

ViewMode = Literal["active", "archived", "all"]

#: Branch name that is permanently protected from archive / hard-delete.
#: master holds the canonical history every developer cares about, so the
#: surface area to accidentally hide it must be zero. Both the API layer and
#: the CLI go through this constant.
PROTECTED_BRANCH = "master"


class ProtectedBranchError(Exception):
    """Raised when a caller tries to archive or hard-delete the protected
    branch (``master``). The API translates this into HTTP 409, the CLI into
    a typer.Exit. Unarchiving the protected branch is allowed."""

    def __init__(self, branch: str) -> None:
        super().__init__(
            f"Branch '{branch}' is protected and cannot be archived or "
            f"hard-deleted. Unarchiving is still allowed."
        )
        self.branch = branch


class ArchiveResult(BaseModel):
    """Outcome of an archive / unarchive / hard-delete operation."""

    changed: int = 0
    skipped_active: list[str] = []  # run ids skipped because they're running/queued
    not_found: list[str] = []        # run ids that did not exist on disk


# ── Index file locking ──────────────────────────────────────────────────────


@contextmanager
def locked_index(index_path: Path) -> Iterator[None]:
    """Hold an exclusive ``fcntl.flock`` on *index_path* during the with-block.

    Both the archive service and ``runner.pipeline._update_indexes`` rewrite
    the same ``runs-index/<branch>/<arch>.json`` file. Without serialisation,
    a run completing while a bulk archive is in progress could clobber the
    archive flip (or vice versa). Wrapping every read-modify-write in this
    context manager prevents that.

    Falls back to a no-op if the file does not yet exist — pipeline writes
    create the index file fresh on the first run, before any archive call
    could ever target it.
    """
    if not index_path.is_file():
        yield
        return
    with index_path.open("r+", encoding="utf-8") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _read_index(index_path: Path) -> list[dict]:
    if not index_path.is_file():
        return []
    with index_path.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return []
    if not isinstance(data, list):
        return []
    return data


def _write_index(index_path: Path, entries: list[dict]) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, default=str)


# ── Visibility helper used by GET /api/results/branches ─────────────────────


def list_visible_branches(
    data_root: Path,
    view: ViewMode,
    triggered_by: Optional[str] = None,
) -> dict[str, list[str]]:
    """Return ``{branch: [arch, ...]}`` filtered by *view* and optionally *triggered_by*.

    For ``view="all"`` with no user filter returns ``branches.json`` verbatim
    (fast path).

    Otherwise scans index files and only includes a branch+arch if at least
    one of its index entries matches the requested archive state AND was
    triggered by the requested user (when given). Cost is one ``json.load``
    per index file — same as ``GET /api/results/all-runs``.
    """
    branches_path = branches_index_path(data_root)
    if not branches_path.is_file():
        return {}
    with branches_path.open("r", encoding="utf-8") as f:
        try:
            all_branches: dict[str, list[str]] = json.load(f)
        except json.JSONDecodeError:
            return {}

    if view == "all" and triggered_by is None:
        return all_branches

    visible: dict[str, list[str]] = {}
    for branch, archs in all_branches.items():
        kept_archs: list[str] = []
        for arch in archs:
            entries = _read_index(runs_index_path(data_root, branch, arch))
            filtered = filter_entries_by_view(entries, view)
            if triggered_by is not None:
                filtered = filter_entries_by_user(filtered, triggered_by)
            if filtered:
                kept_archs.append(arch)
        if kept_archs:
            visible[branch] = kept_archs
    return visible


def filter_entries_by_view(entries: list[dict], view: ViewMode) -> list[dict]:
    """Apply *view* to a raw entry list (from a single index file)."""
    if view == "all":
        return entries
    want_archived = view == "archived"
    return [e for e in entries if bool(e.get("archived", False)) is want_archived]


def filter_entries_by_user(entries: list[dict], triggered_by: str) -> list[dict]:
    """Keep only entries whose ``triggered_by`` matches *triggered_by*.

    Both sides are normalised the same way as the users-leaderboard endpoint:
    a missing or falsy ``triggered_by`` is treated as ``"unknown"``. This
    means filtering for ``"unknown"`` correctly returns runs whose field is
    ``null``, ``""``, or literally ``"unknown"``.
    """
    normalized = triggered_by or "unknown"
    return [e for e in entries if (e.get("triggered_by") or "unknown") == normalized]


# ── Internal mutators ───────────────────────────────────────────────────────


def _patch_run_meta_archived(
    data_root: Path, branch: str, arch: str, run_id: str, archived: bool
) -> bool:
    """Flip ``archived`` on a run's ``run-meta.json``. Returns True on success."""
    rdir = run_dir(data_root, branch, arch, run_id)
    meta_path = rdir / "run-meta.json"
    if not meta_path.is_file():
        return False
    with meta_path.open("r", encoding="utf-8") as f:
        try:
            raw = json.load(f)
        except json.JSONDecodeError:
            return False
    try:
        meta = RunMeta.model_validate(raw)
    except Exception:
        return False
    if meta.archived == archived:
        return True
    meta.archived = archived
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(meta.model_dump(), f, indent=2, default=str)
    return True


def _set_archived_in_index_file(
    index_path: Path,
    archived: bool,
    *,
    run_id_filter: Optional[set[str]] = None,
    protect_run_ids: set[str],
) -> tuple[list[str], list[str], list[str]]:
    """Flip ``archived`` on entries in *index_path* under an exclusive lock.

    If *run_id_filter* is None, applies to every entry. Otherwise only to
    entries whose ``run_id`` is in the set. Entries in *protect_run_ids* are
    skipped and reported back.

    Returns ``(changed_run_ids, skipped_run_ids, not_found_run_ids)``. The
    ``not_found`` list is only meaningful when *run_id_filter* is set; for a
    full-index sweep it is always empty.
    """
    changed: list[str] = []
    skipped: list[str] = []
    not_found: list[str] = []
    with locked_index(index_path):
        entries = _read_index(index_path)
        seen_ids: set[str] = set()
        for entry in entries:
            rid = entry.get("run_id")
            if not isinstance(rid, str):
                continue
            seen_ids.add(rid)
            if run_id_filter is not None and rid not in run_id_filter:
                continue
            if rid in protect_run_ids:
                skipped.append(rid)
                continue
            current = bool(entry.get("archived", False))
            if current == archived:
                continue
            entry["archived"] = archived
            changed.append(rid)
        if changed:
            _write_index(index_path, entries)
        if run_id_filter is not None:
            not_found = sorted(run_id_filter - seen_ids)
    return changed, skipped, not_found


def _set_archived_for_index(
    data_root: Path,
    branch: str,
    arch: str,
    archived: bool,
    *,
    run_id_filter: Optional[set[str]],
    protect_run_ids: set[str],
) -> tuple[int, list[str], list[str]]:
    """Update one branch+arch index file plus each affected run-meta.json.

    Returns ``(changed_count, skipped_run_ids, not_found_run_ids)``.
    """
    index_path = runs_index_path(data_root, branch, arch)
    changed_ids, skipped_ids, not_found_ids = _set_archived_in_index_file(
        index_path,
        archived,
        run_id_filter=run_id_filter,
        protect_run_ids=protect_run_ids,
    )
    for rid in changed_ids:
        _patch_run_meta_archived(data_root, branch, arch, rid, archived)
    return len(changed_ids), skipped_ids, not_found_ids


def _list_archs_for_branch(data_root: Path, branch: str) -> list[str]:
    """Return all archs ever seen for *branch* (from ``branches.json``)."""
    branches_path = branches_index_path(data_root)
    if not branches_path.is_file():
        return []
    with branches_path.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return []
    archs = data.get(branch, [])
    return list(archs) if isinstance(archs, list) else []


# ── Public service surface ──────────────────────────────────────────────────


def set_archived_for_branch(
    data_root: Path,
    branch: str,
    archived: bool,
    protect_run_ids: Iterable[str] = (),
) -> ArchiveResult:
    """Archive or unarchive every run for *branch* (across all archs).

    Raises :class:`ProtectedBranchError` when *branch* is the protected
    branch and *archived* is True. Unarchiving the protected branch (e.g.
    after a manual mis-archive on disk) is still allowed.
    """
    if archived and branch == PROTECTED_BRANCH:
        raise ProtectedBranchError(branch)
    protect = set(protect_run_ids)
    total_changed = 0
    skipped: list[str] = []
    for arch in _list_archs_for_branch(data_root, branch):
        changed, sk, _ = _set_archived_for_index(
            data_root,
            branch,
            arch,
            archived,
            run_id_filter=None,
            protect_run_ids=protect,
        )
        total_changed += changed
        skipped.extend(sk)
    return ArchiveResult(changed=total_changed, skipped_active=skipped)


def set_archived_for_arch(
    data_root: Path,
    branch: str,
    arch: str,
    archived: bool,
    protect_run_ids: Iterable[str] = (),
) -> ArchiveResult:
    """Archive or unarchive every run for *branch* + *arch*.

    Raises :class:`ProtectedBranchError` when *branch* is the protected
    branch and *archived* is True.
    """
    if archived and branch == PROTECTED_BRANCH:
        raise ProtectedBranchError(branch)
    protect = set(protect_run_ids)
    changed, skipped, _ = _set_archived_for_index(
        data_root,
        branch,
        arch,
        archived,
        run_id_filter=None,
        protect_run_ids=protect,
    )
    return ArchiveResult(changed=changed, skipped_active=skipped)


def set_archived_for_runs(
    data_root: Path,
    branch: str,
    arch: str,
    run_ids: Iterable[str],
    archived: bool,
    protect_run_ids: Iterable[str] = (),
) -> ArchiveResult:
    """Archive or unarchive an explicit list of run ids in one branch+arch.

    Unlike branch-wide or arch-wide archiving, per-run archiving is allowed
    on the protected branch so that individual runs can be tidied up without
    hiding the entire branch from the dashboard.
    """
    requested = set(run_ids)
    if not requested:
        return ArchiveResult()
    protect = set(protect_run_ids)
    changed, skipped, not_found = _set_archived_for_index(
        data_root,
        branch,
        arch,
        archived,
        run_id_filter=requested,
        protect_run_ids=protect,
    )
    return ArchiveResult(
        changed=changed,
        skipped_active=skipped,
        not_found=not_found,
    )


def hard_delete_runs(
    data_root: Path,
    branch: str,
    arch: str,
    run_ids: Iterable[str],
    protect_run_ids: Iterable[str] = (),
) -> ArchiveResult:
    """Permanently delete runs from disk and from the index file.

    Defense in depth: even though archived runs cannot be active (active runs
    are skipped at archive time), we still refuse to hard-delete any run id
    in *protect_run_ids*. Also raises :class:`ProtectedBranchError` if the
    target branch is the protected one.
    """
    if branch == PROTECTED_BRANCH:
        raise ProtectedBranchError(branch)
    requested = set(run_ids)
    if not requested:
        return ArchiveResult()
    protect = set(protect_run_ids)
    index_path = runs_index_path(data_root, branch, arch)

    deleted: list[str] = []
    skipped: list[str] = []

    with locked_index(index_path):
        entries = _read_index(index_path)
        kept: list[dict] = []
        for entry in entries:
            rid = entry.get("run_id")
            if not isinstance(rid, str):
                kept.append(entry)
                continue
            if rid not in requested:
                kept.append(entry)
                continue
            if rid in protect:
                skipped.append(rid)
                kept.append(entry)
                continue
            rdir = run_dir(data_root, branch, arch, rid)
            if rdir.is_dir():
                shutil.rmtree(rdir)
            deleted.append(rid)
        if deleted:
            _write_index(index_path, kept)

    found = set(deleted) | set(skipped)
    not_found = sorted(requested - found)
    return ArchiveResult(
        changed=len(deleted),
        skipped_active=skipped,
        not_found=not_found,
    )


def hard_delete_arch_archived(
    data_root: Path,
    branch: str,
    arch: str,
    protect_run_ids: Iterable[str] = (),
) -> ArchiveResult:
    """Permanently delete every *archived* run for one (branch, arch) cell.

    Skips active (non-archived) entries entirely so the dashboard view of the
    cell is unaffected. Raises :class:`ProtectedBranchError` for the
    protected branch — defense in depth even though the dashboard never
    surfaces a protected-branch cell on the Archive page.
    """
    if branch == PROTECTED_BRANCH:
        raise ProtectedBranchError(branch)
    protect = set(protect_run_ids)
    index_path = runs_index_path(data_root, branch, arch)

    deleted: list[str] = []
    skipped: list[str] = []

    with locked_index(index_path):
        entries = _read_index(index_path)
        kept: list[dict] = []
        for entry in entries:
            rid = entry.get("run_id")
            is_archived = bool(entry.get("archived", False))
            if not isinstance(rid, str) or not is_archived:
                kept.append(entry)
                continue
            if rid in protect:
                skipped.append(rid)
                kept.append(entry)
                continue
            rdir = run_dir(data_root, branch, arch, rid)
            if rdir.is_dir():
                shutil.rmtree(rdir)
            deleted.append(rid)
        if deleted:
            _write_index(index_path, kept)

    return ArchiveResult(changed=len(deleted), skipped_active=skipped)
