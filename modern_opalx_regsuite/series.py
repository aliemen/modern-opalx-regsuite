"""Plot data of one run, stored as ``<run>/series.json.gz`` (schema 2).

Columnar, so the browser can hand the arrays straight to the chart::

    {"schema": 2, "source": "runner" | "svg", "max_points": N,
     "sims": {<test>: {<container id or "_">: {
         "s": [...], "rs": [...],               # x of current / reference, shared by all metrics
         "m": {<metric>: {
             "cur": [...], "ref": [...],        # y values, same length as their x
             "s": [...], "rs": [...],           # per-metric x; overrides the container's (svg source)
             "d": {"s": [...], "v": [...]}      # current - reference; absent without common s
         }}}}}}

Schema 1 is the layout of regsite's ``tools/pack_run.py`` without ``source``, ``d`` and
per-metric x. ``source: "svg"`` marks data recovered from the SVG plots of runs made before
this format existed (see ``migration/svg_series.py``); those curves were already simplified
by matplotlib and are display copies, not raw ``.stat`` rows.

Values are float64 written losslessly; NaN and infinities become ``null``, which the chart
draws as a gap. Each series keeps at most ``max_points`` rows (0 keeps all). Pass/fail is
always computed from the full ``.stat`` data, never from this file.
"""
from __future__ import annotations

import bisect
import gzip
import json
import math
import os
from pathlib import Path
from typing import Optional, Sequence

SCHEMA = 2
SERIES_FILE = "series.json.gz"
MAX_POINTS = 100

Values = Sequence[Optional[float]]


def nearest_rows(x: Sequence[float], lo: float, hi: float, max_points: int) -> list[int]:
    """Rows of *x* nearest to *max_points* positions evenly spaced from *lo* to *hi*.

    Each row appears once. With ``lo <= x[0]`` and ``hi >= x[-1]`` the first and last rows
    are always kept. When *x* is not ascending, rows evenly spaced by index are returned.
    Ported from regsite's ``tools/pack_run.py`` (plus a guard for ``max_points < 2``), so
    both thin identically.
    """
    n = len(x)
    if not max_points or n <= max_points:
        return list(range(n))
    if max_points < 2 or hi <= lo or any(b < a for a, b in zip(x, x[1:])):
        step = (n - 1) / max(max_points - 1, 1)
        return sorted({round(k * step) for k in range(max_points)})
    rows: list[int] = []
    for k in range(max_points):
        target = lo + k * (hi - lo) / (max_points - 1)
        j = bisect.bisect_left(x, target)
        if j == n or (j > 0 and target - x[j - 1] <= x[j] - target):
            j -= 1
        if not rows or rows[-1] != j:
            rows.append(j)
    return rows


def thin_on_shared_grid(
    s: Sequence[float],
    cur: dict[str, Values],
    rs: Sequence[float],
    ref: dict[str, Values],
    max_points: int,
) -> tuple[list[float], dict[str, list], list[float], dict[str, list]]:
    """Thin a current/reference pair (one or more metrics each) on one grid over both s ranges.

    A shared grid keeps samples the two runs have in common aligned. Rows whose value is
    ``None`` in any metric (gaps) are always kept so a gap never turns into a bridged line.
    """
    if not s or not rs:
        return list(s), {k: list(v) for k, v in cur.items()}, list(rs), {k: list(v) for k, v in ref.items()}
    lo, hi = min(s[0], rs[0]), max(s[-1], rs[-1])
    ci = _with_gaps(nearest_rows(s, lo, hi, max_points), cur.values())
    ri = _with_gaps(nearest_rows(rs, lo, hi, max_points), ref.values())
    return (
        [s[i] for i in ci],
        {k: [v[i] for i in ci] for k, v in cur.items()},
        [rs[i] for i in ri],
        {k: [v[i] for i in ri] for k, v in ref.items()},
    )


