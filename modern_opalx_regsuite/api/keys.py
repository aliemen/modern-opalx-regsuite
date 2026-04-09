"""SSH key management endpoints (per-user).

Each authenticated regsuite user has their own ``ssh-keys/`` directory under
``<users_root>/<username>/``. Keys are referenced by name from a
:class:`~modern_opalx_regsuite.config.Connection`. Deletion of a key that is
referenced by any of the user's connections returns 409 Conflict.
"""
from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from ..config import SuiteConfig
from ..user_store import (
    connections_referencing_key,
    user_keys_dir,
)
from .deps import get_config, require_user_paths

router = APIRouter(prefix="/api/settings/ssh-keys", tags=["settings"])

_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


class SshKeyInfo(BaseModel):
    name: str
    created_at: str
    fingerprint: str | None = None


def _validate_name(name: str) -> None:
    if not _NAME_RE.fullmatch(name):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Key name must match [a-zA-Z0-9_-]+.",
        )


def _fingerprint(key_path: Path) -> str | None:
    """Compute SSH key fingerprint via ssh-keygen."""
    try:
        proc = subprocess.run(
            ["ssh-keygen", "-lf", str(key_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except FileNotFoundError:
        pass
    return None


def _write_key_atomic(key_path: Path, content: bytes) -> None:
    """Write *content* to *key_path* with mode 0600 atomically.

    Uses ``O_CREAT | O_EXCL | O_WRONLY`` against a temp file then ``os.replace``
    so the key file never exists at any other mode (no 0644 race window).
    """
    key_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(key_path.parent, 0o700)
    except OSError:
        pass
    tmp = key_path.with_suffix(key_path.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, content)
    finally:
        os.close(fd)
    os.replace(tmp, key_path)


@router.post("", status_code=201, response_model=SshKeyInfo)
async def upload_ssh_key(
    name: Annotated[str, Form(...)],
    key_file: Annotated[UploadFile, File(...)],
    user_paths: Annotated[tuple[str, Path], Depends(require_user_paths)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
    cert_file: Annotated[UploadFile | None, File()] = None,
) -> SshKeyInfo:
    """Upload a private key, and optionally a certificate file alongside it.

    The certificate (e.g. ``cscs-key-cert.pub`` from CSCS) is stored as
    ``<name>-cert.pub`` next to ``<name>.pem``. If present, Paramiko will
    automatically use it for certificate-based authentication (required by
    some HPC sites like CSCS Alps/Daint).
    """
    _validate_name(name)
    username, _ = user_paths
    keys = user_keys_dir(cfg, username)
    key_path = keys / f"{name}.pem"

    content = await key_file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Key file is empty.",
        )

    _write_key_atomic(key_path, content)

    if cert_file is not None:
        cert_content = await cert_file.read()
        if cert_content:
            cert_path = keys / f"{name}-cert.pub"
            _write_key_atomic(cert_path, cert_content)

    fp = _fingerprint(key_path)
    mtime = datetime.fromtimestamp(key_path.stat().st_mtime, tz=timezone.utc)
    return SshKeyInfo(name=name, created_at=mtime.isoformat(), fingerprint=fp)


@router.post("/{name}/cert", status_code=204)
async def upload_ssh_key_cert(
    name: str,
    cert_file: Annotated[UploadFile, File(...)],
    user_paths: Annotated[tuple[str, Path], Depends(require_user_paths)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
) -> None:
    """Upload or replace the certificate for an existing SSH key.

    The certificate is stored as ``<name>-cert.pub`` next to ``<name>.pem``.
    Use this endpoint to add a certificate to a key that was uploaded without one.
    """
    _validate_name(name)
    username, _ = user_paths
    keys = user_keys_dir(cfg, username)
    key_path = keys / f"{name}.pem"
    if not key_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Key '{name}' not found.",
        )
    cert_content = await cert_file.read()
    if not cert_content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Certificate file is empty.",
        )
    cert_path = keys / f"{name}-cert.pub"
    _write_key_atomic(cert_path, cert_content)


@router.put("/{name}", response_model=SshKeyInfo)
async def replace_ssh_key(
    name: str,
    key_file: Annotated[UploadFile, File(...)],
    user_paths: Annotated[tuple[str, Path], Depends(require_user_paths)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
    cert_file: Annotated[UploadFile | None, File()] = None,
) -> SshKeyInfo:
    """Replace the contents of an existing SSH key in place.

    Useful for short-lived keys (e.g. CSCS Daint, where the key + certificate
    are valid for only one day): the file on disk is overwritten atomically,
    so every :class:`~modern_opalx_regsuite.config.Connection` that references
    this key by name automatically picks up the new credentials on its next
    use — no unlink/relink dance required.

    A new ``cert_file`` is optional. If provided, it replaces ``<name>-cert.pub``
    next to the key. If omitted, any existing certificate is left untouched
    (use ``DELETE /{name}`` + re-upload if you want to remove a stale cert).
    """
    _validate_name(name)
    username, _ = user_paths
    keys = user_keys_dir(cfg, username)
    key_path = keys / f"{name}.pem"
    if not key_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Key '{name}' not found.",
        )

    content = await key_file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Key file is empty.",
        )

    _write_key_atomic(key_path, content)

    if cert_file is not None:
        cert_content = await cert_file.read()
        if cert_content:
            cert_path = keys / f"{name}-cert.pub"
            _write_key_atomic(cert_path, cert_content)

    fp = _fingerprint(key_path)
    mtime = datetime.fromtimestamp(key_path.stat().st_mtime, tz=timezone.utc)
    return SshKeyInfo(name=name, created_at=mtime.isoformat(), fingerprint=fp)


@router.get("", response_model=list[SshKeyInfo])
def list_ssh_keys(
    user_paths: Annotated[tuple[str, Path], Depends(require_user_paths)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
) -> list[SshKeyInfo]:
    username, _ = user_paths
    keys = user_keys_dir(cfg, username)
    result: list[SshKeyInfo] = []
    if not keys.is_dir():
        return result
    for p in sorted(keys.glob("*.pem")):
        mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        fp = _fingerprint(p)
        result.append(
            SshKeyInfo(name=p.stem, created_at=mtime.isoformat(), fingerprint=fp)
        )
    return result


@router.delete("/{name}", status_code=204)
def delete_ssh_key(
    name: str,
    user_paths: Annotated[tuple[str, Path], Depends(require_user_paths)],
    cfg: Annotated[SuiteConfig, Depends(get_config)],
) -> None:
    _validate_name(name)
    username, _ = user_paths

    # Block deletion if any connection (or its gateway) references this key.
    dependents = connections_referencing_key(cfg, username, name)
    if dependents:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    f"Key '{name}' is in use by {len(dependents)} connection(s). "
                    "Unlink them before deleting."
                ),
                "dependent_connections": dependents,
            },
        )

    keys = user_keys_dir(cfg, username)
    key_path = keys / f"{name}.pem"
    if not key_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Key '{name}' not found.",
        )
    key_path.unlink()
    cert_path = keys / f"{name}-cert.pub"
    if cert_path.is_file():
        cert_path.unlink()
