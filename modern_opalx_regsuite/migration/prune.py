"""Prune converted runs: back up and delete legacy metric SVGs, gzip leftover plain logs.

The contract step after ``series_migration`` and a grace period (see the design doc
``docs/superpowers/specs/2026-10-27-compact-series-storage-design.md``). Per finished run:

* Stat SVGs (``plots/*.svg`` except ``*_beamline.svg``) are removed only when nothing
  still needs them: the run has a schema-2 ``series.json.gz`` and every metric with a
  ``plot`` path also has ``series: true``, or the run has no ``regression-tests.json``
  (its SVGs are referenced by nothing). Runs with a failed conversion keep their SVGs.
* Before deleting, the SVGs are written to ``<backup_dir>/<branch>/<arch>/<run_id>-svgs.tar.gz``
  and the archive is read back and compared file by file (name and sha256). An existing
  archive that already holds identical copies is reused; otherwise a numbered archive is
  added, so a re-run after an interruption never overwrites a backup.
* ``plot`` paths are cleared in ``regression-tests.json`` before the files go, so the
  report never points at a deleted file.
* Plain ``logs/*.log`` are gzipped (``run_logs.gzip_run_logs``) and an existing
  ``artifact-manifest.json`` is rebuilt.

Active runs (status ``running``/``queued`` or a ``work/`` directory) are skipped; the web
service should be stopped while this runs. Re-running is safe and finds nothing left to do.
"""
from __future__ import annotations

import hashlib
import json
import os
import tarfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator, Optional

from .. import series as series_mod
from ..artifacts import MANIFEST_NAME, write_artifact_manifest
from ..run_logs import gzip_run_logs
from .series_migration import _ACTIVE_STATUSES, _rel, iter_run_dirs

_CHUNK = 1024 * 1024


@dataclass
class PruneRunReport:
    run: str
    status: str  # pruned | dry-run | skipped | error
    reason: str = ""
    svgs: int = 0  # stat SVGs removed (or to remove, in a dry run)
    svg_bytes: int = 0
    backup: str = ""  # archive holding them
    backup_bytes: int = 0
    logs: int = 0  # plain logs gzipped (or to gzip)
    log_bytes: int = 0  # plain size before gzip


@dataclass
class PruneReport:
    root: str
    backup_dir: str
    dry_run: bool
    runs: list[PruneRunReport]

    def totals(self) -> dict:
        t: dict = {"runs": len(self.runs)}
        for r in self.runs:
            t[f"runs_{r.status}"] = t.get(f"runs_{r.status}", 0) + 1
            for key in ("svgs", "svg_bytes", "backup_bytes", "logs", "log_bytes"):
                t[key] = t.get(key, 0) + getattr(r, key)
        return t

    def to_json(self) -> str:
        return json.dumps(
            {"root": self.root, "backup_dir": self.backup_dir, "dry_run": self.dry_run,
             "totals": self.totals(), "runs": [asdict(r) for r in self.runs]},
            indent=2,
        )


def prune_root(root: Path, *, backup_dir: Path, dry_run: bool,
               only: Optional[list[Path]] = None, progress=None) -> PruneReport:
    report = PruneReport(root=str(root), backup_dir=str(backup_dir), dry_run=dry_run, runs=[])
    for run_root in (only if only is not None else iter_run_dirs(root)):
        try:
            r = prune_run(run_root, root=root, backup_dir=backup_dir, dry_run=dry_run)
        except Exception as exc:  # one broken run must not stop the batch
            r = PruneRunReport(run=_rel(run_root, root), status="error", reason=f"{type(exc).__name__}: {exc}")
        report.runs.append(r)
        if progress is not None:
            progress(r)
    return report


