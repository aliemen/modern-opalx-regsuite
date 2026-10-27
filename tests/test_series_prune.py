import json
import math
import tarfile

import numpy as np

from legacy_plotting import _write_stat_plot
from modern_opalx_regsuite import series
from modern_opalx_regsuite.artifacts import check_run_integrity, write_artifact_manifest
from modern_opalx_regsuite.migration.prune import prune_root
from modern_opalx_regsuite.migration.series_migration import convert_root


def _legacy_run(root, run_id="20260101-000000", *, branch="master", status="passed", bad_metric=None):
    """A pre-series run: two metric SVGs, a beamline SVG, plain logs, a manifest."""
    run = root / "runs" / branch / "cpu-serial" / run_id
    (run / "plots").mkdir(parents=True)
    (run / "logs").mkdir()
    (run / "run-meta.json").write_text(json.dumps({"branch": branch, "arch": "cpu-serial", "run_id": run_id,
                                                   "started_at": "2026-01-01T00:00:00Z", "status": status}))
    (run / "unit-tests.json").write_text(json.dumps({"tests": []}))
    (run / "logs" / "pipeline.log").write_text("pipeline\n" * 100)
    (run / "logs" / "Sim-RT.log").write_text("sim\n" * 100)
    s = list(np.linspace(0.0, 1.0, 500))
    metrics = []
    for name in ("rms_x", "rms_y"):
        y = [1e-3 + 1e-4 * math.sin(7 * v) for v in s]
        _write_stat_plot(s, y, s, y, run / "plots" / f"Sim_{name}.svg", "Sim", name, "m")
        metrics.append({"metric": name, "mode": "last", "state": "passed", "current_value": y[-1] * (3.0 if name == bad_metric else 1.0),
                        "reference_value": y[-1], "plot": f"plots/Sim_{name}.svg"})
    (run / "plots" / "Sim_beamline.svg").write_text("<svg/>")
    reg = {"simulations": [{"name": "Sim", "log_file": "logs/Sim-RT.log",
                            "containers": [{"id": None, "metrics": metrics}]}]}
    (run / "regression-tests.json").write_text(json.dumps(reg))
    write_artifact_manifest(run)
    return run


def _converted_run(root, **kw):
    run = _legacy_run(root, **kw)
    convert_root(root, max_points=100, dry_run=False, only=[run])
    return run


def test_dry_run_counts_and_touches_nothing(tmp_path):
    run = _converted_run(tmp_path / "data")
    before = sorted(p.relative_to(run).as_posix() for p in run.rglob("*"))
    rep = prune_root(tmp_path / "data", backup_dir=tmp_path / "backup", dry_run=True)
    t = rep.totals()
    assert t["runs_dry-run"] == 1 and t["svgs"] == 2 and t["logs"] == 2
    assert sorted(p.relative_to(run).as_posix() for p in run.rglob("*")) == before
    assert not (tmp_path / "backup").exists()


def test_prune_backs_up_deletes_clears_plots_and_gzips_logs(tmp_path):
    run = _converted_run(tmp_path / "data")
    svg_bytes = {p.name: p.read_bytes() for p in (run / "plots").glob("Sim_rms_*.svg")}
    rep = prune_root(tmp_path / "data", backup_dir=tmp_path / "backup", dry_run=False)
    r = rep.runs[0]
    assert r.status == "pruned" and r.svgs == 2 and r.logs == 2

    archive = tmp_path / "backup" / "master" / "cpu-serial" / "20260101-000000-svgs.tar.gz"
    assert r.backup == str(archive)
    with tarfile.open(archive) as tar:
        assert {m.name: tar.extractfile(m).read() for m in tar} == {f"plots/{k}": v for k, v in svg_bytes.items()}

    assert sorted(p.name for p in (run / "plots").iterdir()) == ["Sim_beamline.svg"]
    assert sorted(p.name for p in (run / "logs").iterdir()) == ["Sim-RT.log.gz", "pipeline.log.gz"]
    metrics = json.loads((run / "regression-tests.json").read_text())["simulations"][0]["containers"][0]["metrics"]
    assert all(m["plot"] is None and m["series"] is True for m in metrics)
    assert check_run_integrity(run).status == "ok"

    again = prune_root(tmp_path / "data", backup_dir=tmp_path / "backup", dry_run=False)
    assert again.runs[0].status == "skipped" and again.runs[0].reason == "nothing to prune"


