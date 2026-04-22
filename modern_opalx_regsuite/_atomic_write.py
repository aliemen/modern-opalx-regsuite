"""Shared atomic-write primitives for sensitive files (private keys, API key
records, connection secrets).

Both ``api/keys.py`` and ``api_keys/store.py`` used to carry hand-rolled
copies of the same ``O_CREAT | O_EXCL | O_WRONLY`` + ``os.replace`` pattern.
They are consolidated here so there is exactly one place that decides how
0600 files land on disk; any future hardening (fsync, O_NOFOLLOW) only needs
to be applied once.
"""
from __future__ import annotations

import os
from pathlib import Path


def write_secret_bytes_atomic(path: Path, content: bytes) -> None:
    """Write *content* to *path* with mode 0600, atomically.

    Guarantees:

    - The target path never transiently exists with a more permissive mode:
      we go through a sibling ``<name>.tmp`` opened with
      ``O_CREAT | O_EXCL | O_WRONLY, 0o600`` and then rename with
      :func:`os.replace`, which is atomic on POSIX.
    - The parent directory is created if missing; best-effort chmod 0700 on
      it so stray listing of the containing dir is not allowed on a multi-user
      host. Chmod failures are swallowed silently here because the caller
      already surfaces filesystem permission problems (see
      ``user_store.ensure_user_dir`` for the ssh-keys dir warning path).
    - Stale ``<name>.tmp`` from a previous crashed write is removed before
      the new O_EXCL open so we do not deadlock on it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    tmp = path.with_suffix(path.suffix + ".tmp")
    if tmp.exists():
        try:
            tmp.unlink()
        except OSError:
            pass
    fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, content)
    finally:
        os.close(fd)
    os.replace(tmp, path)
