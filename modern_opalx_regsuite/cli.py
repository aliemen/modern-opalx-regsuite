from __future__ import annotations

from pathlib import Path
from typing import Optional
import fnmatch
import json
import shutil

import typer

from . import config as config_mod
from .config import SuiteConfig
from .data_model import run_dir, runs_index_path
from .runner import run_pipeline
from .sitegen import generate_site


app = typer.Typer(help="Modern OPALX regression suite CLI.", no_args_is_help=True)


def _resolve_path(p: str) -> Path:
    return Path(p).expanduser().resolve()


def _load_config_option(config_path: Optional[Path]) -> SuiteConfig:
    return config_mod.load_config(config_path)


@app.command()
def init(
    opalx_repo_root: str = typer.Option(
        ...,
        prompt=True,
        help="Path to OPALX source checkout.",
    ),
    builds_root: str = typer.Option(
        ...,
        prompt=True,
        help="Root directory for per-branch/per-arch builds.",
    ),
    data_root: str = typer.Option(
        ...,
        prompt=True,
        help="Root directory for regression/unit test data.",
    ),
    regtests_repo_root: str = typer.Option(
        ...,
        prompt=True,
        help="Path to regression-tests-x source checkout.",
    ),
    regtests_branch: str = typer.Option(
        "master",
        prompt=True,
        help="Branch to use for regression-tests-x.",
    ),
    default_branch: str = typer.Option(
        "master",
        prompt=True,
        help="Default branch to test.",
    ),
    default_arch: str = typer.Option(
        "cpu-serial",
        prompt=True,
        help="Default architecture to test.",
    ),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.toml (defaults to ./config.toml or $OPALX_REGSUITE_CONFIG).",
    ),
) -> None:
    """Initialize a new configuration file."""
    cfg = config_mod.SuiteConfig(
        opalx_repo_root=_resolve_path(opalx_repo_root),
        builds_root=_resolve_path(builds_root),
        data_root=_resolve_path(data_root),
        regtests_repo_root=_resolve_path(regtests_repo_root),
        regtests_branch=regtests_branch,
        default_branch=default_branch,
        default_architectures=[default_arch],
    )
    cfg_path = config_mod.save_config(cfg, path=config)
    typer.echo(f"Configuration written to {cfg_path}")


@app.command()
def run(
    branch: Optional[str] = typer.Option(
        None,
        "--branch",
        "-b",
        help="Branch to test (defaults to config.default_branch).",
    ),
    arch: Optional[str] = typer.Option(
        None,
        "--arch",
        "-a",
        help="Architecture to test (defaults to first config.default_architectures entry).",
    ),
    run_id: Optional[str] = typer.Option(
        None,
        help="Optional run identifier (defaults to timestamp).",
    ),
    skip_unit: bool = typer.Option(
        False,
        help="Skip unit tests.",
    ),
    skip_regression: bool = typer.Option(
        False,
        help="Skip regression tests.",
    ),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.toml (defaults to ./config.toml or $OPALX_REGSUITE_CONFIG).",
    ),
) -> None:
    """Run unit and regression tests for a branch/architecture."""
    cfg = _load_config_option(config)
    branch = branch or cfg.default_branch
    arch = arch or (cfg.default_architectures[0] if cfg.default_architectures else "cpu-serial")

    typer.echo(f"Running pipeline for branch={branch}, arch={arch} ...")
    meta = run_pipeline(
        cfg,
        branch=branch,
        arch=arch,
        run_id=run_id,
        skip_unit=skip_unit,
        skip_regression=skip_regression,
    )
    typer.echo(f"Run {meta.run_id} finished with status={meta.status}")


@app.command("gen-data-site")
def gen_data_site(
    out_dir: Path = typer.Option(
        ...,
        "--out-dir",
        "-o",
        help="Output directory for the generated static site.",
    ),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.toml (defaults to ./config.toml or $OPALX_REGSUITE_CONFIG).",
    ),
) -> None:
    """Generate a static HTML site from the data directory."""
    cfg = _load_config_option(config)
    data_root = cfg.resolved_data_root
    package_root = Path(__file__).resolve().parent
    out_dir = out_dir.expanduser().resolve()

    typer.echo(f"Generating site from {data_root} into {out_dir} ...")
    generate_site(data_root=data_root, out_dir=out_dir, package_root=package_root)
    typer.echo("Site generation complete.")


