"""Convert the metric SVGs of stored runs into ``series.json.gz`` (``source: "svg"``).

Works on one root at a time (``data_root`` or ``archive_root``); both hold plain run
directories ``runs/<branch>/<arch>/<run_id>/``, where ``<branch>`` may contain ``/``.

Per run the conversion only adds data, so the release before this format can still read
every run: it writes ``series.json.gz``, sets ``series: true`` on each converted metric in
``regression-tests.json`` (``plot`` is kept), and rebuilds an existing
``artifact-manifest.json``. SVGs and logs are left alone. Re-running skips runs that already
have a schema-2 series file. Runs that look active (status ``running``/``queued`` or a
``work/`` directory) are skipped; the web service should be stopped while this runs.

Every recovered current/reference curve is checked against the ``current_value`` /
``reference_value`` stored for its metric:

* ``verified``: last point within ``VERIFY_SPAN`` of the plot's value-axis range.
* ``anchored``: the axis carried an additive offset text, which matplotlib rounds to about
  10 significant digits; on curves flatter than that rounding the whole curve is shifted so
  its last point equals the stored value (allowed while within ``ANCHOR_VALUE`` relative).
* ``unverifiable``: the stored value is missing or NaN; the curve is kept as recovered.
* ``failed``: anything else. The metric gets no series and keeps its SVG.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator, Optional

from .. import series as series_mod
from ..artifacts import MANIFEST_NAME, write_artifact_manifest
from .svg_series import Curve, StatPlot, SvgFormatError, parse_stat_svg

VERIFY_SPAN = 1e-4
ANCHOR_VALUE = 1e-6
_ACTIVE_STATUSES = {"running", "queued"}


@dataclass
class RunReport:
    run: str  # path relative to the root, e.g. "runs/master/cpu-serial/20261027-124206"
    status: str  # converted | dry-run | skipped | error
    reason: str = ""
    plots: int = 0
    converted: int = 0
    verified: int = 0
    anchored: int = 0
    unverifiable: int = 0
    failed: list[str] = field(default_factory=list)  # "<test>[<cid>]:<metric>: <reason>"
    unreferenced_svgs: int = 0
    svg_bytes: int = 0  # referenced SVGs that were converted
    series_bytes: int = 0


@dataclass
class MigrationReport:
    root: str
    dry_run: bool
    max_points: int
    runs: list[RunReport] = field(default_factory=list)

    def totals(self) -> dict:
        t: dict = {"runs": len(self.runs)}
        for r in self.runs:
            t[f"runs_{r.status}"] = t.get(f"runs_{r.status}", 0) + 1
            for key in ("plots", "converted", "verified", "anchored", "unverifiable",
                        "unreferenced_svgs", "svg_bytes", "series_bytes"):
                t[key] = t.get(key, 0) + getattr(r, key)
            t["failed"] = t.get("failed", 0) + len(r.failed)
        return t

    def to_json(self) -> str:
        return json.dumps(
            {"root": self.root, "dry_run": self.dry_run, "max_points": self.max_points,
             "totals": self.totals(), "runs": [asdict(r) for r in self.runs]},
            indent=2,
        )


def iter_run_dirs(root: Path) -> Iterator[Path]:
    """Every run directory under ``root/runs``, found by its ``run-meta.json`` at any depth."""
    runs = root / "runs"
    if not runs.is_dir():
        return
    for meta in sorted(runs.rglob("run-meta.json")):
        if "work" not in meta.relative_to(runs).parts[:-1]:
            yield meta.parent


def convert_root(root: Path, *, max_points: int, dry_run: bool,
                 only: Optional[list[Path]] = None, progress=None) -> MigrationReport:
    report = MigrationReport(root=str(root), dry_run=dry_run, max_points=max_points)
    for run_root in (only if only is not None else iter_run_dirs(root)):
        try:
            r = convert_run(run_root, root=root, max_points=max_points, dry_run=dry_run)
        except Exception as exc:  # one broken run must not stop the batch
            r = RunReport(run=_rel(run_root, root), status="error", reason=f"{type(exc).__name__}: {exc}")
        report.runs.append(r)
        if progress is not None:
            progress(r)
    return report


def convert_run(run_root: Path, *, root: Path, max_points: int, dry_run: bool) -> RunReport:
    rep = RunReport(run=_rel(run_root, root), status="skipped")
    meta_path, reg_path = run_root / "run-meta.json", run_root / "regression-tests.json"
    series_path = run_root / series_mod.SERIES_FILE
    if not meta_path.is_file():
        rep.reason = "no run-meta.json"
        return rep
    status = str(json.loads(meta_path.read_text(encoding="utf-8")).get("status", "")).lower()
    if status in _ACTIVE_STATUSES or (run_root / "work").exists():
        rep.reason = f"looks active (status {status or '?'}{', work/ present' if (run_root / 'work').exists() else ''})"
        return rep
    if series_path.exists() and (series_mod.series_schema(series_path) or 0) >= series_mod.SCHEMA:
        rep.reason = "already converted"
        return rep

    stat_svgs = {p.name for p in (run_root / "plots").glob("*.svg") if not p.name.endswith("_beamline.svg")}
    if not reg_path.is_file():
        rep.unreferenced_svgs = len(stat_svgs)
        rep.reason = "no regression-tests.json"
        return rep

    reg = json.loads(reg_path.read_text(encoding="utf-8"))
    sims: dict = {}
    referenced: set[str] = set()
    for sim in reg.get("simulations", []):
        for container in sim.get("containers", []):
            cid = container.get("id") or "_"
            for metric in container.get("metrics", []):
                plot = metric.get("plot")
                if not plot:
                    continue
                rep.plots += 1
                tag = f"{sim.get('name')}{'' if cid == '_' else f'[{cid}]'}:{metric.get('metric')}"
                svg = _safe_plot_path(run_root, plot)
                if svg is None or not svg.is_file():
                    rep.failed.append(f"{tag}: plot file missing or outside the run ({plot})")
                    continue
                referenced.add(svg.name)
                entry, outcome = _convert_metric(svg, metric, max_points)
                if entry is None:
                    rep.failed.append(f"{tag}: {outcome}")
                    continue
                for o in outcome.split(","):
                    setattr(rep, o, getattr(rep, o) + 1)
                rep.converted += 1
                rep.svg_bytes += svg.stat().st_size
                sims.setdefault(sim["name"], {}).setdefault(cid, {"m": {}})["m"][metric["metric"]] = entry
                metric["series"] = True
    rep.unreferenced_svgs = len(stat_svgs - referenced)

    if not rep.converted:
        rep.reason = "no plot converted" if rep.plots else "no plots"
        return rep
    data = series_mod.encode_series(sims, source="svg", max_points=max_points)
    rep.series_bytes = len(data)
    if dry_run:
        rep.status = "dry-run"
        return rep
    series_mod.write_bytes_atomic(series_path, data)
    series_mod.write_bytes_atomic(reg_path, json.dumps(reg, indent=2, default=str).encode("utf-8"))
    if (run_root / MANIFEST_NAME).is_file():
        write_artifact_manifest(run_root)
    rep.status = "converted"
    return rep


def _convert_metric(svg: Path, metric: dict, max_points: int) -> tuple[Optional[dict], str]:
    """Series entry for one metric and a comma-joined outcome per curve, or (None, reason)."""
    try:
        plot = parse_stat_svg(svg.read_text(encoding="utf-8", errors="replace"))
    except SvgFormatError as exc:
        return None, f"unreadable SVG: {exc}"
    if plot.current is None or plot.reference is None:
        return None, "SVG lacks the current or reference curve"
    outcomes = []
    for curve, key in ((plot.current, "current_value"), (plot.reference, "reference_value")):
        outcome = _verify(curve, metric.get(key), plot)
        if outcome.startswith("failed"):
            return None, f"{key.split('_')[0]} curve {outcome}"
        outcomes.append(outcome)

    cur, ref = plot.current, plot.reference
    s, c, rs, r = series_mod.thin_on_shared_grid(cur.x, {"v": cur.y}, ref.x, {"v": ref.y}, max_points)
    entry = {"s": s, "cur": series_mod.clean(c["v"]), "rs": rs, "ref": series_mod.clean(r["v"])}
    if plot.difference is not None:
        ds, dv = series_mod.reduce_min_max(plot.difference.x, plot.difference.y, max_points)
        entry["d"] = {"s": ds, "v": series_mod.clean(dv)}
    return entry, ",".join(outcomes)


def _verify(curve: Curve, stored, plot: StatPlot) -> str:
    """Check (and maybe anchor in place) one curve; see the module docstring."""
    if stored is None or (isinstance(stored, float) and math.isnan(stored)):
        return "unverifiable"
    last = curve.last
    if last is None:
        return "unverifiable"
    err = abs(last - stored)
    if err <= VERIFY_SPAN * plot.y_span:
        return "verified"
    if plot.y.has_offset and err <= ANCHOR_VALUE * max(abs(stored), 1e-300):
        shift = stored - last
        curve.y = [None if v is None else v + shift for v in curve.y]
        return "anchored"
    return f"failed verification (last {last!r} vs stored {stored!r}, axis range {plot.y_span:.3g})"


def _safe_plot_path(run_root: Path, rel: str) -> Optional[Path]:
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts or not p.parts or p.parts[0] != "plots":
        return None
    return run_root / p


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)
