import json
import math

import numpy as np

from modern_opalx_regsuite import series
from modern_opalx_regsuite.artifacts import MANIFEST_NAME, write_artifact_manifest
from modern_opalx_regsuite.migration.series_migration import convert_root, iter_run_dirs
from legacy_plotting import _write_stat_plot


def _make_run(root, branch="master", arch="cpu-serial", run_id="20260101-000000", *,
              status="passed", curves=None, manifest=True):
    """A run dir with one simulation; *curves* maps metric -> (s, cur, ref, stored_cur, stored_ref)."""
    run = root / "runs" / branch / arch / run_id
    (run / "plots").mkdir(parents=True)
    (run / "run-meta.json").write_text(json.dumps({"branch": branch, "arch": arch, "run_id": run_id,
                                                   "started_at": "2026-01-01T00:00:00Z", "status": status}))
    metrics = []
    for name, (s, cur, ref, stored_cur, stored_ref) in (curves or {}).items():
        _write_stat_plot(s, cur, s, ref, run / "plots" / f"Sim_{name}.svg", "Sim", name, "m")
        metrics.append({"metric": name, "mode": "last", "eps": 1e-6, "delta": 0.0, "state": "passed",
                        "current_value": stored_cur, "reference_value": stored_ref,
                        "plot": f"plots/Sim_{name}.svg"})
    reg = {"simulations": [{"name": "Sim", "containers": [{"id": None, "state": "passed", "metrics": metrics}]}]}
    (run / "regression-tests.json").write_text(json.dumps(reg, indent=2))
    if manifest:
        write_artifact_manifest(run)
    return run


def _sine(n=2000, scale=1e-3, base=2e-3):
    s = list(np.linspace(0.0, 3.0, n))
    y = [base + scale * math.sin(2 * v) for v in s]
    return s, y


def test_dry_run_writes_nothing(tmp_path):
    s, y = _sine()
    run = _make_run(tmp_path, curves={"rms_x": (s, y, y, y[-1], y[-1])})
    before = {p: p.stat().st_mtime_ns for p in run.rglob("*")}
    rep = convert_root(tmp_path, max_points=100, dry_run=True)
    assert rep.totals()["runs_dry-run"] == 1 and rep.totals()["converted"] == 1
    assert {p: p.stat().st_mtime_ns for p in run.rglob("*")} == before


def test_convert_writes_series_flags_and_manifest_and_is_idempotent(tmp_path):
    s, y = _sine()
    ref = [v * 1.01 for v in y]
    run = _make_run(tmp_path, curves={"rms_x": (s, y, ref, y[-1], ref[-1]), "rms_y": (s, ref, y, ref[-1], y[-1])})
    rep = convert_root(tmp_path, max_points=50, dry_run=False)
    t = rep.totals()
    assert t["runs_converted"] == 1 and t["converted"] == 2 and t["verified"] == 4 and t["failed"] == 0

    doc = series.read_series(run / series.SERIES_FILE)
    assert doc["source"] == "svg" and doc["max_points"] == 50
    entry = doc["sims"]["Sim"]["_"]["m"]["rms_x"]
    assert len(entry["s"]) <= 50 and len(entry["s"]) == len(entry["cur"])
    assert len(entry["rs"]) == len(entry["ref"]) and "d" in entry
    assert abs(entry["cur"][-1] - y[-1]) < 1e-9

    reg = json.loads((run / "regression-tests.json").read_text())
    metrics = reg["simulations"][0]["containers"][0]["metrics"]
    assert all(m["series"] is True and m["plot"].endswith(".svg") for m in metrics)
    manifest = json.loads((run / MANIFEST_NAME).read_text())
    assert series.SERIES_FILE in {f["path"] for f in manifest["files"]}

    again = convert_root(tmp_path, max_points=50, dry_run=False)
    assert again.runs[0].status == "skipped" and again.runs[0].reason == "already converted"


def test_flat_curve_with_rounded_offset_is_anchored(tmp_path):
    s = list(np.linspace(0.0, 1.0, 300))
    true_last = 100.0463998719693
    cur = [true_last + 1e-13 * math.sin(7 * v) for v in s]
    cur[-1] = true_last
    run = _make_run(tmp_path, curves={"energy": (s, cur, cur, true_last, true_last)})
    rep = convert_root(tmp_path, max_points=100, dry_run=False)
    r = rep.runs[0]
    assert r.failed == [] and r.converted == 1
    assert r.verified + r.anchored == 2
    entry = series.read_series(run / series.SERIES_FILE)["sims"]["Sim"]["_"]["m"]["energy"]
    assert abs(entry["cur"][-1] - true_last) <= 1e-9 * true_last


def test_mismatching_stored_value_fails_and_keeps_svg(tmp_path):
    s, y = _sine()
    good_s, good_y = _sine(scale=2e-3)
    run = _make_run(tmp_path, curves={"bad": (s, y, y, y[-1] * 3, y[-1]),
                                      "good": (good_s, good_y, good_y, good_y[-1], good_y[-1])})
    rep = convert_root(tmp_path, max_points=100, dry_run=False)
    r = rep.runs[0]
    assert r.converted == 1 and len(r.failed) == 1 and r.failed[0].startswith("Sim:bad")
    metrics = {m["metric"]: m for m in json.loads((run / "regression-tests.json").read_text())
               ["simulations"][0]["containers"][0]["metrics"]}
    assert "series" not in metrics["bad"] and metrics["good"]["series"] is True
    assert (run / "plots" / "Sim_bad.svg").is_file()


