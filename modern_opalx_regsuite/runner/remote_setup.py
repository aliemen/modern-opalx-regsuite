from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..config import ArchConfig, Connection


def create_remote_executor(
    *,
    connection: Connection,
    target_key_path: Optional[Path],
    gateway_key_path: Optional[Path],
    pipeline_log_path: Path,
    arch_config: ArchConfig,
    branch: str,
    arch: str,
    gateway_password: Optional[str],
    gateway_otp: Optional[str],
) -> tuple["RemoteExecutor", str, str]:  # type: ignore[name-defined]
    """Validate remote key inputs and build the executor plus remote paths."""
    from ..remote import RemoteExecutor

    if target_key_path is None:
        raise ValueError(
            "run_pipeline: connection is set but target_key_path is None - "
            "the API layer must pre-resolve key paths."
        )
    if not target_key_path.exists():
        raise FileNotFoundError(f"SSH key not found: {target_key_path}")
    if connection.gateway is not None and connection.gateway.auth_method != "interactive":
        if gateway_key_path is None:
            raise ValueError(
                "run_pipeline: connection has a gateway but gateway_key_path is None"
            )
        if not gateway_key_path.exists():
            raise FileNotFoundError(f"Gateway SSH key not found: {gateway_key_path}")

    remote = RemoteExecutor(
        host=connection.host,
        user=connection.user,
        key_path=target_key_path,
        port=connection.port,
        connection_name=connection.name,
        gateway=connection.gateway,
        gateway_key_path=gateway_key_path,
        env=connection.env,
        pipeline_log_path=pipeline_log_path,
        keepalive_interval=connection.keepalive_interval,
        command_timeout=arch_config.command_timeout,
        salloc_timeout=arch_config.salloc_timeout,
        gateway_password=gateway_password,
        gateway_otp=gateway_otp,
    )
    remote_base = connection.work_dir
    return remote, remote_base, f"{remote_base}/builds/{branch}/{arch}/build"
