from __future__ import annotations

from pathlib import Path
from typing import Optional
import fnmatch
import json
import shutil

import typer

from . import config as config_mod
from . import archive_service
from .config import SuiteConfig
from .data_model import RunIndexEntry, RunMeta, branches_index_path, run_dir, runs_index_path
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
    ssh_keys_dir: Optional[str] = typer.Option(
        None,
        "--ssh-keys-dir",
        help=(
            "Directory for SSH private key files. "
            "Defaults to ~/.config/opalx-regsuite/ssh-keys if not set."
        ),
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
        ssh_keys_dir=_resolve_path(ssh_keys_dir) if ssh_keys_dir else None,
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


@app.command("archive")
def archive_cmd(
    branch: str = typer.Option(
        ...,
        "--branch",
        "-b",
        help="Branch to archive (or unarchive with --unarchive).",
    ),
    arch: Optional[str] = typer.Option(
        None,
        "--arch",
        "-a",
        help="Restrict to a single architecture. Omit to apply to all archs of the branch.",
    ),
    run_id: Optional[list[str]] = typer.Option(
        None,
        "--run-id",
        help="Restrict to specific run id(s). Repeat the flag to pass multiple. "
             "Requires --arch.",
    ),
    unarchive: bool = typer.Option(
        False,
        "--unarchive",
        help="Restore archived runs instead of archiving them.",
    ),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.toml.",
    ),
) -> None:
    """Bulk archive or unarchive runs.

    Examples
    --------
    # Archive every run on the 'feature/x' branch.
    $ opalx-regsuite archive --branch feature/x

    # Archive only the cpu-serial runs of master.
    $ opalx-regsuite archive --branch master --arch cpu-serial

    # Archive two specific runs.
    $ opalx-regsuite archive -b master -a cpu-serial \
        --run-id 20260305-131642 --run-id 20260306-091200

    # Restore an archived branch.
    $ opalx-regsuite archive --branch feature/x --unarchive
    """
    if run_id and not arch:
        typer.echo("Error: --run-id requires --arch.", err=True)
        raise typer.Exit(code=2)

    cfg = _load_config_option(config)
    data_root = cfg.resolved_data_root

    archived = not unarchive
    action = "archive" if archived else "unarchive"

    try:
        if run_id:
            result = archive_service.set_archived_for_runs(
                data_root, branch, arch, run_id, archived=archived
            )
        elif arch:
            result = archive_service.set_archived_for_arch(
                data_root, branch, arch, archived=archived
            )
        else:
            result = archive_service.set_archived_for_branch(
                data_root, branch, archived=archived
            )
    except archive_service.ProtectedBranchError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2)

    typer.echo(
        f"{action.title()}d {result.changed} run(s) "
        f"(branch={branch}"
        + (f", arch={arch}" if arch else "")
        + ")."
    )
    if result.skipped_active:
        typer.echo(
            f"Skipped {len(result.skipped_active)} actively-running run(s): "
            + ", ".join(sorted(result.skipped_active))
        )
    if result.not_found:
        typer.echo(
            f"Not found in index: " + ", ".join(sorted(result.not_found))
        )


