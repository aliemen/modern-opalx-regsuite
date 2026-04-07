"""SSH key management endpoints."""
from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from ..config import SuiteConfig
from .deps import get_config, require_auth

router = APIRouter(prefix="/api/settings/ssh-keys", tags=["settings"])

_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


class SshKeyInfo(BaseModel):
    name: str
    created_at: str
    fingerprint: str | None = None


def _keys_dir(cfg: SuiteConfig) -> Path:
    d = cfg.resolved_ssh_keys_dir
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


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


@router.post("", status_code=201, response_model=SshKeyInfo)
async def upload_ssh_key(
    name: str = Form(...),
    key_file: UploadFile = File(...),
    _user: str = Depends(require_auth),
    cfg: SuiteConfig = Depends(get_config),
) -> SshKeyInfo:
    _validate_name(name)
    keys = _keys_dir(cfg)
    key_path = keys / f"{name}.pem"

    content = await key_file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Key file is empty.",
        )

    key_path.write_bytes(content)
    os.chmod(key_path, 0o600)

    fp = _fingerprint(key_path)
    mtime = datetime.fromtimestamp(key_path.stat().st_mtime, tz=timezone.utc)
    return SshKeyInfo(name=name, created_at=mtime.isoformat(), fingerprint=fp)


@router.get("", response_model=list[SshKeyInfo])
def list_ssh_keys(
    _user: str = Depends(require_auth),
    cfg: SuiteConfig = Depends(get_config),
) -> list[SshKeyInfo]:
    keys = _keys_dir(cfg)
    result: list[SshKeyInfo] = []
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
    _user: str = Depends(require_auth),
    cfg: SuiteConfig = Depends(get_config),
) -> None:
    _validate_name(name)
    keys = _keys_dir(cfg)
    key_path = keys / f"{name}.pem"
    if not key_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Key '{name}' not found.",
        )
    key_path.unlink()
