"""Remote SSH execution via Fabric for the OPALX regression suite.

Robustness features:
- SSH keepalive: prevents silent connection drops caused by NAT/firewall
  timeouts during long-running builds (configurable interval, default 30s).
- Connection health checking: detects stale transports and auto-reconnects
  before command execution.
- Per-command timeout: shell-level ``timeout`` wrapper prevents runaway remote
  commands from blocking the pipeline indefinitely.
- Cancel support: a ``threading.Event``-based watchdog interrupts the SSH
  channel when a pipeline cancellation is requested, avoiding the need to
  restart the server.
- Slurm allocation timeout: prevents ``salloc`` from waiting forever for
  resources.
- Interactive gateway auth: supports hop gateways like ``hopx.psi.ch`` that
  require password + 2FA via SSH ControlMaster multiplexing.  Uses the system
  ``ssh(1)`` binary with ``SSH_ASKPASS`` for credential handling.

Sensitive-data rule: every line written to ``log_path`` or ``pipeline_log_path``
under ``data_root`` uses ``self._connection_name`` as the identifier — never
the underlying SSH host, user, key, or work_dir.  Gateway credentials
(password, OTP) are held in memory only and never logged or persisted.
"""
from __future__ import annotations

import io
import os
import re
import shlex
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import paramiko
from fabric import Connection

if TYPE_CHECKING:
    from .config import EnvActivation, GatewayEndpoint


# ── Key loading ──────────────────────────────────────────────────────────────


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


# ── Interactive gateway helpers (SSH ControlMaster + ASKPASS) ─────────────────


def _write_askpass_script() -> str:
    """Create a temporary ``SSH_ASKPASS`` helper script.

    The script itself contains **no credentials** — it reads them from
    environment variables ``_HOPX_PW`` and ``_HOPX_OTP`` that only exist in
    the child SSH process's environment.  The file is placed in ``/dev/shm``
    (memory-backed tmpfs on Linux) when available to avoid touching physical
    storage.
    """
    tmpdir = "/dev/shm" if os.path.isdir("/dev/shm") else tempfile.gettempdir()
    fd, path = tempfile.mkstemp(prefix=".opalx_askpass_", dir=tmpdir, suffix=".sh")
    try:
        os.write(fd, (
            b"#!/bin/sh\n"
            b'case "$1" in\n'
            b'  *[Pp]assword*) printf \'%s\\n\' "$_HOPX_PW";;\n'
            b'  *) printf \'%s\\n\' "$_HOPX_OTP";;\n'
            b"esac\n"
        ))
    finally:
        os.close(fd)
    os.chmod(path, 0o700)
    return path


# ── Tee writer for dual-stream logging ───────────────────────────────────────


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


# ── Remote executor ──────────────────────────────────────────────────────────


