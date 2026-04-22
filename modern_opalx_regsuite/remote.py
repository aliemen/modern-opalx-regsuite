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
  require password + 2FA.  Uses a Paramiko Transport directly to authenticate
  via keyboard-interactive (password + TOTP/OTP), then opens a
  ``direct-tcpip`` channel to the target host — no system ``ssh`` binary,
  no ControlMaster socket, no ProxyCommand subprocess needed.

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
import pexpect
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


# ── ssh -W socket wrapper ───────────────────────────────────────────────────


class _StdioForward:
    """Socket-like wrapper around an ``ssh -W`` subprocess's stdin/stdout.

    ``paramiko.ProxyCommand`` has two bugs that make it unreliable with
    ControlMaster pipes:

    1. ``recv()`` loops until *exactly* ``size`` bytes are read, instead
       of returning as soon as *any* data is available (the standard
       ``socket.recv`` contract).  On a tunnel where chunks arrive
       incrementally this causes unnecessary blocking.
    2. When ``os.read`` returns 0 (EOF), the loop busy-spins until the
       timeout fires instead of raising immediately.

    This wrapper fixes both by returning partial reads immediately and
    raising ``OSError`` on EOF.  It also flushes ``stdin`` after every
    write.
    """

    def __init__(
        self,
        proc: "subprocess.Popen[bytes]",
        initial_data: bytes = b"",
    ) -> None:
        self._proc = proc
        self._buf = initial_data
        self._timeout: float | None = None

    # ── socket-like interface expected by Paramiko ───────────────────

    def send(self, data: bytes) -> int:
        self._proc.stdin.write(data)
        self._proc.stdin.flush()
        return len(data)

    def recv(self, size: int) -> bytes:
        # Return buffered bytes first (from the pre-flight read).
        if self._buf:
            chunk = self._buf[:size]
            self._buf = self._buf[size:]
            return chunk

        from select import select as _sel
        r, _, _ = _sel([self._proc.stdout], [], [], self._timeout)
        if not r:
            raise socket.timeout()
        data = os.read(self._proc.stdout.fileno(), size)
        if not data:
            raise OSError("ssh -W tunnel closed")
        return data

    def close(self) -> None:
        try:
            self._proc.kill()
        except Exception:
            pass

    def settimeout(self, timeout: float | None) -> None:
        self._timeout = timeout

    @property
    def closed(self) -> bool:
        return self._proc.returncode is not None

    # Paramiko checks ._closed in a few places.
    @property
    def _closed(self) -> bool:
        return self.closed


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
        # pexpect child process that holds the primary ControlMaster session
        # to the interactive gateway (hop-ng requires this to stay open).
        self._gateway_process: Optional[pexpect.spawn] = None
        self._control_path: Optional[str] = None
        # ssh -W subprocess and its socket wrapper (used for the target tunnel).
        self._tunnel_proc: Optional[subprocess.Popen] = None
        self._allocation_id: Optional[str] = None
        self._slurm_cluster: Optional[str] = None

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
        self._log(f"[{self._connection_name}] Connection to {self._host} established.")
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
        self._log(f"[{self._connection_name}] Connection to {self._host} established.")
        return conn

    def _open_via_interactive_gateway(self, _stale_retry: bool = False) -> Connection:
        """Open a connection through PSI's hop-ng interactive gateway.

        PSI's hop-ng does NOT support standard ProxyJump / direct-tcpip from
        a fresh connection.  It requires a persistent PRIMARY session (an
        actual SSH shell session, not ``-N``) that registers a NAT forwarding
        slot on the gateway.  Only while that session is open can additional
        connections reach internal PSI hosts.

        Architecture (ControlMaster):
        1. pexpect spawns ``ssh -o ControlMaster=yes`` **without** ``-N``,
           so a real session channel is opened and the hop-ng forced command
           runs.
        2. pexpect handles the two-round keyboard-interactive auth
           (password → server failure-with-continue → OTP).
        3. We wait for the gateway's final banner line ("no other commands
           available!") which confirms the NAT forwarding slot is active.
        4. The ControlMaster socket is now ready.
        5. Paramiko uses ``ssh -o ControlMaster=auto -W target:port`` as a
           ProxyCommand, piggybacking on the live ControlMaster session.
           Because that session has an active shell channel, the gateway
           accepts the direct-tcpip forwarding request.

        On reconnect (target dropped, gateway still alive), step 5 is
        repeated without a new OTP.
        """
        if self._is_gateway_alive():
            self._log(
                f"[{self._connection_name}] Reusing existing gateway session"
            )
            conn = self._connect_through_control_socket()
            self._log(
                f"[{self._connection_name}] Connection to {self._host} established."
            )
            return conn

        # ── Establish a new primary session via pexpect ──────────────────
        self._control_path = tempfile.mktemp(
            prefix=".opalx_ctl_", dir=tempfile.gettempdir()
        )

        child = pexpect.spawn(
            "ssh",
            [
                "-o", "StrictHostKeyChecking=accept-new",
                "-o", "ControlMaster=yes",
                "-o", f"ControlPath={self._control_path}",
                "-o", "PreferredAuthentications=keyboard-interactive",
                "-p", str(self._gateway.port),
                f"{self._gateway.user}@{self._gateway.host}",
            ],
            timeout=60,
            encoding="utf-8",
        )
        self._gateway_process = child

        try:
            # ── Round 1: password ─────────────────────────────────────────
            idx = child.expect([
                r"[Pp]assword\s*:",
                r"[Pp]ermission\s+[Dd]enied",
                pexpect.EOF,
                pexpect.TIMEOUT,
            ])
            if idx != 0:
                raise RuntimeError(
                    f"No password prompt from {self._gateway.host}; "
                    f"output: {(child.before or '').strip()!r}"
                )
            child.sendline(self._gateway_password or "")

            # ── Round 2: OTP ──────────────────────────────────────────────
            # Server replies with MSG_USERAUTH_FAILURE + "can continue:
            # keyboard-interactive", then immediately sends the OTP prompt.
            idx = child.expect([
                r"[Vv]erification\s+[Cc]ode",
                r"[Mm]icrosoft\s+verification",
                r"[Ee]nter\s+[Yy]our\s+Microsoft",
                r"[Pp]ermission\s+[Dd]enied",
                pexpect.EOF,
                pexpect.TIMEOUT,
            ])
            if idx >= 3:
                raise RuntimeError(
                    f"Gateway auth failed after password: "
                    f"{(child.before or '').strip()!r}"
                )
            child.sendline(self._gateway_otp or "")
            self._log(
                f"[{self._connection_name}] Gateway credentials sent, "
                "waiting for forwarding slot..."
            )

            # ── Wait for forwarding slot ───────────────────────────────────
            # The forced command prints the welcome banner ending with
            # "no other commands available!" — only after this line is the
            # NAT forwarding slot guaranteed to be active.
            #
            # hop-ng may instead ask to disconnect a stale session from a
            # different IP — answer "Y" and wait for the normal banner.
            idx = child.expect([
                r"no other commands available",           # 0 — normal success
                r"\(Y\)es or \(N\)o",                    # 1 — stale-session prompt
                r"[Pp]ermission\s+[Dd]enied",            # 2
                pexpect.EOF,                              # 3
                pexpect.TIMEOUT,                          # 4
            ], timeout=30)
            if idx == 1:
                # Stale session from another IP — agree to disconnect it.
                self._log(
                    f"[{self._connection_name}] hop-ng asked to disconnect "
                    "stale session — answering Y"
                )
                child.sendline("Y")
                # Now wait for the normal banner after the old session is torn down.
                idx = child.expect([
                    r"no other commands available",
                    pexpect.EOF,
                    pexpect.TIMEOUT,
                ], timeout=30)
                if idx != 0:
                    # hop-ng closed the connection after terminating the stale
                    # session.  This is expected on some versions: the
                    # forwarding slot is freed and the client must re-request
                    # it with a fresh connection.  Clean up and retry once —
                    # the stale session is now gone so the second attempt
                    # should succeed without hitting the Y/N prompt again.
                    child.close(force=True)
                    self._gateway_process = None
                    self._cleanup_gateway_files()
                    if _stale_retry:
                        raise RuntimeError(
                            f"Gateway session on {self._gateway.host} did not "
                            f"establish after reconnecting post-stale-disconnect: "
                            f"{(child.before or '').strip()!r}"
                        )
                    self._log(
                        f"[{self._connection_name}] hop-ng closed connection "
                        "after terminating stale session — reconnecting..."
                    )
                    return self._open_via_interactive_gateway(_stale_retry=True)
            elif idx != 0:
                raise RuntimeError(
                    f"Gateway session on {self._gateway.host} did not "
                    f"establish: {(child.before or '').strip()!r}"
                )

        except pexpect.TIMEOUT:
            child.close(force=True)
            self._gateway_process = None
            self._cleanup_gateway_files()
            raise RuntimeError(
                f"Timed out waiting for gateway session on "
                f"{self._gateway.host}"
            )
        except RuntimeError:
            child.close(force=True)
            self._gateway_process = None
            self._cleanup_gateway_files()
            raise

        # Drain ALL remaining banner output (Username, NAT-IP, Sessionend,
        # etc.) so the pexpect PTY buffer is clear and the SSH process is
        # fully in its idle-wait state.
        try:
            child.expect(pexpect.TIMEOUT, timeout=3)
        except pexpect.TIMEOUT:
            pass

        # ControlMaster socket should exist by now; wait up to 10 s.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if os.path.exists(self._control_path):
                break
            if not child.isalive():
                self._gateway_process = None
                self._cleanup_gateway_files()
                raise RuntimeError(
                    f"Gateway SSH process exited unexpectedly after session "
                    f"was established"
                )
            time.sleep(0.2)
        else:
            child.close(force=True)
            self._gateway_process = None
            self._cleanup_gateway_files()
            raise RuntimeError(
                f"ControlMaster socket not created for {self._gateway.host}"
            )

        # Verify the ControlMaster is accepting multiplex requests.
        ctl_check = subprocess.run(
            [
                "ssh",
                "-o", f"ControlPath={self._control_path}",
                "-O", "check",
                f"{self._gateway.user}@{self._gateway.host}",
            ],
            capture_output=True, timeout=5,
        )
        if ctl_check.returncode != 0:
            stderr = ctl_check.stderr.decode(errors="replace").strip()
            self._log(
                f"[{self._connection_name}] ControlMaster check failed: {stderr}"
            )

        self._log(
            f"[{self._connection_name}] Gateway {self._gateway.host} "
            "primary session established (ControlMaster ready)"
        )
        conn = self._connect_through_control_socket()
        self._log(
            f"[{self._connection_name}] Connection to {self._host} established."
        )
        return conn

    def _connect_through_control_socket(self) -> Connection:
        """Connect to the target via ``ssh -W`` through the ControlMaster.

        Uses ``mux_client_request_stdio_fwd`` (the ``-W`` multiplex
        request), which opens a ``direct-tcpip`` forwarding channel — NOT a
        session channel.  This is critical for PSI's hop-ng gateway which
        allows only one session per connection.

        A custom ``_StdioForward`` socket wrapper drives the subprocess
        instead of ``paramiko.ProxyCommand``, which has buffering bugs that
        cause timeouts on ControlMaster pipes.
        """
        self._kill_tunnel()

        proc = subprocess.Popen(
            [
                "ssh",
                "-o", "ControlMaster=auto",
                "-o", f"ControlPath={self._control_path}",
                "-o", "BatchMode=yes",
                "-W", f"{self._host}:{self._port}",
                f"{self._gateway.user}@{self._gateway.host}",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self._tunnel_proc = proc

        # Verify the tunnel is alive by waiting for the target's SSH banner
        # (e.g. "SSH-2.0-OpenSSH_8.0") to appear on stdout.
        import select as _select
        r, _, _ = _select.select([proc.stdout], [], [], 15)
        if not r:
            proc.kill()
            stderr = proc.stderr.read().decode(errors="replace")
            self._tunnel_proc = None
            raise RuntimeError(
                f"ssh -W tunnel to {self._host}:{self._port} produced "
                f"no output in 15 s.  stderr: {stderr}"
            )
        # Peek at stdout to confirm data is flowing — don't consume it,
        # Paramiko needs the full banner.  os.read is non-blocking here
        # because select said it's ready.
        first = os.read(proc.stdout.fileno(), 64)
        if not first:
            proc.kill()
            stderr = proc.stderr.read().decode(errors="replace")
            self._tunnel_proc = None
            raise RuntimeError(
                f"ssh -W tunnel to {self._host}:{self._port} closed "
                f"immediately.  stderr: {stderr}"
            )

        # Build a socket wrapper that feeds the already-read bytes first,
        # then continues reading from the subprocess stdout.
        tunnel_sock = _StdioForward(proc, initial_data=first)

        ckw = _connect_kwargs(self._key_path)
        ckw["sock"] = tunnel_sock
        conn = Connection(
            host=self._host,
            user=self._user,
            port=self._port,
            connect_kwargs=ckw,
        )
        conn.open()
        self._apply_keepalive(conn)
        return conn

    def _kill_tunnel(self) -> None:
        """Terminate any running ssh -W tunnel subprocess."""
        if self._tunnel_proc is not None:
            try:
                self._tunnel_proc.kill()
                self._tunnel_proc.wait(timeout=3)
            except Exception:
                pass
            self._tunnel_proc = None

    def _cleanup_gateway_files(self) -> None:
        """Remove the ControlMaster socket file."""
        if self._control_path and os.path.exists(self._control_path):
            try:
                os.unlink(self._control_path)
            except OSError:
                pass
        self._control_path = None

    def _is_gateway_alive(self) -> bool:
        """Check if the pexpect ControlMaster session is still running."""
        return (
            self._gateway_process is not None
            and self._gateway_process.isalive()
            and self._control_path is not None
            and os.path.exists(self._control_path)
        )

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

        For interactive gateways: if the target connection drops but the
        ControlMaster session is still alive, the target connection is
        re-established via a new local port forward without needing a fresh
        OTP.  If the ControlMaster process has died, a ``RuntimeError`` is
        raised.
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
                # ControlMaster alive — reconnect via existing socket.
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
        """Close SSH connections, port forward, and the ControlMaster session."""
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
        self._kill_tunnel()
        if self._gateway_process is not None:
            # Ask the ControlMaster to exit gracefully, then force-kill.
            if self._control_path:
                try:
                    subprocess.run(
                        [
                            "ssh",
                            "-o", f"ControlPath={self._control_path}",
                            "-O", "exit",
                            f"{self._gateway.user}@{self._gateway.host}",
                        ],
                        capture_output=True, timeout=5,
                    )
                except Exception:
                    pass
            try:
                self._gateway_process.close(force=True)
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

        # Extract --cluster=<name> so srun can target the same cluster.
        self._slurm_cluster: Optional[str] = None
        for arg in slurm_args:
            if arg.startswith("--cluster="):
                self._slurm_cluster = arg.split("=", 1)[1]
            elif arg == "--cluster" or arg == "-M":
                # Next arg is the cluster name — handled by the =form above
                # in the config; flag this as a hint to check manually.
                pass

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
        cluster_info = f" on cluster {self._slurm_cluster}" if self._slurm_cluster else ""
        self._log(
            f"[{self._connection_name}] Interactive node allocated. "
            f"Slurm job {job_id}{cluster_info}."
        )
        return job_id

    def release_slurm_job(self) -> None:
        """Cancel the active Slurm allocation (best-effort).

        Tolerates stale or closed connections — if ``scancel`` cannot be
        delivered on the primary connection, we attempt one retry on a freshly
        opened SSH connection through the same gateway. If that also fails the
        job will time out on its own via Slurm's ``--time`` limit.
        """
        if self._allocation_id is None:
            return
        job_id = self._allocation_id
        self._allocation_id = None  # clear first so close() won't double-cancel
        cluster_flag = ""
        if self._slurm_cluster:
            cluster_flag = f" --cluster={shlex.quote(self._slurm_cluster)}"
        scancel_cmd = f"scancel{cluster_flag} {shlex.quote(job_id)}"

        primary_err: Optional[Exception] = None
        try:
            self.conn.run(scancel_cmd, hide=True, warn=True)
            self._log(f"[{self._connection_name}] Slurm job {job_id} cancelled")
            return
        except Exception as exc:
            primary_err = exc

        # Primary failed — try once via a fresh side-channel connection so a
        # dropped transport does not leak the allocation.
        if self._scancel_via_fresh_connection(job_id):
            self._log(
                f"[{self._connection_name}] Slurm job {job_id} cancelled via "
                "side-channel after primary connection failed."
            )
            return

        self._log(
            f"[{self._connection_name}] WARNING: could not cancel Slurm job "
            f"{job_id} on either the primary or a fresh connection "
            f"(err={primary_err!s}). The job will expire on Slurm's --time."
        )

    def _scancel_via_fresh_connection(self, job_id: str) -> bool:
        """Open a short-lived SSH connection and run ``scancel``.

        Used when the primary transport has dropped mid-run, so we still get
        a best-effort chance to free the Slurm allocation instead of leaking
        it until Slurm's own time limit fires. Returns True on success.

        Interactive gateways are the hard case: a ``scancel`` on a fresh
        connection requires re-opening the gateway, which normally needs a
        new OTP. We try the in-memory ControlMaster socket first (no new
        OTP needed as long as the gateway session is still alive); if that
        fails we give up silently rather than prompt the user again.
        """
        cluster_flag = ""
        if self._slurm_cluster:
            cluster_flag = f" --cluster={shlex.quote(self._slurm_cluster)}"
        scancel_cmd = f"scancel{cluster_flag} {shlex.quote(job_id)}"

        fresh_conn: Optional[Connection] = None
        try:
            if (
                self._gateway is not None
                and self._gateway.auth_method == "interactive"
            ):
                if not self._is_gateway_alive():
                    return False
                fresh_conn = self._connect_through_control_socket()
            elif self._gateway is not None:
                # Key-auth gateway: reopen both legs from scratch.
                gw_conn = Connection(
                    host=self._gateway.host,
                    user=self._gateway.user,
                    port=self._gateway.port,
                    connect_kwargs=_connect_kwargs(self._gateway_key_path),
                )
                fresh_conn = Connection(
                    host=self._host,
                    user=self._user,
                    port=self._port,
                    gateway=gw_conn,
                    connect_kwargs=_connect_kwargs(self._key_path),
                )
                fresh_conn.open()
            else:
                fresh_conn = Connection(
                    host=self._host,
                    user=self._user,
                    port=self._port,
                    connect_kwargs=_connect_kwargs(self._key_path),
                )
                fresh_conn.open()

            fresh_conn.run(scancel_cmd, hide=True, warn=True)
            return True
        except Exception:
            return False
        finally:
            if fresh_conn is not None:
                try:
                    fresh_conn.close()
                except Exception:
                    pass

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
            cluster_flag = ""
            if self._slurm_cluster:
                cluster_flag = f" --cluster={shlex.quote(self._slurm_cluster)}"
            wrapped = (
                f"srun --jobid={shlex.quote(self._allocation_id)}"
                f" --overlap{cluster_flag}{uenv_flags}"
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
        # A daemon thread that waits on the cancel_event and:
        #   1. best-effort cancels the Slurm allocation (if any) on a fresh
        #      side-channel connection — the primary channel is blocked
        #      reading the running command so we can't reuse it;
        #   2. closes the SSH transport to interrupt ``conn.run()`` and
        #      unblock the main thread.
        # Without step 1 a user-triggered cancel would leave the Slurm job
        # consuming cluster resources until its --time limit expires.
        command_done = threading.Event()

        if cancel_event is not None:
            def _cancel_watchdog() -> None:
                cancel_event.wait()
                if command_done.is_set():
                    return
                if self._allocation_id is not None:
                    job_id = self._allocation_id
                    if self._scancel_via_fresh_connection(job_id):
                        self._log(
                            f"[{self._connection_name}] cancel: Slurm job "
                            f"{job_id} cancelled via side-channel."
                        )
                        # Clear the allocation id so the subsequent
                        # release_slurm_job() during close() does not retry.
                        self._allocation_id = None
                    else:
                        self._log(
                            f"[{self._connection_name}] cancel: could not "
                            f"reach Slurm to cancel job {job_id} on a "
                            "side-channel; will rely on Slurm --time."
                        )
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
                # SSH/transport failure that was NOT a cancellation: the
                # primary channel is dead. If a Slurm job was active, the
                # remote process is still consuming a compute node; try
                # best-effort scancel on a fresh side-channel before
                # bubbling the error up.
                if self._allocation_id is not None:
                    job_id = self._allocation_id
                    if self._scancel_via_fresh_connection(job_id):
                        self._log(
                            f"[{self._connection_name}] transport error; "
                            f"Slurm job {job_id} cancelled via side-channel."
                        )
                        self._allocation_id = None
                    else:
                        self._log(
                            f"[{self._connection_name}] transport error; "
                            f"could not reach Slurm to cancel job {job_id} "
                            "on a side-channel. The job will expire on "
                            "Slurm's --time limit."
                        )
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
        repo_name = Path(remote_path).name
        if self.path_exists(f"{remote_path}/.git"):
            self._log(f"[{self._connection_name}] Updating {repo_name} (branch={branch})...")
            # Fetch all remote tracking refs so origin/{branch} is guaranteed
            # up to date. Using "git fetch origin" (no branch arg) ensures the
            # configured refspec maps refs/heads/* → refs/remotes/origin/* for
            # all branches, which is required for the reset --hard step below.
            rc_fetch = self.run_command(
                "git fetch origin",
                remote_cwd=remote_path,
                log_path=log_path,
                append_log=True,
                cancel_event=cancel_event,
            )
            if rc_fetch != 0:
                self._log(
                    f"[{self._connection_name}] WARNING: {repo_name} fetch failed"
                    " — aborting update to avoid building stale code."
                )
                return False
            rc_checkout = self.run_command(
                f"git checkout {shlex.quote(branch)}",
                remote_cwd=remote_path,
                log_path=log_path,
                append_log=True,
                cancel_event=cancel_event,
            )
            if rc_checkout != 0:
                self._log(
                    f"[{self._connection_name}] WARNING: {repo_name} checkout of"
                    f" {branch} failed."
                )
                return False
            # Hard-reset to the remote tracking ref instead of ff-only pull.
            # This is deterministic even if the local branch has diverged (e.g.
            # after a manual commit on the remote during debugging).
            rc_reset = self.run_command(
                f"git reset --hard origin/{shlex.quote(branch)}",
                remote_cwd=remote_path,
                log_path=log_path,
                append_log=True,
                cancel_event=cancel_event,
            )
            if rc_reset == 0:
                self._log(f"[{self._connection_name}] {repo_name} updated.")
            else:
                self._log(f"[{self._connection_name}] WARNING: {repo_name} reset failed.")
            return rc_reset == 0
        else:
            parent = str(Path(remote_path).parent)
            self.ensure_dir(parent)
            self._log(f"[{self._connection_name}] Cloning {repo_name} (branch={branch})...")
            rc = self.run_command(
                f"git clone --branch {shlex.quote(branch)} {shlex.quote(repo_url)} {shlex.quote(remote_path)}",
                remote_cwd=parent,
                log_path=log_path,
                append_log=True,
                cancel_event=cancel_event,
            )
            if rc == 0:
                self._log(f"[{self._connection_name}] {repo_name} cloned.")
            else:
                self._log(f"[{self._connection_name}] WARNING: {repo_name} clone failed.")
            return rc == 0

    def git_rev_parse_short(self, remote_path: str) -> Optional[str]:
        """Return the short SHA of HEAD at *remote_path* on the remote.

        Returns None if the command fails (e.g. path is not a git repo).
        Does NOT apply env activation -- git is always available.
        """
        try:
            result = self.conn.run(
                f"git -C {shlex.quote(remote_path)} rev-parse --short HEAD",
                hide=True,
                warn=True,
            )
            if result.return_code == 0:
                return result.stdout.strip() or None
            return None
        except Exception:
            return None

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

    def fetch_file_status(
        self, remote_path: str, local_path: Path
    ) -> tuple[str, Optional[str]]:
        """Try to fetch *remote_path*; return a precise status instead of raising.

        Return values:
          ``("fetched", None)``      — file copied successfully.
          ``("absent", None)``       — file does not exist on the remote.
          ``("transport_error", msg)`` — SFTP or transport failure.

        The regression runner uses this to distinguish "the run never produced
        this stat file" (a genuine test failure, keeps state ``broken``) from
        "SSH dropped while fetching" (escalates to ``failed`` so operators do
        not treat transport flakes as silent broken tests).
        """
        local_path.parent.mkdir(parents=True, exist_ok=True)
        transport = self.conn.transport
        if transport is None or not transport.is_active():
            return ("transport_error", "SSH transport is not active")
        try:
            sftp = paramiko.SFTPClient.from_transport(transport)
        except Exception as exc:
            return ("transport_error", f"could not open SFTP: {exc}")
        try:
            try:
                sftp.stat(remote_path)
            except FileNotFoundError:
                return ("absent", None)
            except IOError as exc:
                # Paramiko reports missing file as IOError with errno 2.
                if getattr(exc, "errno", None) == 2:
                    return ("absent", None)
                return ("transport_error", f"stat failed: {exc}")
            try:
                sftp.get(remote_path, str(local_path))
            except (paramiko.SSHException, socket.error, EOFError) as exc:
                return ("transport_error", f"get failed: {exc}")
            except IOError as exc:
                return ("transport_error", f"get failed: {exc}")
            return ("fetched", None)
        finally:
            try:
                sftp.close()
            except Exception:
                pass

    # ── Directory helpers ────────────────────────────────────────────────

    def ensure_dir(self, remote_path: str) -> None:
        """Create a directory (and parents) on the remote.

        Bypasses ``self._env`` since ``mkdir -p`` only needs coreutils.
        """
        self.conn.run(
            f"mkdir -p {shlex.quote(remote_path)}", hide=True, warn=True
        )

    def remove_dir(self, remote_path: str) -> None:
        """Recursively remove *remote_path* on the remote. No-op if absent."""
        self.conn.run(
            f"rm -rf {shlex.quote(remote_path)}", hide=True, warn=True
        )

    def path_exists(self, remote_path: str) -> bool:
        """Check whether *remote_path* exists on the remote.

        Bypasses ``self._env`` since ``test -e`` is a bash builtin.
        """
        result = self.conn.run(
            f"test -e {shlex.quote(remote_path)}", hide=True, warn=True
        )
        return result.return_code == 0

    def list_dir(self, remote_path: str) -> list[str]:
        """Return the immediate children of *remote_path* on the remote.

        Names are returned without a trailing slash, sorted, and hidden
        entries (starting with ``.``) are omitted — matching what local
        regtests discovery already ignores. Returns an empty list if the
        directory does not exist or cannot be read.
        """
        result = self.conn.run(
            f"ls -1 {shlex.quote(remote_path)}", hide=True, warn=True
        )
        if result.return_code != 0:
            return []
        entries = [
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip() and not line.strip().startswith(".")
        ]
        entries.sort()
        return entries

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