@app.command("patch-visibility")
def patch_visibility(
    branch: str = typer.Option(
        ...,
        "--branch",
        "-b",
        help="Branch to patch.",
    ),
    arch: Optional[str] = typer.Option(
        None,
        "--arch",
        "-a",
        help="Restrict to a single architecture. Omit to apply to every arch of the branch.",
    ),
    run_id: Optional[list[str]] = typer.Option(
        None,
        "--run-id",
        help="Restrict to specific run id(s). Repeat to pass multiple. Requires --arch.",
    ),
    public: bool = typer.Option(
        False,
        "--public",
        help="Mark runs as public (visible on /api/public/*).",
    ),
    private: bool = typer.Option(
        False,
        "--private",
        help="Mark runs as private (the default for new runs).",
    ),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.toml.",
    ),
) -> None:
    """Bulk publish or unpublish historical runs.

    Patches the ``public`` flag in both ``run-meta.json`` and the
    corresponding ``runs-index/<branch>/<arch>.json`` entry, under the same
    ``fcntl.flock`` used by the pipeline completion writer — safe to run
    against a live server.

    Examples
    --------
    # Publish every run of master/cpu-serial.
    $ opalx-regsuite patch-visibility --branch master --arch cpu-serial --public

    # Unpublish a single run.
    $ opalx-regsuite patch-visibility -b master -a cpu-serial \\
        --run-id 20260305-131642 --private

    # Publish the whole branch (all archs).
    $ opalx-regsuite patch-visibility --branch feature/demo --public
    """
    if public == private:
        typer.echo(
            "Error: specify exactly one of --public or --private.", err=True
        )
        raise typer.Exit(code=2)
    if run_id and not arch:
        typer.echo("Error: --run-id requires --arch.", err=True)
        raise typer.Exit(code=2)

    cfg = _load_config_option(config)
    data_root = cfg.resolved_data_root
    want_public = public
    action = "publish" if want_public else "unpublish"

    if run_id:
        result = archive_service.set_public_for_runs(
            data_root, branch, arch, run_id, public=want_public
        )
    elif arch:
        result = archive_service.set_public_for_branch_arch(
            data_root, branch, arch, public=want_public
        )
    else:
        # Walk every arch the branch has ever produced.
        total = 0
        for a in archive_service._list_archs_for_branch(data_root, branch):
            r = archive_service.set_public_for_branch_arch(
                data_root, branch, a, public=want_public
            )
            total += r.changed
        typer.echo(
            f"{action.title()}ed {total} run(s) across all archs of branch={branch}."
        )
        return

    typer.echo(
        f"{action.title()}ed {result.changed} run(s) "
        f"(branch={branch}"
        + (f", arch={arch}" if arch else "")
        + ")."
    )
    if result.not_found:
        typer.echo("Not found in index: " + ", ".join(sorted(result.not_found)))


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
    """Add or update a user and materialize their per-user directory tree."""
    from .api.auth import add_user
    from .user_store import ensure_user_dir

    cfg = _load_config_option(config)
    add_user(cfg, username, password)
    udir = ensure_user_dir(cfg, username)
    typer.echo(f"User '{username}' saved to {cfg.resolved_users_file}")
    typer.echo(f"User directory: {udir}")


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


@app.command("migrate-keys")
def migrate_keys(
    username: str = typer.Option(..., "--user", "-u", prompt=True),
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
) -> None:
    """Copy legacy global SSH keys into the per-user keys directory.

    Reads from ``cfg.resolved_ssh_keys_dir`` (the deprecated global location)
    and copies every ``*.pem`` into ``<users_root>/<username>/ssh-keys/``.
    Existing per-user keys with the same name are NOT overwritten — those
    must be removed manually first.
    """
    from .user_store import ensure_user_dir, user_keys_dir

    cfg = _load_config_option(config)
    src = cfg.resolved_ssh_keys_dir
    if not src.is_dir():
        typer.echo(f"No legacy ssh-keys dir at {src}; nothing to migrate.")
        raise typer.Exit(0)

    ensure_user_dir(cfg, username)
    dst = user_keys_dir(cfg, username)
    copied = 0
    skipped = 0
    for key in sorted(src.glob("*.pem")):
        target = dst / key.name
        if target.exists():
            typer.echo(f"  skip  {key.name} (already exists in user dir)")
            skipped += 1
            continue
        shutil.copy2(key, target)
        target.chmod(0o600)
        typer.echo(f"  copy  {key.name}")
        copied += 1
    typer.echo(f"\nMigrated {copied} key(s), skipped {skipped}.")
    typer.echo(f"Source: {src}")
    typer.echo(f"Target: {dst}")


