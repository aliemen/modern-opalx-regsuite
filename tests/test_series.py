import gzip
import json
import math

import pytest

from modern_opalx_regsuite import series


def test_nearest_rows_keeps_ends_and_limit():
    x = [i * 0.01 for i in range(1000)]
    rows = series.nearest_rows(x, x[0], x[-1], 100)
    assert rows[0] == 0 and rows[-1] == 999
    assert len(rows) <= 100
    assert rows == sorted(set(rows))


def test_nearest_rows_short_or_unlimited_keeps_all():
    x = [0.0, 1.0, 2.0]
    assert series.nearest_rows(x, 0.0, 2.0, 100) == [0, 1, 2]
    assert series.nearest_rows(list(range(500)), 0, 499, 0) == list(range(500))


def test_nearest_rows_non_monotonic_falls_back_to_index_spacing():
    x = [float(i % 7) for i in range(300)]
    rows = series.nearest_rows(x, 0.0, 6.0, 10)
    assert rows[0] == 0 and rows[-1] == 299 and len(rows) == 10


def test_shared_grid_keeps_identical_runs_aligned():
    s = [i * 0.5 for i in range(2001)]
    y = [math.sin(v) for v in s]
    ts, cur, trs, ref = series.thin_on_shared_grid(s, {"a": y}, s, {"a": y}, 100)
    assert ts == trs
    assert cur["a"] == ref["a"]
    assert len(ts) <= 100


def test_shared_grid_keeps_gap_rows():
    s = [float(i) for i in range(1000)]
    y = [1.0] * 1000
    y[333] = None
    ts, cur, _, _ = series.thin_on_shared_grid(s, {"a": y}, s, {"a": [1.0] * 1000}, 50)
    assert 333.0 in ts and cur["a"][ts.index(333.0)] is None


def test_reduce_min_max_keeps_a_one_row_spike():
    x = [i * 1e-3 for i in range(10_000)]
    y = [0.0] * 10_000
    y[4321] = 5.0
    y[7777] = -3.0
    rx, ry = series.reduce_min_max(x, y, 100)
    assert len(rx) <= 100
    assert 5.0 in ry and -3.0 in ry
    assert rx[0] == x[0] and rx[-1] == x[-1]
    assert rx == sorted(rx)


def test_clean_maps_non_finite_to_none():
    assert series.clean([1.0, float("nan"), float("inf"), None, -2]) == [1.0, None, None, None, -2.0]


def test_encode_is_deterministic_and_rejects_nan():
    sims = {"T": {"_": {"m": {"x": {"s": [0.0, 1.0], "cur": [1.0, None]}}}}}
    a = series.encode_series(sims, source="svg", max_points=100)
    assert a == series.encode_series(sims, source="svg", max_points=100)
    doc = json.loads(gzip.decompress(a))
    assert doc["schema"] == series.SCHEMA and doc["source"] == "svg" and doc["max_points"] == 100
    assert doc["sims"]["T"]["_"]["m"]["x"]["cur"] == [1.0, None]
    with pytest.raises(ValueError):
        series.encode_series({"T": {"_": {"m": {"x": {"cur": [float("nan")]}}}}}, source="svg", max_points=0)


def test_write_series_atomic_roundtrip(tmp_path):
    path = tmp_path / series.SERIES_FILE
    size = series.write_series(path, {"T": {}}, source="runner", max_points=10)
    assert size == path.stat().st_size
    assert series.read_series(path)["sims"] == {"T": {}}
    assert series.series_schema(path) == series.SCHEMA
    assert series.series_schema(tmp_path / "missing.json.gz") is None
    assert [p.name for p in tmp_path.iterdir()] == [series.SERIES_FILE]
