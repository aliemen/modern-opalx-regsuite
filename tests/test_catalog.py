from __future__ import annotations

import subprocess
from pathlib import Path

from modern_opalx_regsuite.catalog import list_catalog_tests


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def test_catalog_parses_branch_tree_without_checkout(tmp_path: Path) -> None:
    repo = tmp_path / "regression-tests-x"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/master")
    _git(repo, "config", "user.email", "demo@example.invalid")
    _git(repo, "config", "user.name", "Demo")

    test_root = repo / "RegressionTests" / "Multi"
    (test_root / "reference").mkdir(parents=True)
    (test_root / "Multi.in").write_text("OPTION;\n", encoding="utf-8")
    (test_root / "Multi.local").write_text("#!/bin/sh\n", encoding="utf-8")
    (test_root / "Multi.rt").write_text(
        '"Multi container test."\nstat "rms_x" avg 1E-5\n',
        encoding="utf-8",
    )
    (test_root / "reference" / "Multi_c0.stat").write_text("SDDS\n", encoding="utf-8")
    (test_root / "reference" / "Multi_c1.stat").write_text("SDDS\n", encoding="utf-8")
    disabled = repo / "disabledTests" / "Disabled"
    disabled.mkdir(parents=True)
    (disabled / "Disabled.in").write_text("OPTION;\n", encoding="utf-8")
    (disabled / "Disabled.rt").write_text('"Disabled."\n', encoding="utf-8")

    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixtures")

    report = list_catalog_tests(
        repo,
        "master",
        include_disabled=True,
        last_status_by_name={"Multi": "passed"},
        last_run_by_name={"Multi": "run-1"},
        repo_url="git@github.com:OPALX-project/regression-tests-x.git",
    )
    by_name = {test.name: test for test in report.tests}

    assert report.commit_url == f"https://github.com/OPALX-project/regression-tests-x/commit/{report.commit}"
    assert by_name["Multi"].enabled is True
    assert by_name["Multi"].description == "Multi container test."
    assert by_name["Multi"].metrics[0].metric == "rms_x"
    assert by_name["Multi"].reference_stat_count == 2
    assert by_name["Multi"].multi_container_refs == ["Multi_c0.stat", "Multi_c1.stat"]
    assert by_name["Multi"].last_status == "passed"
    assert by_name["Multi"].last_run_id == "run-1"
    assert by_name["Disabled"].enabled is False
