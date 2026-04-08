"""Remote SSH execution via Fabric for the OPALX regression suite.

Sensitive-data rule: every line written to ``log_path`` or ``pipeline_log_path``
under ``data_root`` uses ``self._connection_name`` as the identifier — never
the underlying SSH host, user, key, or work_dir. The fully-wrapped command
(``cd <work_dir> && source <init> && module load ... && <cmd>``) is built in
memory only; only the user-meaningful ``cmd`` and the streamed stdout/stderr
ever touch a log file.
"""
from __future__ import annotations

import io
import shlex
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import paramiko
from fabric import Connection

if TYPE_CHECKING:
    from .config import EnvActivation, GatewayEndpoint


def _load_pkey(key_path: Path) -> paramiko.PKey:
    """Load a private key from *key_path*, trying all supported key types.

    Using ``pkey=`` instead of ``key_filename=`` avoids a known Paramiko quirk
    where the internal type-guessing loop silently skips newer OpenSSH-format
    Ed25519 keys and falls through to ``AuthenticationException`` with no
    diagnostic information.  Loading explicitly surfaces key-format errors at
    load time with a clear message.

    If a certificate file ``<key_stem>-cert.pub`` exists next to the private
    key (e.g. CSCS-style certificate-based auth), it is attached to the key
    object automatically so Paramiko offers the cert identity during auth —
    exactly what OpenSSH does when it finds ``<name>-cert.pub`` alongside
    ``<name>`` in ``~/.ssh/``.
    """
    key: paramiko.PKey | None = None
    for key_cls in (
        paramiko.Ed25519Key,
        paramiko.RSAKey,
        paramiko.ECDSAKey,
    ):
        try:
            key = key_cls.from_private_key_file(str(key_path))
            break
        except (paramiko.SSHException, ValueError):
            continue
    if key is None:
        raise ValueError(
            f"Could not load SSH private key from {key_path}: "
            "unrecognised format or unsupported key type."
        )
    # Auto-load companion certificate if present (e.g. cscs-key-cert.pub).
    cert_path = key_path.parent / (key_path.stem + "-cert.pub")
    if cert_path.is_file():
        key.load_certificate(str(cert_path))
    return key


