"""Remote SSH execution via Fabric for the OPALX regression suite."""
from __future__ import annotations

import io
import os
import shlex
import subprocess
from pathlib import Path
from typing import Optional

from fabric import Connection


class _TeeWriter(io.RawIOBase):
    """File-like that writes each chunk to two underlying file objects."""

    def __init__(self, primary: io.IOBase, secondary: Optional[io.IOBase] = None):
        self._primary = primary
        self._secondary = secondary

    def write(self, data) -> int:  # type: ignore[override]
        if isinstance(data, memoryview):
            data = bytes(data)
        if isinstance(data, bytes):
            text = data.decode("utf-8", errors="replace")
        else:
            text = data
        self._primary.write(text)
        self._primary.flush()
        if self._secondary is not None:
            self._secondary.write(text)
            self._secondary.flush()
        return len(data)

    def writable(self) -> bool:
        return True


class RemoteExecutor:
    """SSH execution and file transfer for remote pipeline runs.

    Uses a single persistent Fabric ``Connection`` per executor instance.
    All methods are blocking (designed to run inside ``asyncio.to_thread``).
    """

    def __init__(
        self,
        host: str,
        user: str,
        key_path: Path,
        port: int = 22,
        pipeline_log_path: Optional[Path] = None,
    ) -> None:
        self._host = host
        self._user = user
        self._key_path = key_path
        self._port = port
        self._pipeline_log_path = pipeline_log_path
        self._conn: Optional[Connection] = None

    # ── Connection management ────────────────────────────────────────────

    @property
    def conn(self) -> Connection:
        """Return (and lazily create) the cached Fabric Connection."""
        if self._conn is None:
            self._conn = Connection(
                host=self._host,
                user=self._user,
                port=self._port,
                connect_kwargs={"key_filename": str(self._key_path)},
            )
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    # ── Logging helper ───────────────────────────────────────────────────

    def _log(self, line: str) -> None:
        if self._pipeline_log_path is not None:
            self._pipeline_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._pipeline_log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    # ── Command execution ────────────────────────────────────────────────

    def run_command(
        self,
        cmd: str,
        remote_cwd: str,
        log_path: Path,
        module_loads: Optional[list[str]] = None,
        module_use_paths: Optional[list[str]] = None,
        lmod_init: Optional[str] = None,
        env: Optional[dict[str, str]] = None,
        append_log: bool = False,
    ) -> int:
        """Execute *cmd* on the remote host inside *remote_cwd*.

        stdout+stderr are streamed to *log_path* (and *pipeline_log_path*
        if set).  Returns the remote exit code.
        """
        # Build module preamble.
        prefix_parts: list[str] = []
        if module_loads:
            init_path = lmod_init or "/usr/share/lmod/lmod/init/bash"
            prefix_parts.append(f"source {shlex.quote(init_path)}")
            for p in (module_use_paths or []):
                prefix_parts.append(f"module use {shlex.quote(p)}")
            for m in module_loads:
                prefix_parts.append(f"module load {shlex.quote(m)}")

        # Build env-var prefix.
        env_prefix = ""
        if env:
            env_prefix = " ".join(
                f"{k}={shlex.quote(v)}" for k, v in env.items()
            ) + " "

        full_cmd = cmd
        if prefix_parts:
            full_cmd = " && ".join(prefix_parts) + " && " + env_prefix + cmd
        elif env_prefix:
            full_cmd = env_prefix + cmd

        # Wrap in cd.
        wrapped = f"cd {shlex.quote(remote_cwd)} && {full_cmd}"

        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_mode = "a" if append_log else "w"

        header = f"$ [remote:{self._host}] {cmd}\n"
        self._log(f"[remote] {cmd}")

        with log_path.open(log_mode, encoding="utf-8") as log_file:
            log_file.write(header)
            pipeline_file = None
            try:
                if (
                    self._pipeline_log_path is not None
                    and self._pipeline_log_path != log_path
                ):
                    pipeline_file = self._pipeline_log_path.open(
                        "a", encoding="utf-8"
                    )
                tee = _TeeWriter(log_file, pipeline_file)
                result = self.conn.run(
                    wrapped, out_stream=tee, err_stream=tee, hide=True, warn=True
                )
                return result.return_code
            finally:
                if pipeline_file is not None:
                    pipeline_file.close()

    # ── Git operations ───────────────────────────────────────────────────

    def git_clone_or_update(
        self,
        repo_url: str,
        remote_path: str,
        branch: str,
        log_path: Path,
    ) -> bool:
        """Clone *repo_url* to *remote_path* or update if it already exists.

        Returns True on success.
        """
        if self.path_exists(f"{remote_path}/.git"):
            self._log(f"[remote-git] Updating {remote_path} branch={branch}")
            rc_fetch = self.run_command(
                f"git fetch origin {shlex.quote(branch)}",
                remote_cwd=remote_path,
                log_path=log_path,
                append_log=True,
            )
            rc_checkout = self.run_command(
                f"git checkout {shlex.quote(branch)}",
                remote_cwd=remote_path,
                log_path=log_path,
                append_log=True,
            )
            rc_pull = self.run_command(
                f"git pull --ff-only origin {shlex.quote(branch)}",
                remote_cwd=remote_path,
                log_path=log_path,
                append_log=True,
            )
            return rc_fetch == 0 and rc_checkout == 0 and rc_pull == 0
        else:
            parent = str(Path(remote_path).parent)
            self.ensure_dir(parent)
            self._log(
                f"[remote-git] Cloning {repo_url} → {remote_path} branch={branch}"
            )
            rc = self.run_command(
                f"git clone --branch {shlex.quote(branch)} {shlex.quote(repo_url)} {shlex.quote(remote_path)}",
                remote_cwd=parent,
                log_path=log_path,
                append_log=True,
            )
            return rc == 0

    # ── File transfer ────────────────────────────────────────────────────

    def fetch_file(self, remote_path: str, local_path: Path) -> None:
        """Download a single file from the remote via scp.

        Fabric's conn.get() reuses a cached Paramiko SFTP channel that can
        end up in a bad state after run_command() calls that use custom
        out_stream/err_stream objects, causing spurious "Garbage packet
        received" errors with Paramiko 4.x.  Using a subprocess scp call
        creates a completely independent transfer that is unaffected by the
        Fabric connection state.
        """
        local_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "scp",
            "-i", str(self._key_path),
            "-P", str(self._port),
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            f"{self._user}@{self._host}:{remote_path}",
            str(local_path),
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"scp failed (rc={result.returncode}): {stderr}")

    # ── Directory helpers ────────────────────────────────────────────────

    def ensure_dir(self, remote_path: str) -> None:
        """Create a directory (and parents) on the remote."""
        self.conn.run(
            f"mkdir -p {shlex.quote(remote_path)}", hide=True, warn=True
        )

    def path_exists(self, remote_path: str) -> bool:
        """Check whether *remote_path* exists on the remote."""
        result = self.conn.run(
            f"test -e {shlex.quote(remote_path)}", hide=True, warn=True
        )
        return result.return_code == 0

    def cleanup(self, remote_path: str) -> None:
        """Remove *remote_path* on the remote.  Logs warning but does not raise."""
        self._log(f"[remote] Cleaning up {remote_path}")
        result = self.conn.run(
            f"rm -rf {shlex.quote(remote_path)}", hide=True, warn=True
        )
        if result.return_code != 0:
            self._log(
                f"[remote] WARNING: cleanup of {remote_path} returned {result.return_code}"
            )