def prune_run(run_root: Path, *, root: Path, backup_dir: Path, dry_run: bool) -> PruneRunReport:
    rel = _rel(run_root, root)
    rep = PruneRunReport(run=rel, status="skipped")
    meta_path, reg_path = run_root / "run-meta.json", run_root / "regression-tests.json"
    if not meta_path.is_file():
        rep.reason = "no run-meta.json"
        return rep
    status = str(json.loads(meta_path.read_text(encoding="utf-8")).get("status", "")).lower()
    if status in _ACTIVE_STATUSES or (run_root / "work").exists():
        rep.reason = f"looks active (status {status or '?'}{', work/ present' if (run_root / 'work').exists() else ''})"
        return rep

    svgs = sorted(p for p in (run_root / "plots").glob("*.svg") if not p.name.endswith("_beamline.svg"))
    plain_logs = sorted((run_root / "logs").glob("*.log"))
    reg = json.loads(reg_path.read_text(encoding="utf-8")) if reg_path.is_file() else None
    keep_reason = _svgs_still_needed(run_root, reg) if svgs else None
    if keep_reason:
        svgs = []
    if not svgs and not plain_logs:
        rep.reason = keep_reason or "nothing to prune"
        return rep

    rep.svgs, rep.svg_bytes = len(svgs), sum(p.stat().st_size for p in svgs)
    rep.logs, rep.log_bytes = len(plain_logs), sum(p.stat().st_size for p in plain_logs)
    rep.reason = keep_reason or ""
    if dry_run:
        rep.status = "dry-run"
        return rep

    if svgs:
        archive = _backup_svgs(svgs, backup_dir / Path(rel).relative_to("runs"))
        rep.backup, rep.backup_bytes = str(archive), archive.stat().st_size
        if reg is not None and _clear_plot_paths(reg):
            series_mod.write_bytes_atomic(reg_path, json.dumps(reg, indent=2, default=str).encode("utf-8"))
        for p in svgs:
            p.unlink()
    gzip_run_logs(run_root)
    if (run_root / MANIFEST_NAME).is_file():
        write_artifact_manifest(run_root)
    rep.status = "pruned"
    return rep


def _svgs_still_needed(run_root: Path, reg: Optional[dict]) -> Optional[str]:
    """Why the run's stat SVGs must stay, or None if they can go."""
    if reg is None:
        return None  # no report: nothing references them
    with_plot = [m for _sim, m in _metrics(reg) if m.get("plot")]
    if not with_plot:
        return None
    if (series_mod.series_schema(run_root / series_mod.SERIES_FILE) or 0) < series_mod.SCHEMA:
        return "SVGs kept: run not converted (no schema-2 series.json.gz)"
    unconverted = [m for m in with_plot if not m.get("series")]
    if unconverted:
        return f"SVGs kept: {len(unconverted)} plot(s) failed conversion"
    return None


def _metrics(reg: dict) -> Iterator[tuple[dict, dict]]:
    for sim in reg.get("simulations", []):
        for container in sim.get("containers", []):
            for metric in container.get("metrics", []):
                yield sim, metric


def _clear_plot_paths(reg: dict) -> bool:
    changed = False
    for _sim, metric in _metrics(reg):
        if metric.get("plot"):
            metric["plot"] = None
            changed = True
    return changed


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _archive_digests(archive: Path) -> dict[str, str]:
    """Member name -> sha256 of every regular file in a .tar.gz."""
    out: dict[str, str] = {}
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            f = tar.extractfile(member)
            h = hashlib.sha256()
            while chunk := f.read(_CHUNK):
                h.update(chunk)
            out[member.name] = h.hexdigest()
    return out


def _backup_svgs(svgs: list[Path], base: Path) -> Path:
    """Archive *svgs* as ``<base>-svgs[-N].tar.gz`` (members ``plots/<name>``), verified."""
    want = {f"plots/{p.name}": _sha256(p) for p in svgs}
    base.parent.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        archive = base.with_name(f"{base.name}-svgs{'' if n == 1 else f'-{n}'}.tar.gz")
        if not archive.exists():
            break
        have = _archive_digests(archive)
        if all(have.get(name) == digest for name, digest in want.items()):
            return archive  # an earlier, interrupted prune already backed these up
        n += 1

    tmp = archive.with_name(f".{archive.name}.{os.getpid()}.tmp")
    try:
        with tarfile.open(tmp, "w:gz", compresslevel=6) as tar:
            for p in svgs:
                tar.add(p, arcname=f"plots/{p.name}")
        if _archive_digests(tmp) != want:
            raise OSError(f"backup check failed for {archive}")
        os.replace(tmp, archive)
    finally:
        if tmp.exists():
            tmp.unlink()
    return archive