def _connect_kwargs(key_path: Path) -> dict:
    """Build Fabric/Paramiko connect_kwargs for a single SSH leg.

    - ``pkey``: pre-loaded key object — avoids the ``key_filename`` type-guessing
      loop that silently fails for newer OpenSSH-format Ed25519 keys.
    - ``allow_agent=False``: do not query the ssh-agent (IdentitiesOnly equivalent).
    - ``look_for_keys=False``: do not scan ~/.ssh/id_* fallback files.
    - ``banner_timeout=60``: CSCS and similar HPC front-ends can take several
      seconds to emit the SSH banner; Paramiko's default of 15 s is too short.
    - ``auth_timeout=60``: same reasoning — give the server time to complete
      the public-key challenge exchange.
    - ``timeout=30``: TCP connect timeout.
    """
    return {
        "pkey": _load_pkey(key_path),
        "allow_agent": False,
        "look_for_keys": False,
        "banner_timeout": 60,
        "auth_timeout": 60,
        "timeout": 30,
    }


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

    Uses a single persistent Fabric ``Connection`` per executor instance, with
    optional ``ProxyJump`` chaining via Fabric's ``gateway=`` parameter. All
    methods are blocking (designed to run inside ``asyncio.to_thread``).

    The constructor takes resolved key paths — it does not look up keys on
    disk. Resolution lives in
    :func:`modern_opalx_regsuite.user_store.resolve_connection_key_paths`.
    """

    def __init__(
        self,
        host: str,
        user: str,
        key_path: Path,
        port: int = 22,
        connection_name: str = "remote",
        gateway: Optional["GatewayEndpoint"] = None,
        gateway_key_path: Optional[Path] = None,
        env: Optional["EnvActivation"] = None,
        pipeline_log_path: Optional[Path] = None,
    ) -> None:
        self._host = host
        self._user = user
        self._key_path = key_path
        self._port = port
        self._connection_name = connection_name
        self._gateway = gateway
        self._gateway_key_path = gateway_key_path
        self._env = env
        self._pipeline_log_path = pipeline_log_path
        self._conn: Optional[Connection] = None
        self._gateway_conn: Optional[Connection] = None

    # ── Connection management ────────────────────────────────────────────

    @property
    def conn(self) -> Connection:
        """Return (and lazily create) the cached Fabric Connection chain."""
        if self._conn is None:
            gw_conn: Optional[Connection] = None
            if self._gateway is not None:
                if self._gateway_key_path is None:
                    raise ValueError(
                        "RemoteExecutor: gateway is set but gateway_key_path is None"
                    )
                self._gateway_conn = Connection(
                    host=self._gateway.host,
                    user=self._gateway.user,
                    port=self._gateway.port,
                    connect_kwargs=_connect_kwargs(self._gateway_key_path),
                )
                gw_conn = self._gateway_conn

            self._conn = Connection(
                host=self._host,
                user=self._user,
                port=self._port,
                gateway=gw_conn,
                connect_kwargs=_connect_kwargs(self._key_path),
            )
        return self._conn

    def close(self) -> None:
        """Close the target connection, then the gateway. Fabric does not cascade."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        if self._gateway_conn is not None:
            try:
                self._gateway_conn.close()
            except Exception:
                pass
            self._gateway_conn = None

    # ── Logging helper ───────────────────────────────────────────────────

    def _log(self, line: str) -> None:
        if self._pipeline_log_path is not None:
            self._pipeline_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._pipeline_log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    # ── Environment activation preamble ──────────────────────────────────

    def _is_uenv(self) -> bool:
        return self._env is not None and self._env.style == "uenv"

    def _build_env_preamble(self) -> list[str]:
        """Return shell statements that activate the connection's env (prefix styles only).

        Returns an empty list for ``none``, ``uenv`` (handled separately as a
        wrapper in ``run_command``), and when no env is configured.  The result
        is joined into the in-memory wrapped command — never written to a log
        file under ``data_root``.
        """
        env = self._env
        if env is None or env.style in ("none", "uenv"):
            return []
        if env.style == "prologue":
            return [env.prologue] if env.prologue else []
        if env.style == "modules":
            init_path = env.lmod_init or "/usr/share/lmod/lmod/init/bash"
            parts = [f"source {shlex.quote(init_path)}"]
            for p in env.module_use_paths:
                parts.append(f"module use {shlex.quote(p)}")
            for m in env.module_loads:
                parts.append(f"module load {shlex.quote(m)}")
            return parts
        return []

    def _wrap_with_uenv(self, cmd: str) -> str:
        """Wrap *cmd* with ``uenv run <prologue> -- <cmd>``.

        ``uenv start`` is an interactive-shell command that fails in
        non-interactive SSH sessions.  ``uenv run`` is the correct alternative
        for scripted use — it executes a single command inside the uenv and
        exits, exactly like ``docker run``.

        ``self._env.prologue`` holds the arguments between ``uenv run`` and
        ``--``, e.g. ``--view=develop /path/to/image.squashfs``.
        """
        assert self._env is not None and self._env.prologue
        return f"uenv run {self._env.prologue} -- {cmd}"

    # ── Command execution ────────────────────────────────────────────────

    def run_command(
        self,
        cmd: str,
        remote_cwd: str,
        log_path: Path,
        env_vars: Optional[dict[str, str]] = None,
        append_log: bool = False,
    ) -> int:
        """Execute *cmd* on the remote host inside *remote_cwd*.

        stdout+stderr are streamed to *log_path* (and *pipeline_log_path* if
        set). Environment activation comes from ``self._env`` and is applied
        automatically. Returns the remote exit code.
        """
        prefix_parts = self._build_env_preamble()

        # Inline shell env-var assignment, e.g. ``OMP_NUM_THREADS=4 cmd``.
        env_prefix = ""
        if env_vars:
            env_prefix = " ".join(
                f"{k}={shlex.quote(v)}" for k, v in env_vars.items()
            ) + " "

        full_cmd = cmd
        if prefix_parts:
            full_cmd = " && ".join(prefix_parts) + " && " + env_prefix + cmd
        elif env_prefix:
            full_cmd = env_prefix + cmd

        # uenv style: wrap the whole thing (including env vars) with uenv run.
        # uenv run uses execve, not a shell — VAR=value cmd shell syntax does not
        # work.  Use env(1) to carry the variable assignments instead.
        if self._is_uenv() and self._env and self._env.prologue:
            inner = (f"env {env_prefix}{cmd}") if env_prefix else cmd
            full_cmd = self._wrap_with_uenv(inner)

        # Wrap in cd. The wrapped command exists in memory only.
        wrapped = f"cd {shlex.quote(remote_cwd)} && {full_cmd}"

        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_mode = "a" if append_log else "w"

        # Sanitized log header — connection_name only, never host/user/work_dir.
        header = f"$ [{self._connection_name}] {cmd}\n"
        self._log(f"[{self._connection_name}] {cmd}")

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
            self._log(f"[{self._connection_name}] git update {branch}")
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
            self._log(f"[{self._connection_name}] git clone {branch}")
            rc = self.run_command(
                f"git clone --branch {shlex.quote(branch)} {shlex.quote(repo_url)} {shlex.quote(remote_path)}",
                remote_cwd=parent,
                log_path=log_path,
                append_log=True,
            )
            return rc == 0

    # ── File transfer ────────────────────────────────────────────────────

    def fetch_file(self, remote_path: str, local_path: Path) -> None:
        """Download a single file from the remote via a fresh SFTP channel.

        Uses paramiko.SFTPClient.from_transport() directly instead of
        conn.get(), for two reasons:
        - Fabric 3.x caches the SFTP client and it can become stale after
          run_command() calls that use custom out_stream/err_stream objects,
          causing "Garbage packet received" with Paramiko 4.x.
        - subprocess scp invokes the remote shell, which on this host prints
          "Loaded opalx module" even for non-interactive sessions, corrupting
          the scp protocol handshake.
        The SFTP subsystem is launched by OpenSSH directly (not via the user's
        shell), so shell startup output does not affect it.
        """
        local_path.parent.mkdir(parents=True, exist_ok=True)
        sftp = paramiko.SFTPClient.from_transport(self.conn.transport)
        try:
            sftp.get(remote_path, str(local_path))
        finally:
            sftp.close()

    # ── Directory helpers ────────────────────────────────────────────────

    def ensure_dir(self, remote_path: str) -> None:
        """Create a directory (and parents) on the remote.

        Bypasses ``self._env`` since ``mkdir -p`` only needs coreutils.
        """
        self.conn.run(
            f"mkdir -p {shlex.quote(remote_path)}", hide=True, warn=True
        )

    def path_exists(self, remote_path: str) -> bool:
        """Check whether *remote_path* exists on the remote.

        Bypasses ``self._env`` since ``test -e`` is a bash builtin.
        """
        result = self.conn.run(
            f"test -e {shlex.quote(remote_path)}", hide=True, warn=True
        )
        return result.return_code == 0

    def cleanup(self, remote_path: str) -> None:
        """Remove *remote_path* on the remote.  Logs warning but does not raise."""
        self._log(f"[{self._connection_name}] cleanup {remote_path}")
        result = self.conn.run(
            f"rm -rf {shlex.quote(remote_path)}", hide=True, warn=True
        )
        if result.return_code != 0:
            self._log(
                f"[{self._connection_name}] WARNING: cleanup returned {result.return_code}"
            )

    # ── Smoke test (used by /api/settings/connections/{name}/test) ───────

    def whoami(self) -> str:
        """Run ``whoami`` on the remote and return its stdout (stripped).

        This is the authoritative connection test — it exercises the entire
        SSH chain (gateway included) and validates auth, but does **not**
        apply ``self._env`` (it's a transport-only check).
        """
        result = self.conn.run("whoami", hide=True, warn=True)
        if result.return_code != 0:
            raise RuntimeError(
                f"whoami exit={result.return_code} stderr={result.stderr.strip()}"
            )
        return result.stdout.strip()