def reduce_min_max(x: Sequence[float], y: Values, max_points: int) -> tuple[list[float], list]:
    """Reduce one series to about *max_points* rows, keeping every bucket's extremes.

    The x range is split into ``(max_points - 2) // 2`` buckets; each keeps its minimum and
    maximum row, plus the first and last row overall, so narrow spikes survive (unlike grid
    sampling). Gap rows (``None``) are kept. Buckets are by index when x is not ascending.
    """
    n = len(x)
    if not max_points or n <= max_points:
        return list(x), list(y)
    buckets = max(1, (max_points - 2) // 2)
    ascending = all(b >= a for a, b in zip(x, x[1:])) and x[-1] > x[0]
    keep = {0, n - 1}
    best: dict[int, tuple[int, int]] = {}
    for i in range(n):
        v = y[i]
        if v is None:
            keep.add(i)
            continue
        if ascending:
            b = min(int((x[i] - x[0]) / (x[-1] - x[0]) * buckets), buckets - 1)
        else:
            b = min(i * buckets // n, buckets - 1)
        lo_i, hi_i = best.get(b, (i, i))
        if v < y[lo_i]:
            lo_i = i
        if v > y[hi_i]:
            hi_i = i
        best[b] = (lo_i, hi_i)
    for lo_i, hi_i in best.values():
        keep.update((lo_i, hi_i))
    rows = sorted(keep)
    return [x[i] for i in rows], [y[i] for i in rows]


def common_s_differences(
    s: Sequence[float], values: Sequence[float], ref_s: Sequence[float], ref_values: Sequence[float]
) -> tuple[list[float], list[float]]:
    """current - reference at the s coordinates both series share (relative tolerance 1e-9)."""
    s_common: list[float] = []
    diffs: list[float] = []
    i = j = 0
    n, m = min(len(s), len(values)), min(len(ref_s), len(ref_values))
    while i < n and j < m:
        if math.isclose(s[i], ref_s[j], rel_tol=1e-9, abs_tol=1e-12):
            s_common.append(s[i])
            diffs.append(values[i] - ref_values[j])
            i += 1
            j += 1
        elif s[i] < ref_s[j]:
            i += 1
        else:
            j += 1
    return s_common, diffs


class RunSeriesWriter:
    """Collects the plot data of one run and keeps ``series.json.gz`` current.

    The runner calls :meth:`add` with the full-resolution arrays of every plottable metric
    and :meth:`flush` once per finished simulation, which thins that simulation and rewrites
    the file, so cancelled or crashed runs keep the tests that finished. Only one
    simulation's raw arrays are held at a time.
    """

    def __init__(self, path: Path, max_points: int) -> None:
        self.path = path
        self.max_points = max_points
        self.sims: dict = {}
        self._pending: dict[tuple[str, str], dict] = {}

    def add(
        self,
        test: str,
        container_id: Optional[str],
        metric: str,
        s: Sequence[float],
        cur: Sequence[float],
        rs: Sequence[float],
        ref: Sequence[float],
    ) -> None:
        c = self._pending.setdefault((test, container_id or "_"), {"s": s, "rs": rs, "shared": {}, "own": {}})
        if list(s) == list(c["s"]) and list(rs) == list(c["rs"]):
            c["shared"][metric] = (cur, ref)
        else:
            c["own"][metric] = (s, cur, rs, ref)

    def flush(self, test: str) -> None:
        for (t, cid) in [k for k in self._pending if k[0] == test]:
            c = self._pending.pop((t, cid))
            entry: dict = {"m": {}}
            if c["shared"]:
                s, cur, rs, ref = thin_on_shared_grid(
                    c["s"], {k: v[0] for k, v in c["shared"].items()},
                    c["rs"], {k: v[1] for k, v in c["shared"].items()}, self.max_points,
                )
                entry["s"], entry["rs"] = s, rs
                for name, (full_cur, full_ref) in c["shared"].items():
                    entry["m"][name] = {"cur": clean(cur[name]), "ref": clean(ref[name]),
                                        **self._difference(c["s"], full_cur, c["rs"], full_ref)}
            for name, (ms, mcur, mrs, mref) in c["own"].items():
                s, cur, rs, ref = thin_on_shared_grid(ms, {"v": mcur}, mrs, {"v": mref}, self.max_points)
                entry["m"][name] = {"s": s, "cur": clean(cur["v"]), "rs": rs, "ref": clean(ref["v"]),
                                    **self._difference(ms, mcur, mrs, mref)}
            self.sims.setdefault(t, {})[cid] = entry
        if self.sims:
            write_series(self.path, self.sims, source="runner", max_points=self.max_points)

    def _difference(self, s, cur, rs, ref) -> dict:
        ds, dv = common_s_differences(s, cur, rs, ref)
        if not ds:
            return {}
        ds, dv = reduce_min_max(ds, clean(dv), self.max_points)
        return {"d": {"s": ds, "v": dv}}


def clean(values: Values) -> list[Optional[float]]:
    """Map NaN and infinities to ``None`` so the JSON stays valid."""
    return [None if v is None or not math.isfinite(v) else float(v) for v in values]


def encode_series(sims: dict, *, source: str, max_points: int) -> bytes:
    """Serialize *sims* (the ``sims`` mapping of the layout above) to gzipped JSON bytes.

    ``mtime=0`` keeps the bytes identical for identical data. Raises ``ValueError`` if a
    NaN or infinity slipped past :func:`clean`.
    """
    payload = {"schema": SCHEMA, "source": source, "max_points": max_points, "sims": sims}
    raw = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
    return gzip.compress(raw, compresslevel=9, mtime=0)


def write_series(path: Path, sims: dict, *, source: str, max_points: int) -> int:
    """Write the series file atomically (sibling staging file + ``os.replace``); returns its size."""
    data = encode_series(sims, source=source, max_points=max_points)
    write_bytes_atomic(path, data)
    return len(data)


def read_series(path: Path) -> dict:
    with gzip.open(path, "rb") as f:
        return json.loads(f.read())


def series_schema(path: Path) -> Optional[int]:
    """Schema number of an existing series file, or ``None`` if missing or unreadable."""
    try:
        return int(read_series(path).get("schema", 1))
    except (OSError, ValueError, EOFError):
        return None


def write_bytes_atomic(path: Path, data: bytes) -> None:
    """Replace *path* with *data* so readers see either the old or the new file, never a mix.

    The staging file sits next to the target (same filesystem, also on NFS) and keeps the
    default file mode, unlike ``_atomic_write.write_secret_bytes_atomic``.
    """
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _with_gaps(rows: list[int], series: "Sequence[Values]") -> list[int]:
    gaps = {i for v in series for i, val in enumerate(v) if val is None}
    return sorted(set(rows) | gaps) if gaps else rows