@app.command("rebuild-indexes")
def rebuild_indexes(
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.toml (defaults to ./config.toml or $OPALX_REGSUITE_CONFIG).",
    ),
) -> None:
    """Rebuild runs-index/ and branches.json from all run-meta.json files on disk.

    Run this once after pointing data_root at an existing data directory that
    pre-dates the index files (e.g. legacy test data).
    """
    cfg = _load_config_option(config)
    data_root = cfg.resolved_data_root
    runs_root = data_root / "runs"

    if not runs_root.is_dir():
        typer.echo(f"No runs directory found at {runs_root}")
        raise typer.Exit(0)

    # Collect all valid metas grouped by (branch, arch).
    from collections import defaultdict
    by_branch_arch: dict[tuple[str, str], list[RunMeta]] = defaultdict(list)
    total = 0

    for meta_path in sorted(runs_root.glob("*/*/*/run-meta.json")):
        try:
            with meta_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            meta = RunMeta.model_validate(data)
            by_branch_arch[(meta.branch, meta.arch)].append(meta)
            total += 1
        except Exception as exc:
            typer.echo(f"  Skipping {meta_path}: {exc}", err=True)

    if total == 0:
        typer.echo("No valid run-meta.json files found.")
        raise typer.Exit(0)

    typer.echo(f"Found {total} run(s) across {len(by_branch_arch)} branch/arch pair(s).")

    branches: dict[str, list[str]] = {}

    for (branch, arch), metas in sorted(by_branch_arch.items()):
        metas.sort(key=lambda m: m.started_at, reverse=True)
        entries = [
            RunIndexEntry(
                branch=m.branch,
                arch=m.arch,
                run_id=m.run_id,
                started_at=m.started_at,
                finished_at=m.finished_at,
                status=m.status,
                unit_tests_total=m.unit_tests_total,
                unit_tests_failed=m.unit_tests_failed,
                regression_total=m.regression_total,
                regression_passed=m.regression_passed,
                regression_failed=m.regression_failed,
                regression_broken=m.regression_broken,
            )
            for m in metas
        ]
        idx_path = runs_index_path(data_root, branch, arch)
        idx_path.parent.mkdir(parents=True, exist_ok=True)
        with idx_path.open("w", encoding="utf-8") as f:
            json.dump([e.model_dump(mode="json") for e in entries], f, indent=2, default=str)
        typer.echo(f"  {branch}/{arch}: {len(entries)} run(s) → {idx_path}")

        archs = set(branches.get(branch, []))
        archs.add(arch)
        branches[branch] = sorted(archs)

    branches_path = branches_index_path(data_root)
    with branches_path.open("w", encoding="utf-8") as f:
        json.dump(branches, f, indent=2)
    typer.echo(f"Branches index written to {branches_path}")