def test_nan_stored_value_is_unverifiable(tmp_path):
    s, y = _sine()
    _make_run(tmp_path, curves={"rms_x": (s, y, y, float("nan"), y[-1])})
    r = convert_root(tmp_path, max_points=100, dry_run=False).runs[0]
    assert r.unverifiable == 1 and r.verified == 1 and r.converted == 1


def test_skips_active_runs_and_counts_unreferenced_svgs(tmp_path):
    s, y = _sine()
    _make_run(tmp_path, run_id="20260101-000001", status="running", curves={"a": (s, y, y, y[-1], y[-1])})
    worked = _make_run(tmp_path, run_id="20260101-000002", curves={"a": (s, y, y, y[-1], y[-1])})
    (worked / "work").mkdir()
    orphan = _make_run(tmp_path, run_id="20260101-000003", status="failed", curves={"a": (s, y, y, y[-1], y[-1])})
    (orphan / "regression-tests.json").unlink()
    extra = _make_run(tmp_path, run_id="20260101-000004", curves={"a": (s, y, y, y[-1], y[-1])})
    (extra / "plots" / "Stray_x.svg").write_text((extra / "plots" / "Sim_a.svg").read_text())
    (extra / "plots" / "Sim_beamline.svg").write_text("<svg/>")

    by_id = {r.run.rsplit("/", 1)[-1]: r for r in convert_root(tmp_path, max_points=100, dry_run=False).runs}
    assert by_id["20260101-000001"].status == "skipped" and "active" in by_id["20260101-000001"].reason
    assert by_id["20260101-000002"].status == "skipped" and "work/" in by_id["20260101-000002"].reason
    assert by_id["20260101-000003"].reason == "no regression-tests.json"
    assert by_id["20260101-000003"].unreferenced_svgs == 1
    assert by_id["20260101-000004"].status == "converted" and by_id["20260101-000004"].unreferenced_svgs == 1


def test_finds_runs_of_branches_with_slashes(tmp_path):
    s, y = _sine()
    _make_run(tmp_path, branch="v1-fix/spin-step-order", curves={"a": (s, y, y, y[-1], y[-1])})
    _make_run(tmp_path, branch="master", curves={"a": (s, y, y, y[-1], y[-1])})
    found = [p.relative_to(tmp_path).as_posix() for p in iter_run_dirs(tmp_path)]
    assert found == ["runs/master/cpu-serial/20260101-000000",
                     "runs/v1-fix/spin-step-order/cpu-serial/20260101-000000"]


FIXTURES = __import__("pathlib").Path(__file__).parent / "fixtures" / "legacy_svg"


def _run_with_real_svg(root, svg_name, sim, metric, stored_cur, stored_ref):
    run = root / "runs" / "master" / "cpu-serial" / "20260420-152730"
    (run / "plots").mkdir(parents=True)
    (run / "plots" / svg_name).write_text((FIXTURES / svg_name).read_text())
    (run / "run-meta.json").write_text(json.dumps({"status": "passed"}))
    reg = {"simulations": [{"name": sim, "containers": [{"id": None, "metrics": [
        {"metric": metric, "mode": "avg", "state": "passed", "current_value": stored_cur,
         "reference_value": stored_ref, "plot": f"plots/{svg_name}"}]}]}]}
    (run / "regression-tests.json").write_text(json.dumps(reg))
    return run


def test_real_production_svg_converts_verified(tmp_path):
    run = _run_with_real_svg(tmp_path, "RFCavity_emit_x.svg", "RFCavity", "emit_x",
                             4.197484276978961e-09, 4.19748676518746e-09)
    r = convert_root(tmp_path, max_points=100, dry_run=False).runs[0]
    assert (r.converted, r.verified, r.failed) == (1, 2, [])
    entry = series.read_series(run / series.SERIES_FILE)["sims"]["RFCavity"]["_"]["m"]["emit_x"]
    assert len(entry["s"]) <= 100 and entry["d"]["v"]


def test_real_flat_svg_with_rounded_offset_is_anchored(tmp_path):
    # Production plot whose axis spans ~2e-11 around 100.046 MeV; matplotlib printed the
    # offset as 1.000463999e2, so the recovered level is off by ~3e-8 until anchored.
    cur, ref = 100.0463998719892, 100.0463998719693
    run = _run_with_real_svg(tmp_path, "Solenoid-1-fromfile_energy.svg", "Solenoid-1-fromfile", "energy", cur, ref)
    r = convert_root(tmp_path, max_points=100, dry_run=False).runs[0]
    assert r.failed == [] and r.anchored == 2
    entry = series.read_series(run / series.SERIES_FILE)["sims"]["Solenoid-1-fromfile"]["_"]["m"]["energy"]
    assert entry["cur"][-1] == cur and entry["ref"][-1] == ref