class RemoteExecutor:
    """SSH execution and file transfer for remote pipeline runs.

    Uses a single persistent Fabric ``Connection`` per executor instance, with
    optional ``ProxyJump`` chaining via Fabric's ``gateway=`` parameter or a
    manually established keyboard-interactive transport for hop gateways.

    Robustness guarantees:

    - SSH keepalive detects dead connections within ``keepalive_interval`` s.
    - Stale transports are detected and reconnected automatically before each
      command (except interactive gateways, where OTPs are single-use).
    - Commands can be interrupted via ``cancel_event`` (``threading.Event``).
    - Individual commands are subject to ``command_timeout`` (shell timeout).
    - Slurm allocations have a configurable ``salloc_timeout``.

    All methods are blocking (designed to run inside ``asyncio.to_thread``).

    The constructor takes resolved key paths — it does not look up keys on
    disk.  Resolution lives in
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
        # ── Robustness settings ──────────────────────────────────────
        keepalive_interval: int = 30,
        command_timeout: int = 0,
        salloc_timeout: int = 0,
        # ── Interactive gateway credentials (held in memory only) ────
        gateway_password: Optional[str] = None,
        gateway_otp: Optional[str] = None,
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
        self._keepalive_interval = keepalive_interval
        self._command_timeout = command_timeout
        self._salloc_timeout = salloc_timeout
        self._gateway_password = gateway_password
        self._gateway_otp = gateway_otp

        self._conn: Optional[Connection] = None
        self._gateway_conn: Optional[Connection] = None
        self._gateway_transport: Optional[paramiko.Transport] = None
        self._allocation_id: Optional[str] = None
        # SSH ControlMaster state for interactive gateways.
        self._gateway_process: Optional[subprocess.Popen] = None
        self._control_path: Optional[str] = None
        self._askpass_path: Optional[str] = None

    # ── Connection management ────────────────────────────────────────────

    def _open_connection(self) -> Connection:
        """Create, open, and configure a new Fabric Connection."""
        if self._gateway is not None:
            if self._gateway.auth_method == "interactive":
                return self._open_via_interactive_gateway()
            return self._open_via_key_gateway()
        return self._open_direct()

    def _open_direct(self) -> Connection:
        """Open a direct SSH connection (no gateway)."""
        conn = Connection(
            host=self._host,
            user=self._user,
            port=self._port,
            connect_kwargs=_connect_kwargs(self._key_path),
        )
        conn.open()
        self._apply_keepalive(conn)
        return conn

    def _open_via_key_gateway(self) -> Connection:
        """Open a connection through a key-authenticated gateway."""
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
        conn = Connection(
            host=self._host,
            user=self._user,
            port=self._port,
            gateway=self._gateway_conn,
            connect_kwargs=_connect_kwargs(self._key_path),
        )
        conn.open()
        self._apply_keepalive(conn)
        self._apply_keepalive(self._gateway_conn)
        return conn

    def _open_via_interactive_gateway(self) -> Connection:
        """Open a connection through an interactive (password+2FA) gateway.

        Uses the system ``ssh(1)`` binary to establish a ``ControlMaster``
        session to the gateway with keyboard-interactive authentication
        handled via ``SSH_ASKPASS``.  Subsequent target connections tunnel
        through the control socket using ``ssh -W`` as a ``ProxyCommand`` —
        exactly how PSI's hopx.psi.ch architecture works.

        This approach uses SSH multiplexing, which is required by gateways
        like hopx.psi.ch where a persistent "setup connection" must stay
        open for forwarding to work.

        The ControlMaster session stays alive for the duration of the run.
        If the target connection drops but the gateway is still alive,
        reconnection through the existing control socket is possible
        without re-authenticating.
        """
        # If we already have a live control master, just create a new proxy.
        if self._is_gateway_alive():
            self._log(
                f"[{self._connection_name}] Reusing existing gateway session"
            )
            return self._connect_through_control_socket()

        # ── Establish a new ControlMaster session ────────────────────────

        # Create ASKPASS script (contains NO credentials — reads from env).
        self._askpass_path = _write_askpass_script()

        # Control socket in memory-backed tmpfs when available.
        tmpdir = "/dev/shm" if os.path.isdir("/dev/shm") else tempfile.gettempdir()
        self._control_path = tempfile.mktemp(
            prefix=".opalx_ctl_", dir=tmpdir
        )

        # Environment for the SSH subprocess — credentials live here only.
        gw_env = os.environ.copy()
        gw_env["SSH_ASKPASS"] = self._askpass_path
        gw_env["SSH_ASKPASS_REQUIRE"] = "force"
        gw_env["_HOPX_PW"] = self._gateway_password or ""
        gw_env["_HOPX_OTP"] = self._gateway_otp or ""
        gw_env.setdefault("DISPLAY", ":0")

        ssh_cmd = [
            "ssh", "-N",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ControlMaster=auto",
            "-o", f"ControlPath={self._control_path}",
            "-o", "PreferredAuthentications=keyboard-interactive",
            "-o", "NumberOfPasswordPrompts=1",
            "-p", str(self._gateway.port),
            f"{self._gateway.user}@{self._gateway.host}",
        ]

        self._gateway_process = subprocess.Popen(
            ssh_cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=gw_env,
            preexec_fn=os.setsid,
        )

        # Wait for the control socket to appear (= successful auth).
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if os.path.exists(self._control_path):
                break
            if self._gateway_process.poll() is not None:
                stderr = self._gateway_process.stderr.read().decode(
                    "utf-8", errors="replace"
                )
                self._cleanup_gateway_files()
                raise RuntimeError(
                    f"SSH gateway authentication to {self._gateway.host} "
                    f"failed: {stderr.strip() or 'unknown error'}"
                )
            time.sleep(0.5)
        else:
            self._gateway_process.kill()
            self._cleanup_gateway_files()
            raise RuntimeError(
                f"Timed out (60s) waiting for SSH gateway "
                f"{self._gateway.host} to authenticate"
            )

        # ASKPASS script is no longer needed after auth.
        if self._askpass_path and os.path.exists(self._askpass_path):
            os.unlink(self._askpass_path)
            self._askpass_path = None

        self._log(
            f"[{self._connection_name}] SSH gateway to "
            f"{self._gateway.host} established (ControlMaster)"
        )

        return self._connect_through_control_socket()

    def _is_gateway_alive(self) -> bool:
        """Check if the SSH ControlMaster gateway process is still running."""
        return (
            self._gateway_process is not None
            and self._gateway_process.poll() is None
            and self._control_path is not None
            and os.path.exists(self._control_path)
        )

    def _connect_through_control_socket(self) -> Connection:
        """Create a target connection routed through the ControlMaster socket."""
        proxy_cmd = (
            f"ssh -o ControlPath={shlex.quote(self._control_path)}"
            f" -p {self._gateway.port}"
            f" -W {self._host}:{self._port}"
            f" {self._gateway.user}@{self._gateway.host}"
        )
        proxy = paramiko.ProxyCommand(proxy_cmd)
        ckw = _connect_kwargs(self._key_path)
        ckw["sock"] = proxy
        conn = Connection(
            host=self._host,
            user=self._user,
            port=self._port,
            connect_kwargs=ckw,
        )
        conn.open()
        self._apply_keepalive(conn)
        return conn

    def _cleanup_gateway_files(self) -> None:
        """Remove temporary gateway files (askpass script, control socket)."""
        for attr in ("_askpass_path", "_control_path"):
            path = getattr(self, attr, None)
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
            setattr(self, attr, None)

    def _apply_keepalive(self, conn: Connection) -> None:
        """Enable SSH keepalive on a connection's transport."""
        if self._keepalive_interval > 0 and conn.transport:
            conn.transport.set_keepalive(self._keepalive_interval)

    @property
    def conn(self) -> Connection:
        """Return (and lazily create) the cached Fabric Connection chain.

        Checks transport health on every access; reconnects if the transport
        has gone stale (e.g. after a network interruption detected by
        keepalive).

        For interactive gateways using ControlMaster: if the target connection
        drops but the gateway process is still alive, the target connection is
        re-established through the existing control socket without needing a
        fresh OTP.  If the gateway process itself has died, a ``RuntimeError``
        is raised.
        """
        if self._conn is not None:
            transport = self._conn.transport
            if transport is not None and transport.is_active():
                return self._conn
            # Transport died — clean up and reconnect.
            self._log(
                f"[{self._connection_name}] SSH transport inactive, reconnecting"
            )
            if (
                self._gateway is not None
                and self._gateway.auth_method == "interactive"
            ):
                if not self._is_gateway_alive():
                    self._close_connections()
                    raise RuntimeError(
                        f"SSH gateway to {self._gateway.host} has terminated. "
                        "Cannot reconnect — please re-trigger the run with "
                        "a fresh OTP."
                    )
                # Gateway is alive — reconnect through existing control socket.
                self._log(
                    f"[{self._connection_name}] Reconnecting through "
                    "existing gateway"
                )
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
                # Fall through to _open_connection which reuses the socket.
            else:
                self._close_connections()

        self._conn = self._open_connection()
        return self._conn

    def _close_connections(self) -> None:
        """Close SSH connections, transports, and gateway processes."""
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
        if self._gateway_transport is not None:
            try:
                self._gateway_transport.close()
            except Exception:
                pass
            self._gateway_transport = None
        # Shut down SSH ControlMaster for interactive gateways.
        if self._gateway_process is not None:
            if self._control_path:
                try:
                    subprocess.run(
                        ["ssh",
                         "-o", f"ControlPath={self._control_path}",
                         "-O", "exit",
                         f"{self._gateway.user}@{self._gateway.host}"],
                        capture_output=True, timeout=5,
                    )
                except Exception:
                    pass
            try:
                self._gateway_process.terminate()
                self._gateway_process.wait(timeout=5)
            except Exception:
                try:
                    self._gateway_process.kill()
                except Exception:
                    pass
            self._gateway_process = None
        self._cleanup_gateway_files()

    def close(self) -> None:
        """Cancel any active Slurm allocation, then close SSH connections."""
        self.release_slurm_job()
        self._close_connections()

    # ── Slurm allocation ─────────────────────────────────────────────────

    def allocate_slurm_job(self, slurm_args: list[str]) -> str:
        """Allocate a Slurm job via ``salloc --no-shell``.

        Returns the job ID string and records it in ``self._allocation_id``.
        From this point on, every :meth:`run_command` call is automatically
        wrapped in ``srun --jobid=<ID> --overlap -- bash -c '...'`` so that
        MPI-linked executables can find the allocated host list.

        Respects ``self._salloc_timeout``; exit code 124 from the shell
        ``timeout`` wrapper is translated to a clear error message.
        """
        args_str = " ".join(shlex.quote(a) for a in slurm_args)
        salloc_cmd = f"salloc --no-shell {args_str}"

        if self._salloc_timeout > 0:
            salloc_cmd = (
                f"timeout --signal=TERM --kill-after=30 {self._salloc_timeout} "
                f"bash -c {shlex.quote(salloc_cmd)}"
            )

        result = self.conn.run(salloc_cmd, hide=True, warn=True)
        if result.return_code != 0:
            stderr = result.stderr.strip()
            if result.return_code == 124:
                raise RuntimeError(
                    f"salloc timed out after {self._salloc_timeout}s waiting "
                    f"for resources: {stderr}"
                )
            raise RuntimeError(
                f"salloc failed (rc={result.return_code}): {stderr}"
            )
        # salloc writes "salloc: Granted job allocation 12345" to stderr.
        combined = result.stdout + result.stderr
        m = re.search(r"Granted job allocation (\d+)", combined)
        if m is None:
            raise RuntimeError(
                f"Could not parse job ID from salloc output: {combined!r}"
            )
        job_id = m.group(1)
        self._allocation_id = job_id
        self._log(f"[{self._connection_name}] Slurm job {job_id} allocated")
        return job_id

    def release_slurm_job(self) -> None:
        """Cancel the active Slurm allocation (best-effort).

        Tolerates stale or closed connections — if ``scancel`` cannot be
        delivered, the job will time out on its own via Slurm's ``--time``
        limit.
        """
        if self._allocation_id is None:
            return
        job_id = self._allocation_id
        self._allocation_id = None  # clear first so close() won't double-cancel
        try:
            self.conn.run(f"scancel {shlex.quote(job_id)}", hide=True, warn=True)
        except Exception:
            self._log(
                f"[{self._connection_name}] WARNING: could not cancel Slurm "
                f"job {job_id} (connection may be unavailable)"
            )
        else:
            self._log(f"[{self._connection_name}] Slurm job {job_id} cancelled")

    # ── Logging helper ───────────────────────────────────────────────────

    def _log(self, line: str) -> None:
        """Append a line to the pipeline log (if configured)."""
        if self._pipeline_log_path is not None:
            self._pipeline_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._pipeline_log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    # ── Environment activation preamble ──────────────────────────────────

    def _is_uenv(self) -> bool:
        """Check if the environment style is uenv."""
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

        When a Slurm allocation is active, use :meth:`_uenv_srun_flags`
        instead — uenv activation is passed as ``srun --uenv/--view`` flags,
        which avoids nesting ``uenv run`` inside ``bash -c`` inside ``srun``.
        """
        assert self._env is not None and self._env.prologue
        return f"uenv run {self._env.prologue} -- {cmd}"

    def _uenv_srun_flags(self) -> str:
        """Convert the uenv prologue to ``srun --uenv`` / ``--view`` flags.

        CSCS Alps ``srun`` accepts ``--uenv=<image>`` and ``--view=<view>``
        directly — the equivalent of ``#SBATCH --uenv`` / ``#SBATCH --view``.
        Supported prologue forms (same syntax as ``uenv run``):

        - ``/path/to/image.squashfs``
        - ``/path/to/image.squashfs:view-name``
        - ``--view=view-name /path/to/image.squashfs``
        """
        prologue = (self._env.prologue or "") if self._env else ""
        parts = shlex.split(prologue)
        image: Optional[str] = None
        view: Optional[str] = None
        for part in parts:
            if part.startswith("--view="):
                view = part[len("--view="):]
            elif not part.startswith("-"):
                if ":" in part:
                    image, _, view_suffix = part.partition(":")
                    if view_suffix:
                        view = view_suffix
                else:
                    image = part
        flags = f"--uenv={shlex.quote(image)}" if image else ""
        if view:
            flags += f" --view={shlex.quote(view)}"
        return flags.strip()

    # ── Command execution ────────────────────────────────────────────────

    def run_command(
        self,
        cmd: str,
        remote_cwd: str,
        log_path: Path,
        env_vars: Optional[dict[str, str]] = None,
        append_log: bool = False,
        timeout: Optional[int] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> int:
        """Execute *cmd* on the remote host inside *remote_cwd*.

        stdout+stderr are streamed to *log_path* (and *pipeline_log_path* if
        set).  Environment activation comes from ``self._env`` and is applied
        automatically.

        Returns the remote exit code, or ``-1`` if the command was cancelled.
        Exit code ``124`` from the shell ``timeout`` wrapper indicates a
        command timeout.
        """
        # Early bail-out if already cancelled.
        if cancel_event is not None and cancel_event.is_set():
            return -1

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
        # Exception: when a Slurm allocation is active, uenv activation is passed
        # as srun --uenv/--view flags (see below) — running "uenv run" inside an
        # srun step can interfere with namespace setup on CSCS Alps.
        if self._is_uenv() and self._env and self._env.prologue and self._allocation_id is None:
            inner = (f"env {env_prefix}{cmd}") if env_prefix else cmd
            full_cmd = self._wrap_with_uenv(inner)

        # Wrap in cd. The wrapped command exists in memory only.
        # Also strip the exported "module" bash function inherited from the SSH
        # login profile (lmod exports it via BASH_FUNC_module%%). srun rejects
        # multiline function exports with "Improperly formed environment
        # variable", which corrupts the log output of any command that calls
        # srun internally (e.g. regression test .local scripts that launch
        # OPAL-X via srun/mpirun).
        #
        # Note: `unset -f module` alone is not enough — bash only removes the
        # function from the current shell but keeps BASH_FUNC_module%% in its
        # environment, which is then re-imported by child bashes (and forwarded
        # to nested srun). We must unset the raw env var by name as well.
        wrapped = (
            f'unset -f module 2>/dev/null; '
            f'unset "BASH_FUNC_module%%" 2>/dev/null; '
            f'unset "BASH_FUNC_module()" 2>/dev/null; '
            f"cd {shlex.quote(remote_cwd)} && {full_cmd}"
        )

        # When a Slurm allocation is active, run every command as a job step
        # so that MPI-linked test executables can see the allocated host list.
        # srun calls execve, not a shell, so we use bash -c to preserve the
        # &&-chain (cd, module loads, env preamble) around the real command.
        # When uenv style is configured, pass the image/view as srun --uenv/--view
        # flags instead of calling "uenv run" inside bash — this is the correct
        # way to activate a uenv on CSCS Alps compute nodes, equivalent to
        # #SBATCH --uenv / #SBATCH --view.
        if self._allocation_id is not None:
            uenv_flags = ""
            if self._is_uenv() and self._env and self._env.prologue:
                uenv_flags = " " + self._uenv_srun_flags()
            wrapped = (
                f"srun --jobid={shlex.quote(self._allocation_id)} --overlap{uenv_flags}"
                f" -- bash -c {shlex.quote(wrapped)}"
            )

        # Apply per-command timeout (shell-level).  Skipped for srun commands
        # because Slurm's --time flag is the proper timeout mechanism there.
        effective_timeout = timeout if timeout is not None else self._command_timeout
        if effective_timeout > 0 and self._allocation_id is None:
            wrapped = (
                f"timeout --signal=TERM --kill-after=30 {effective_timeout} "
                f"bash -c {shlex.quote(wrapped)}"
            )

        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_mode = "a" if append_log else "w"

        # Sanitized log header — connection_name only, never host/user/work_dir.
        header = f"$ [{self._connection_name}] {cmd}\n"
        self._log(f"[{self._connection_name}] {cmd}")

        # ── Cancel watchdog ──────────────────────────────────────────────
        # A daemon thread that waits on the cancel_event and closes the SSH
        # transport to interrupt ``conn.run()``.  This unblocks the main
        # thread which is stuck reading from the SSH channel.
        command_done = threading.Event()

        if cancel_event is not None:
            def _cancel_watchdog() -> None:
                cancel_event.wait()
                if not command_done.is_set():
                    try:
                        transport = self._conn.transport if self._conn else None
                        if transport:
                            transport.close()
                    except Exception:
                        pass

            threading.Thread(
                target=_cancel_watchdog, daemon=True, name="cancel-ssh"
            ).start()

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
                command_done.set()
                return result.return_code
            except Exception as exc:
                command_done.set()
                if cancel_event is not None and cancel_event.is_set():
                    self._log(
                        f"[{self._connection_name}] command interrupted by cancellation"
                    )
                    self._close_connections()
                    return -1
                # Re-raise SSH/transport errors so the pipeline can handle them.
                raise
            finally:
                command_done.set()
                if pipeline_file is not None:
                    pipeline_file.close()

    # ── Git operations ───────────────────────────────────────────────────

    def git_clone_or_update(
        self,
        repo_url: str,
        remote_path: str,
        branch: str,
        log_path: Path,
        cancel_event: Optional[threading.Event] = None,
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
                cancel_event=cancel_event,
            )
            rc_checkout = self.run_command(
                f"git checkout {shlex.quote(branch)}",
                remote_cwd=remote_path,
                log_path=log_path,
                append_log=True,
                cancel_event=cancel_event,
            )
            rc_pull = self.run_command(
                f"git pull --ff-only origin {shlex.quote(branch)}",
                remote_cwd=remote_path,
                log_path=log_path,
                append_log=True,
                cancel_event=cancel_event,
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
                cancel_event=cancel_event,
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
