"""One-shot data-layout migrations for regression-tests.json files.

The multi-beam refactor moved per-simulation metrics into a nested
``containers`` list so a single simulation can hold N beam-container slices.
Historical runs written before that change have a flat ``metrics`` array on
each simulation; this module rewrites them in place to the new shape.

The migration is idempotent: once a simulation has ``containers``, we leave
it alone. The first write of any file creates a ``<file>.bak`` sibling so a
misbehaving migration can be reverted by hand.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Optional

log = logging.getLogger("opalx.migrations")


def _migrate_simulation(sim: dict) -> bool:
    """Wrap a legacy ``metrics`` array into ``containers: [{id: None, ...}]``.

    Returns True if the simulation was modified.
    """
    if "containers" in sim:
        return False
    metrics = sim.get("metrics")
    if not isinstance(metrics, list):
        # Nothing to migrate and no containers either — normalize to empty.
        sim["containers"] = []
        sim.pop("metrics", None)
        return True
    sim["containers"] = [
        {
            "id": None,
            "state": sim.get("state") or "passed",
            "metrics": metrics,
            "revision": None,
        }
    ]
    sim.pop("metrics", None)
    return True


def _migrate_regression_json(path: Path) -> bool:
    """Rewrite a single regression-tests.json file in place if needed.

    Returns True when the file was changed (and a .bak sibling was written on
    the first modification). Safe to call repeatedly — already-migrated files
    are a no-op.
    """
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False

    sims = data.get("simulations") if isinstance(data, dict) else None
    if not isinstance(sims, list):
        return False

    changed = False
    for sim in sims:
        if isinstance(sim, dict) and _migrate_simulation(sim):
            changed = True

    if not changed:
        return False

    backup = path.with_suffix(path.suffix + ".bak")
    if not backup.exists():
        try:
            shutil.copy2(path, backup)
        except OSError:
            pass

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    return True


def migrate_all_regression_json(data_root: Path) -> tuple[int, int]:
    """Walk ``data_root/runs/*/*/*/regression-tests.json`` and migrate each.

    Returns ``(inspected, migrated)``. Errors on individual files are
    swallowed and logged so a single corrupt file cannot break startup.
    """
    runs_root = data_root / "runs"
    if not runs_root.is_dir():
        return 0, 0
    inspected = 0
    migrated = 0
    for path in sorted(runs_root.glob("*/*/*/regression-tests.json")):
        inspected += 1
        try:
            if _migrate_regression_json(path):
                migrated += 1
        except Exception:
            log.exception("regression-tests.json migration failed: %s", path)
    if migrated:
        log.info(
            "regression-tests.json: migrated %d / %d file(s) to the "
            "containers layout.",
            migrated,
            inspected,
        )
    return inspected, migrated
