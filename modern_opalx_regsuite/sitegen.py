from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .data_model import (
    RunIndexEntry,
    branches_index_path,
    runs_index_path,
)


TEMPLATES_DIR_NAME = "templates"


@dataclass
class RunSummary:
    branch: str
    arch: str
    run_id: str
    status: str
    started_at: str
    finished_at: str | None
    unit_tests_failed: int
    regression_failed: int
    regression_broken: int


def _load_jinja_env(package_root: Path) -> Environment:
    templates_dir = package_root / TEMPLATES_DIR_NAME
    loader = FileSystemLoader(str(templates_dir))
    env = Environment(
        loader=loader,
        autoescape=select_autoescape(["html", "xml"]),
    )
    return env


def _load_branches(data_root: Path) -> Dict[str, List[str]]:
    path = branches_index_path(data_root)
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    # raw is {branch: [arch1, arch2, ...]}
    return {str(k): list(v) for k, v in raw.items()}


def _load_runs_for_arch(data_root: Path, branch: str, arch: str) -> List[RunSummary]:
    idx_path = runs_index_path(data_root, branch, arch)
    if not idx_path.is_file():
        return []
    with idx_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    entries = [RunIndexEntry.model_validate(e) for e in raw]
    return [
        RunSummary(
            branch=e.branch,
            arch=e.arch,
            run_id=e.run_id,
            status=e.status,
            started_at=e.started_at.isoformat(),
            finished_at=e.finished_at.isoformat() if e.finished_at else None,
            unit_tests_failed=e.unit_tests_failed,
            regression_failed=e.regression_failed,
            regression_broken=e.regression_broken,
        )
        for e in entries
    ]


def generate_site(
    data_root: Path,
    out_dir: Path,
    package_root: Path,
) -> None:
    """Generate a static site from the JSON data tree."""
    env = _load_jinja_env(package_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    branches = _load_branches(data_root)

    # Global index: overview of latest run per branch/arch.
    index_tmpl = env.get_template("index.html.j2")
    latest: list[RunSummary] = []
    for branch, archs in branches.items():
        for arch in archs:
            runs = _load_runs_for_arch(data_root, branch, arch)
            if runs:
                latest.append(runs[0])

    latest.sort(key=lambda r: r.started_at, reverse=True)

    index_html = index_tmpl.render(latest_runs=latest)
    (out_dir / "index.html").write_text(index_html, encoding="utf-8")

    # Per-branch pages.
    branch_tmpl = env.get_template("branch.html.j2")
    run_tmpl = env.get_template("run.html.j2")

    for branch, archs in branches.items():
        branch_dir = out_dir / "branch" / branch
        branch_dir.mkdir(parents=True, exist_ok=True)

        branch_runs_by_arch: dict[str, list[RunSummary]] = {}
        for arch in archs:
            branch_runs_by_arch[arch] = _load_runs_for_arch(data_root, branch, arch)

        branch_html = branch_tmpl.render(
            branch=branch,
            runs_by_arch=branch_runs_by_arch,
        )
        (branch_dir / "index.html").write_text(branch_html, encoding="utf-8")

        # Run detail pages.
        for arch, runs in branch_runs_by_arch.items():
            for r in runs:
                run_dir = branch_dir / arch / r.run_id
                run_dir.mkdir(parents=True, exist_ok=True)

                # Load detailed JSON files for this run.
                run_root = data_root / "runs" / branch / arch / r.run_id
                meta = json.loads((run_root / "run-meta.json").read_text("utf-8"))
                unit = json.loads((run_root / "unit-tests.json").read_text("utf-8"))
                reg = json.loads(
                    (run_root / "regression-tests.json").read_text("utf-8")
                )

                run_html = run_tmpl.render(
                    meta=meta,
                    unit=unit,
                    regression=reg,
                    branch=branch,
                    arch=arch,
                    run_id=r.run_id,
                )
                (run_dir / "index.html").write_text(run_html, encoding="utf-8")

