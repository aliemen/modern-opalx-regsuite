from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from . import config as config_mod
from .config import SuiteConfig
from .runner import run_pipeline
from .sitegen import generate_site


app = typer.Typer(help="Modern OPALX regression suite CLI.")


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
    cfg_path = config_mod.init_default_config(
        opalx_repo_root=_resolve_path(opalx_repo_root),
        builds_root=_resolve_path(builds_root),
        data_root=_resolve_path(data_root),
        default_branch=default_branch,
        default_architectures=[default_arch],
        path=config,
    )
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


if __name__ == "__main__":
    app()