def test_failed_conversion_keeps_svgs_but_gzips_logs(tmp_path):
    run = _converted_run(tmp_path / "data", bad_metric="rms_x")  # stored value disagrees -> rms_x fails
    r = prune_root(tmp_path / "data", backup_dir=tmp_path / "backup", dry_run=False).runs[0]
    assert r.svgs == 0 and r.logs == 2 and "1 plot(s) failed conversion" in r.reason
    assert len(list((run / "plots").glob("Sim_rms_*.svg"))) == 2
    metrics = json.loads((run / "regression-tests.json").read_text())["simulations"][0]["containers"][0]["metrics"]
    assert all(m["plot"] for m in metrics)
    assert not (tmp_path / "backup").exists()


def test_unconverted_run_keeps_svgs(tmp_path):
    run = _legacy_run(tmp_path / "data")
    r = prune_root(tmp_path / "data", backup_dir=tmp_path / "backup", dry_run=False).runs[0]
    assert "not converted" in r.reason and r.svgs == 0
    assert len(list((run / "plots").glob("Sim_rms_*.svg"))) == 2


def test_run_without_report_loses_its_orphan_svgs(tmp_path):
    run = _legacy_run(tmp_path / "data", status="failed")
    (run / "regression-tests.json").unlink()
    r = prune_root(tmp_path / "data", backup_dir=tmp_path / "backup", dry_run=False).runs[0]
    assert r.status == "pruned" and r.svgs == 2
    assert sorted(p.name for p in (run / "plots").iterdir()) == ["Sim_beamline.svg"]


def test_active_runs_are_skipped(tmp_path):
    running = _converted_run(tmp_path / "data", run_id="20260101-000001")
    meta = json.loads((running / "run-meta.json").read_text())
    (running / "run-meta.json").write_text(json.dumps({**meta, "status": "running"}))
    worked = _converted_run(tmp_path / "data", run_id="20260101-000002")
    (worked / "work").mkdir()
    reps = prune_root(tmp_path / "data", backup_dir=tmp_path / "backup", dry_run=False).runs
    assert [r.status for r in reps] == ["skipped", "skipped"]
    assert all("active" in r.reason for r in reps)


def test_rerun_after_interruption_never_overwrites_a_backup(tmp_path):
    run = _converted_run(tmp_path / "data")
    archive = tmp_path / "backup" / "master" / "cpu-serial" / "20260101-000000-svgs.tar.gz"
    archive.parent.mkdir(parents=True)
    with tarfile.open(archive, "w:gz") as tar:  # an older backup holding only one of the two
        tar.add(run / "plots" / "Sim_rms_x.svg", arcname="plots/Sim_rms_x.svg")
    first = archive.read_bytes()
    r = prune_root(tmp_path / "data", backup_dir=tmp_path / "backup", dry_run=False).runs[0]
    assert archive.read_bytes() == first
    assert r.backup.endswith("20260101-000000-svgs-2.tar.gz")
    with tarfile.open(r.backup) as tar:
        assert sorted(tar.getnames()) == ["plots/Sim_rms_x.svg", "plots/Sim_rms_y.svg"]


def test_existing_identical_backup_is_reused(tmp_path):
    run = _converted_run(tmp_path / "data")
    archive = tmp_path / "backup" / "master" / "cpu-serial" / "20260101-000000-svgs.tar.gz"
    archive.parent.mkdir(parents=True)
    with tarfile.open(archive, "w:gz") as tar:
        for p in sorted((run / "plots").glob("Sim_rms_*.svg")):
            tar.add(p, arcname=f"plots/{p.name}")
    r = prune_root(tmp_path / "data", backup_dir=tmp_path / "backup", dry_run=False).runs[0]
    assert r.status == "pruned" and r.backup == str(archive)
    assert sorted(p.name for p in archive.parent.iterdir()) == [archive.name]
