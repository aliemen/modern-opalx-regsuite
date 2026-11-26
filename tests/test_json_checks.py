"""JSON value checks: .rt parsing, value lookup, verdicts, discovery and remote fetching."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import pytest

from modern_opalx_regsuite.config import Connection, SuiteConfig
from modern_opalx_regsuite.rt_checks import json_value, parse_rt_text
from modern_opalx_regsuite.runner import regression_runner
from modern_opalx_regsuite.runner.execution import _ensure_run_paths
from modern_opalx_regsuite.runner.parsing.regression import (
    _discover_regression_tests,
    _discover_regression_tests_remote,
)
from modern_opalx_regsuite.runner.regression_results import _build_simulation

TUNE = "root.orbits.0.optics.full_tunes.vertical"


def _orbit(tune: Optional[float]) -> dict:
    tunes = {} if tune is None else {"vertical": tune}
    return {"orbits": [{"optics": {"full_tunes": tunes}}]}


def _stat(rms_s: float) -> str:
    return f"""SDDS1
&column name=t, units=s, type=double, &end
&column name=s, units=m, type=double, &end
&column name=rms_s, units=m, type=double, &end
&data mode=ascii, &end
0.0 0.0 0.001
1e-9 0.1 {rms_s}
"""


def _simulate(
    tmp_path: Path,
    rt: str,
    rc: int = 0,
    new: Optional[dict] = None,
    ref: Optional[dict] = None,
    stats: Optional[tuple[float, float]] = None,
):
    """Build the result of test "T" from a work dir and a reference dir."""
    work, reference = tmp_path / "work", tmp_path / "reference"
    work.mkdir()
    reference.mkdir()
    (work / "T.rt").write_text(rt, encoding="utf-8")
    if new is not None:
        (work / "orbit.json").write_text(json.dumps(new), encoding="utf-8")
    if ref is not None:
        (reference / "orbit.json").write_text(json.dumps(ref), encoding="utf-8")
    if stats is not None:
        (work / "T.stat").write_text(_stat(stats[0]), encoding="utf-8")
        (reference / "T.stat").write_text(_stat(stats[1]), encoding="utf-8")
    return _build_simulation(
        test_name="T",
        rc=rc,
        rt_file=work / "T.rt",
        work_test_dir=work,
        reference_dir=reference,
        plots_dir=tmp_path / "plots",
        pipeline_log_path=tmp_path / "pipeline.log",
        test_start=time.monotonic(),
        log_path=tmp_path / "T-RT.log",
    )


def test_parse_rt_text_reads_both_kinds_strips_comments_and_reports_bad_lines() -> None:
    rt = parse_rt_text(
        '"Checks"\n'
        'stat "rms_x" last 1e-5 # m: trailing comment\n'
        f"orbit.json {TUNE} 1e-9\n"
        'orbit.json "root.orbits.0.solution.section_coordinates.1" 1e-9 # quoted path\n'
        "# a comment line\n"
        'stat "rms_y" last abc\n'
        "../orbit.json root.a 1e-9\n"
        "data/orbit.json root.a 1e-9\n"
        "stat rms_z last 1e-5\n"
    )
    assert rt.description == "Checks"
    assert rt.stat == [("rms_x", "last", 1e-5)]
    assert rt.json == [
        ("orbit.json", TUNE, 1e-9),
        ("orbit.json", "root.orbits.0.solution.section_coordinates.1", 1e-9),
    ]
    assert rt.invalid == [
        'stat "rms_y" last abc',
        "../orbit.json root.a 1e-9",
        "data/orbit.json root.a 1e-9",
        "stat rms_z last 1e-5",
    ]


def test_json_value_resolves_keys_and_indices_and_rejects_non_numbers() -> None:
    doc = {"a": [1, 2.5, True, "s", float("nan")], "b": {"c": 3}}
    assert json_value(doc, "root.a.1") == 2.5
    assert json_value(doc, "root.b.c") == 3.0
    for path in ("root.a.5", "root.a.-1", "root.a.2", "root.a.3", "root.a.4", "a.1", "root", "root.x"):
        assert json_value(doc, path) is None, path


@pytest.mark.parametrize(
    ("rc", "new", "ref", "state"),
    [
        (0, _orbit(1.6895), _orbit(1.6895), "passed"),
        (0, _orbit(1.6895 + 2e-9), _orbit(1.6895), "failed"),
        (0, _orbit(1.6895), None, "broken"),         # no reference file: the test is wrong
        (0, _orbit(1.6895), _orbit(None), "broken"),  # no reference value
        (0, None, _orbit(1.6895), "failed"),          # the run wrote no file
        (0, _orbit(None), _orbit(1.6895), "failed"),  # e.g. COF reports tunes unavailable
        (1, None, _orbit(1.6895), "failed"),
        (-9, None, _orbit(1.6895), "crashed"),
    ],
)
def test_json_only_test_gets_one_container_per_file_and_no_presence_check(
    tmp_path: Path, rc: int, new: Optional[dict], ref: Optional[dict], state: str
) -> None:
    sim = _simulate(tmp_path, f'"T"\norbit.json {TUNE} 1e-9\n', rc=rc, new=new, ref=ref)
    assert [c.id for c in sim.containers] == ["orbit.json"]
    (m,) = sim.containers[0].metrics
    assert (m.metric, m.mode, m.eps, m.series, m.state) == (TUNE, "json", 1e-9, False, state)
    assert sim.state == state


def test_mixed_test_keeps_stat_container_first_and_reports_bad_rt_lines(tmp_path: Path) -> None:
    sim = _simulate(
        tmp_path,
        f'"T"\nstat "rms_s" last 1e-9\norbit.json {TUNE} 1e-9\nstat rms_x last 1e-5\n',
        new=_orbit(1.0),
        ref=_orbit(1.0),
        stats=(0.002, 0.002),
    )
    assert [c.id for c in sim.containers] == [None, "orbit.json", "T.rt"]
    assert [c.state for c in sim.containers] == ["passed", "passed", "broken"]
    assert sim.containers[2].metrics[0].mode == "invalid"
    assert sim.state == "broken"


def test_local_discovery_accepts_a_json_only_reference(tmp_path: Path) -> None:
    for name, ref_file in (("JsonOnly", "orbit.json"), ("NoReference", None)):
        d = tmp_path / name
        (d / "reference").mkdir(parents=True)
        (d / f"{name}.in").write_text("QUIT;\n", encoding="utf-8")
        if ref_file:
            (d / "reference" / ref_file).write_text("{}", encoding="utf-8")
    assert _discover_regression_tests(tmp_path) == ["JsonOnly"]


class _Res:
    def __init__(self, stdout: str = "") -> None:
        self.return_code = 0
        self.stdout = stdout


class _Conn:
    def __init__(self, stdout: str = "") -> None:
        self.stdout = stdout
        self.commands: list[str] = []

    def run(self, cmd: str, **_kwargs) -> _Res:
        self.commands.append(cmd)
        return _Res(self.stdout)


def test_remote_discovery_accepts_a_json_only_reference() -> None:
    root = "/r/RegressionTests"
    listing = [f"{root}/J", f"{root}/J/J.in", f"{root}/J/reference/orbit.json", f"{root}/N", f"{root}/N/N.in"]

    class _Remote:
        conn = _Conn("\n".join(listing))

    remote = _Remote()
    assert _discover_regression_tests_remote(remote, root) == ["J"]
    assert "-path '*/reference/*.json'" in remote.conn.commands[0]


class _FetchingRemote:
    """Serves the .rt and both orbit.json files of test "J"; everything else is absent."""

    def __init__(self, files: dict[str, str]) -> None:
        self.files = files
        self.fetched: list[str] = []
        self.conn = _Conn()

    def ensure_dir(self, _path: str) -> None:
        pass

    def run_command(self, _cmd: str, **_kwargs) -> int:
        return 0

    def fetch_file_status(self, remote: str, local: Path):
        self.fetched.append(remote)
        if remote not in self.files:
            return ("absent", None)
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(self.files[remote], encoding="utf-8")
        return ("fetched", None)

    def fetch_file(self, remote: str, _local: Path) -> None:
        raise FileNotFoundError(remote)


def test_remote_runner_fetches_the_json_files_named_in_the_rt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src, work = "/r/regtests/RegressionTests/J", "/r/work/run-3/J"
    remote = _FetchingRemote(
        {
            f"{src}/J.rt": f'"J"\norbit.json {TUNE} 1e-9\n',
            f"{work}/orbit.json": json.dumps(_orbit(1.5)),
            f"{src}/reference/orbit.json": json.dumps(_orbit(1.5)),
        }
    )
    monkeypatch.setattr(regression_runner, "_discover_regression_tests_remote", lambda _r, _root: ["J"])
    paths = _ensure_run_paths(tmp_path / "data", "master", "gpu", "run-3")
    cfg = SuiteConfig(
        opalx_repo_root=tmp_path / "opalx",
        builds_root=tmp_path / "builds",
        data_root=tmp_path / "data",
        regtests_repo_root=tmp_path / "regtests",
    )

    report = regression_runner._run_regression_suite_remote(
        cfg=cfg,
        paths=paths,
        connection=Connection(name="daint", host="daint.example", user="runner", key_name="k", work_dir="/r"),
        mpi_ranks=1,
        opalx_info_level=2,
        use_slurm=True,
        slurm_step_args=None,
        remote=remote,
        remote_base="/r",
        remote_build="/r/build",
        run_id="run-3",
        pipeline_log_path=paths.pipeline_log_path,
    )

    assert f"{work}/orbit.json" in remote.fetched
    assert f"{src}/reference/orbit.json" in remote.fetched
    (sim,) = report.simulations
    assert [(c.id, c.state) for c in sim.containers] == [("orbit.json", "passed")]
    assert sim.state == "passed"
