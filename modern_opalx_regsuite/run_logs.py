"""Run logs on disk: ``logs/<name>.log`` while a run is live, ``logs/<name>.log.gz`` after.

Once a run has fully ended (pipeline returned and the live-log tailer has flushed),
:func:`finalize_run_files` gzips every plain log and rewrites the artifact manifest.
Readers of finished-run logs use :func:`read_log_text`, which accepts either form; the
``/data`` mount serves ``x.log`` from ``x.log.gz`` with ``Content-Encoding: gzip``
(``api/app.py``), so log links keep their plain names.
"""
from __future__ import annotations

import gzip
import hashlib
from pathlib import Path
from typing import Optional

_CHUNK = 1024 * 1024


def gz_path(path: Path) -> Path:
    return path.with_name(path.name + ".gz")


def resolve_log(path: Path) -> Optional[Path]:
    """The file that holds the log named *path*: the plain file, else its ``.gz``."""
    if path.is_file():
        return path
    gz = gz_path(path)
    return gz if gz.is_file() else None


def log_exists(path: Path) -> bool:
    return resolve_log(path) is not None


def read_log_text(path: Path) -> str:
    """Text of the log named *path*, plain or gzipped; raises ``FileNotFoundError``."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        pass  # gzipped meanwhile, or only the .gz exists
    with gzip.open(gz_path(path), "rb") as f:
        return f.read().decode("utf-8", errors="replace")


def gzip_log(path: Path) -> bool:
    """Replace the plain log *path* by ``path.gz``; returns False if there was no plain log.

    The compressed file is written next to the target and checked to decompress to the same
    bytes before it replaces any existing ``.gz`` and the plain file is removed. If a
    ``.gz`` already exists (lines appended after an earlier gzip), the plain text is added
    to its end.
    """
    if not path.is_file():
        return False
    gz = gz_path(path)
    tmp = path.with_name(f".{gz.name}.tmp")
    digest = hashlib.sha256()
    try:
        with gzip.GzipFile(tmp, "wb", compresslevel=6, mtime=0) as out:
            sources = ([gz] if gz.is_file() else []) + [path]
            for src in sources:
                opener = gzip.open if src == gz else open
                with opener(src, "rb") as f:
                    while chunk := f.read(_CHUNK):
                        digest.update(chunk)
                        out.write(chunk)
        check = hashlib.sha256()
        with gzip.open(tmp, "rb") as f:
            while chunk := f.read(_CHUNK):
                check.update(chunk)
        if check.digest() != digest.digest():
            raise OSError(f"gzip check failed for {path}")
        tmp.replace(gz)
    finally:
        if tmp.exists():
            tmp.unlink()
    path.unlink()
    return True


def gzip_run_logs(run_root: Path) -> int:
    """Gzip every plain ``logs/*.log`` of a finished run; returns how many were compressed."""
    logs = run_root / "logs"
    if not logs.is_dir():
        return 0
    return sum(gzip_log(p) for p in sorted(logs.glob("*.log")))


def finalize_run_files(run_root: Path) -> None:
    """Post-run step: gzip the logs and rewrite the manifest. Call only after every writer
    of the run's logs has finished (see ``api/coordinator.py``)."""
    from .artifacts import write_artifact_manifest  # artifacts imports this module

    if not run_root.is_dir():
        return
    gzip_run_logs(run_root)
    write_artifact_manifest(run_root)

