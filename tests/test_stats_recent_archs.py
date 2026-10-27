import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from modern_opalx_regsuite.api import stats_developer


def _data_root(tmp_path):
    """master on three archs: one ran 2 days ago, one 60 days ago, one only archived runs."""
    now = datetime.now(timezone.utc)

    def entry(run_id, days_ago, archived=False):
        start = now - timedelta(days=days_ago)
        return {"branch": "master", "run_id": run_id, "status": "passed", "regtest_branch": "master",
                "started_at": start.isoformat(), "finished_at": (start + timedelta(minutes=20)).isoformat(),
                "archived": archived}

    indexes = {
        "fresh": [entry("r2", 2), entry("r1", 40)],
        "stale": [entry("s1", 60)],
        "retired": [entry("a1", 1, archived=True)],
    }
    (tmp_path / "branches.json").write_text(json.dumps({"master": list(indexes)}))
    for arch, entries in indexes.items():
        path = tmp_path / "runs-index" / "master" / f"{arch}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([{**e, "arch": arch} for e in entries]))
    return SimpleNamespace(resolved_data_root=tmp_path)


def test_master_cards_leave_out_archs_without_a_recent_active_run(tmp_path):
    cfg = _data_root(tmp_path)
    kw = {"_user": "u", "cfg": cfg, "view": "active"}
    assert [c.arch for c in stats_developer.latest_master(**kw).cells] == ["fresh"]
    assert [c.arch for c in stats_developer.suite_duration(**kw).cells] == ["fresh"]
    assert [e.arch for e in stats_developer.newly_broken(**kw).entries] == ["fresh"]


def test_recent_days_zero_keeps_every_arch(tmp_path):
    cfg = _data_root(tmp_path)
    cells = stats_developer.latest_master(_user="u", cfg=cfg, view="active", recent_days=0).cells
    assert [c.arch for c in cells] == ["fresh", "stale", "retired"]
    assert cells[2].run_id is None  # only archived runs: an empty row, as before
    wide = stats_developer.latest_master(_user="u", cfg=cfg, view="active", recent_days=90).cells
    assert [c.arch for c in wide] == ["fresh", "stale"]