@app.command("backfill-users")
def backfill_users(
    username: str = typer.Option(
        "opalx",
        "--username",
        "-u",
        help="Username to assign to runs that have no triggered_by field. "
             "Default is 'opalx', the legacy bucket.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Only report what would change; do not modify any files.",
    ),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.toml (defaults to ./config.toml or $OPALX_REGSUITE_CONFIG).",
    ),
) -> None:
    """Assign a username to legacy runs that have no ``triggered_by`` value.

    Scans every ``runs/<branch>/<arch>/<run_id>/run-meta.json`` and, for any
    file whose ``triggered_by`` field is missing or null, sets it to
    *username* and rewrites the file. The corresponding entry in
    ``runs-index/<branch>/<arch>.json`` is updated in the same pass so the
    Archive-tab user dropdown sees the backfilled value without needing a
    full ``rebuild-indexes``.
    """
    cfg = _load_config_option(config)
    data_root = cfg.resolved_data_root
    runs_root = data_root / "runs"

    if not runs_root.is_dir():
        typer.echo(f"No runs directory found at {runs_root}")
        raise typer.Exit(0)

    # Pass 1: rewrite run-meta.json files. Track (branch, arch, run_id) so
    # we can patch the matching index entries in pass 2.
    backfilled: dict[tuple[str, str], list[str]] = {}
    inspected = 0

    for meta_path in sorted(runs_root.glob("*/*/*/run-meta.json")):
        inspected += 1
        try:
            with meta_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            typer.echo(f"  skip  {meta_path}: {exc}", err=True)
            continue

        if data.get("triggered_by"):
            continue  # already has a user

        data["triggered_by"] = username
        branch = data.get("branch")
        arch = data.get("arch")
        run_id = data.get("run_id")
        if not (isinstance(branch, str) and isinstance(arch, str) and isinstance(run_id, str)):
            typer.echo(f"  skip  {meta_path}: missing branch/arch/run_id", err=True)
            continue

        if not dry_run:
            with meta_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)

        backfilled.setdefault((branch, arch), []).append(run_id)

    total_backfilled = sum(len(ids) for ids in backfilled.values())
    typer.echo(
        f"Inspected {inspected} run(s); "
        f"{total_backfilled} run(s) need backfill → '{username}'."
    )

    if total_backfilled == 0:
        return

    # Pass 2: patch matching entries in each affected index file.
    patched_index_entries = 0
    for (branch, arch), run_ids in sorted(backfilled.items()):
        idx_path = runs_index_path(data_root, branch, arch)
        if not idx_path.is_file():
            typer.echo(
                f"  warn  no index for {branch}/{arch}; skipping index patch."
            )
            continue
        try:
            with idx_path.open("r", encoding="utf-8") as f:
                entries = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            typer.echo(f"  warn  cannot read {idx_path}: {exc}")
            continue
        if not isinstance(entries, list):
            continue

        target = set(run_ids)
        local_patched = 0
        for entry in entries:
            rid = entry.get("run_id")
            if isinstance(rid, str) and rid in target and not entry.get("triggered_by"):
                entry["triggered_by"] = username
                local_patched += 1

        if local_patched and not dry_run:
            with idx_path.open("w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2, default=str)

        if local_patched:
            patched_index_entries += local_patched
            typer.echo(
                f"  {branch}/{arch}: patched {local_patched} index entry(ies)."
            )

    typer.echo(
        f"\n{'[dry-run] would patch' if dry_run else 'Patched'} "
        f"{total_backfilled} run-meta.json file(s) and "
        f"{patched_index_entries} index entry(ies)."
    )


@app.command("backfill-regtest-branches")
def backfill_regtest_branches(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Only report what would change; do not modify any files.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite existing regtest_branch values (default: skip runs that already have one).",
    ),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.toml (defaults to ./config.toml or $OPALX_REGSUITE_CONFIG).",
    ),
) -> None:
    """Back-fill the ``regtest_branch`` field for historical runs.

    Scans every ``runs/<branch>/<arch>/<run_id>/run-meta.json``. For runs
    that are missing ``regtest_branch`` (or, with ``--force``, all runs), it
    uses ``git branch -a --contains <tests_repo_commit>`` against the local
    regression-tests repo to infer the branch name, then writes it to both
    ``run-meta.json`` and the matching ``runs-index`` entry.

    Preference order when multiple branches contain the commit:
      1. "master" or "main"
      2. Alphabetically first remote-tracking branch (``remotes/origin/<name>``)
      3. Alphabetically first local branch

    Runs whose ``tests_repo_commit`` is absent or unknown to the local repo are
    skipped and reported.
    """
    import subprocess

    cfg = _load_config_option(config)
    data_root = cfg.resolved_data_root
    runs_root = data_root / "runs"
    regtests_repo = cfg.resolved_regtests_repo_root

    if not runs_root.is_dir():
        typer.echo(f"No runs directory found at {runs_root}")
        raise typer.Exit(0)

    if not (regtests_repo / ".git").is_dir():
        typer.echo(
            f"Regression-tests repo not found or not a git repo: {regtests_repo}",
            err=True,
        )
        raise typer.Exit(1)

    def _resolve_branch(commit: str) -> Optional[str]:
        """Return the best branch name that contains *commit*, or None."""
        proc = subprocess.run(
            ["git", "branch", "-a", "--contains", commit],
            cwd=str(regtests_repo),
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None

        raw_lines = [ln.strip().lstrip("* ") for ln in proc.stdout.splitlines()]
        # Strip the "remotes/origin/" prefix to get bare branch names.
        names: list[str] = []
        for line in raw_lines:
            if line.startswith("remotes/origin/"):
                names.append(line[len("remotes/origin/"):])
            elif line and not line.startswith("remotes/"):
                names.append(line)

        if not names:
            return None

        # Prefer master / main, then alphabetical.
        for preferred in ("master", "main"):
            if preferred in names:
                return preferred
        return sorted(names)[0]

    backfilled: dict[tuple[str, str], list[tuple[str, str]]] = {}  # (branch, arch) → [(run_id, resolved)]
    inspected = 0
    skipped_no_commit = 0
    skipped_not_found = 0

    for meta_path in sorted(runs_root.glob("*/*/*/run-meta.json")):
        inspected += 1
        try:
            with meta_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            typer.echo(f"  skip  {meta_path}: {exc}", err=True)
            continue

        if data.get("regtest_branch") and not force:
            continue  # already backfilled

        commit = data.get("tests_repo_commit")
        if not commit:
            skipped_no_commit += 1
            continue

        resolved = _resolve_branch(commit)
        if resolved is None:
            skipped_not_found += 1
            typer.echo(f"  warn  commit {commit} not found in {regtests_repo}")
            continue

        branch = data.get("branch")
        arch = data.get("arch")
        run_id = data.get("run_id")
        if not (isinstance(branch, str) and isinstance(arch, str) and isinstance(run_id, str)):
            typer.echo(f"  skip  {meta_path}: missing branch/arch/run_id", err=True)
            continue

        data["regtest_branch"] = resolved
        if not dry_run:
            with meta_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)

        backfilled.setdefault((branch, arch), []).append((run_id, resolved))

    total_backfilled = sum(len(ids) for ids in backfilled.values())
    typer.echo(
        f"Inspected {inspected} run(s); "
        f"{total_backfilled} run(s) backfilled, "
        f"{skipped_no_commit} skipped (no commit hash), "
        f"{skipped_not_found} skipped (commit unknown to repo)."
    )

    if total_backfilled == 0:
        return

    # Patch matching entries in each affected index file.
    patched_index_entries = 0
    for (branch, arch), run_pairs in sorted(backfilled.items()):
        idx_path = runs_index_path(data_root, branch, arch)
        if not idx_path.is_file():
            typer.echo(f"  warn  no index for {branch}/{arch}; skipping index patch.")
            continue
        try:
            with idx_path.open("r", encoding="utf-8") as f:
                entries = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            typer.echo(f"  warn  cannot read {idx_path}: {exc}")
            continue
        if not isinstance(entries, list):
            continue

        run_id_to_branch = dict(run_pairs)
        local_patched = 0
        for entry in entries:
            rid = entry.get("run_id")
            if isinstance(rid, str) and rid in run_id_to_branch:
                if entry.get("regtest_branch") and not force:
                    continue
                entry["regtest_branch"] = run_id_to_branch[rid]
                local_patched += 1

        if local_patched and not dry_run:
            with idx_path.open("w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2, default=str)

        if local_patched:
            patched_index_entries += local_patched
            typer.echo(f"  {branch}/{arch}: patched {local_patched} index entry(ies).")

    typer.echo(
        f"\n{'[dry-run] would patch' if dry_run else 'Patched'} "
        f"{total_backfilled} run-meta.json file(s) and "
        f"{patched_index_entries} index entry(ies)."
    )


@app.command("migrate-regression-json")
def migrate_regression_json_cmd(
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.toml (defaults to ./config.toml or $OPALX_REGSUITE_CONFIG).",
    ),
) -> None:
    """Rewrite historical regression-tests.json files to the containers layout.

    Wraps each simulation's flat ``metrics`` array into a single
    ``containers: [{id: None, ...}]`` entry so the multi-beam UI can read it.
    Idempotent — already-migrated files are left alone. A ``.bak`` sibling is
    created on the first modification of each file.
    """
    from .runner.migrations import migrate_all_regression_json

    cfg = _load_config_option(config)
    data_root = cfg.resolved_data_root
    inspected, migrated = migrate_all_regression_json(data_root)
    typer.echo(
        f"Inspected {inspected} regression-tests.json file(s); "
        f"migrated {migrated}."
    )


if __name__ == "__main__":
    app()