@app.command("del-test")
def del_test(
    run_id: str = typer.Argument(
        ...,
        help="Run identifier or glob pattern (e.g. '20260305-131529' or '2026*').",
    ),
    branch: Optional[str] = typer.Option(
        None,
        "--branch",
        "-b",
        help="Branch to operate on (defaults to config.default_branch).",
    ),
    arch: Optional[str] = typer.Option(
        None,
        "--arch",
        "-a",
        help="Architecture to operate on (defaults to first config.default_architectures entry).",
    ),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.toml (defaults to ./config.toml or $OPALX_REGSUITE_CONFIG).",
    ),
) -> None:
    """Delete one or more test runs from the data directory."""
    cfg = _load_config_option(config)
    data_root = cfg.resolved_data_root

    branch = branch or cfg.default_branch
    if arch is not None:
        archs = [arch]
    else:
        archs = cfg.default_architectures or ["cpu-serial"]

    total_deleted = 0

    for current_arch in archs:
        index_path = runs_index_path(data_root, branch, current_arch)
        if not index_path.is_file():
            continue

        with index_path.open("r", encoding="utf-8") as f:
            try:
                entries = json.load(f)
            except json.JSONDecodeError:
                typer.echo(f"Warning: could not parse runs index {index_path}, skipping.")
                continue

        if not isinstance(entries, list):
            typer.echo(f"Warning: unexpected structure in {index_path}, skipping.")
            continue

        kept_entries = []
        deleted_ids: list[str] = []

        for entry in entries:
            rid = entry.get("run_id")
            if isinstance(rid, str) and fnmatch.fnmatch(rid, run_id):
                deleted_ids.append(rid)
                run_path = run_dir(data_root, branch, current_arch, rid)
                if run_path.exists():
                    shutil.rmtree(run_path)
            else:
                kept_entries.append(entry)

        if deleted_ids:
            with index_path.open("w", encoding="utf-8") as f:
                json.dump(kept_entries, f, indent=2)

            total_deleted += len(deleted_ids)
            typer.echo(
                f"Deleted {len(deleted_ids)} run(s) for branch={branch}, arch={current_arch}: "
                + ", ".join(sorted(deleted_ids))
            )

    if total_deleted == 0:
        typer.echo(
            f"No runs matched pattern '{run_id}' "
            f"(branch={branch}, archs={', '.join(archs)})."
        )


@app.command()
def serve(
    host: str = typer.Option(None, "--host", help="Bind host (overrides config)."),
    port: int = typer.Option(None, "--port", help="Bind port (overrides config)."),
    workers: int = typer.Option(
        1,
        "--workers",
        help="Number of uvicorn workers. Must be 1 for the run-state singleton.",
    ),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.toml.",
    ),
) -> None:
    """Start the OPALX regression suite web server."""
    try:
        import uvicorn
    except ImportError:
        typer.echo("uvicorn is required. Install it with: pip install 'uvicorn[standard]'")
        raise typer.Exit(1)

    cfg = _load_config_option(config)
    bind_host = host or cfg.host
    bind_port = port or cfg.port

    if workers != 1:
        typer.echo(
            "Warning: --workers > 1 is not supported (run-state singleton requires a single process).",
            err=True,
        )
        workers = 1

    typer.echo(f"Starting OPALX regression suite at http://{bind_host}:{bind_port}")
    uvicorn.run(
        "modern_opalx_regsuite.api.app:create_app",
        factory=True,
        host=bind_host,
        port=bind_port,
        workers=workers,
        log_level="info",
    )


@app.command("user-add")
def user_add(
    username: str = typer.Option(..., "--username", "-u", prompt=True),
    password: str = typer.Option(
        ...,
        "--password",
        "-p",
        prompt=True,
        hide_input=True,
        confirmation_prompt=True,
    ),
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
) -> None:
    """Add or update a user in the users.json file."""
    from .api.auth import add_user

    cfg = _load_config_option(config)
    add_user(cfg, username, password)
    typer.echo(f"User '{username}' saved to {cfg.resolved_users_file}")


@app.command("user-del")
def user_del(
    username: str = typer.Option(..., "--username", "-u", prompt=True),
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
) -> None:
    """Remove a user from the users.json file."""
    from .api.auth import delete_user

    cfg = _load_config_option(config)
    if delete_user(cfg, username):
        typer.echo(f"User '{username}' removed.")
    else:
        typer.echo(f"User '{username}' not found.", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()

