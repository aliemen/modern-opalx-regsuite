from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from .archive_service import filter_entries_by_view
from .data_model import RegressionSimulation, RegressionTestsReport, run_dir, runs_index_path


BAD_STATES = {"failed", "broken", "crashed"}
GOOD_STATES = {"passed"}


class FlakySimulation(BaseModel):
    name: str
    observations: int
    passed: int
    failed: int
    broken: int
    crashed: int
    latest_status: Optional[str] = None
    latest_run_id: Optional[str] = None


class FlakinessReport(BaseModel):
    branch: str
    arch: str
    regtests_branch: str
    limit: int
    min_observations: int
    runs_considered: int
    simulations: list[FlakySimulation] = Field(default_factory=list)


def _load_index(
    data_root: Path,
    branch: str,
    arch: str,
    regtests_branch: str,
    limit: int,
) -> list[dict]:
    path = runs_index_path(data_root, branch, arch)
    if not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(raw, list):
        return []
    entries = filter_entries_by_view(raw, "active")
    completed = [
        e
        for e in entries
        if e.get("status") in {"passed", "failed"}
        and (e.get("regtest_branch") or "master") == regtests_branch
    ]
    return completed[:limit]


def _load_report(
    data_root: Path,
    branch: str,
    arch: str,
    run_id: str,
) -> Optional[RegressionTestsReport]:
    path = run_dir(data_root, branch, arch, run_id) / "regression-tests.json"
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        return RegressionTestsReport.model_validate(raw)
    except Exception:
        return None


def simulation_outcome(sim: RegressionSimulation) -> str:
    state = (sim.state or "").lower()
    if state in BAD_STATES:
        return state
    seen_good = state in GOOD_STATES
    for container in sim.containers:
        c_state = (container.state or "").lower()
        if c_state in BAD_STATES:
            return c_state
        if c_state in GOOD_STATES:
            seen_good = True
        for metric in container.metrics:
            m_state = (metric.state or "").lower()
            if m_state in BAD_STATES:
                return m_state
            if m_state in GOOD_STATES:
                seen_good = True
    return "passed" if seen_good else (state or "unknown")


def latest_simulation_results(
    data_root: Path,
    branch: str,
    arch: str,
    regtests_branch: str,
) -> dict[str, tuple[str, str]]:
    entries = _load_index(data_root, branch, arch, regtests_branch, 1)
    if not entries:
        return {}
    run_id = entries[0].get("run_id")
    if not isinstance(run_id, str):
        return {}
    report = _load_report(data_root, branch, arch, run_id)
    if report is None:
        return {}
    return {sim.name: (simulation_outcome(sim), run_id) for sim in report.simulations}


def latest_simulation_statuses(
    data_root: Path,
    branch: str,
    arch: str,
    regtests_branch: str,
) -> dict[str, str]:
    return {
        name: status
        for name, (status, _run_id) in latest_simulation_results(
            data_root,
            branch,
            arch,
            regtests_branch,
        ).items()
    }


def compute_flakiness(
    data_root: Path,
    branch: str,
    arch: str,
    regtests_branch: str,
    *,
    limit: int = 20,
    min_observations: int = 3,
) -> FlakinessReport:
    entries = _load_index(data_root, branch, arch, regtests_branch, limit)
    counts: dict[str, dict[str, int]] = {}
    latest: dict[str, tuple[str, str]] = {}

    for entry in entries:
        run_id = entry.get("run_id")
        if not isinstance(run_id, str):
            continue
        report = _load_report(data_root, branch, arch, run_id)
        if report is None:
            continue
        for sim in report.simulations:
            outcome = simulation_outcome(sim)
            bucket = counts.setdefault(
                sim.name,
                {
                    "passed": 0,
                    "failed": 0,
                    "broken": 0,
                    "crashed": 0,
                    "unknown": 0,
                },
            )
            bucket[outcome if outcome in bucket else "unknown"] += 1
            latest.setdefault(sim.name, (outcome, run_id))

    flaky: list[FlakySimulation] = []
    for name, bucket in counts.items():
        observations = sum(bucket.values())
        if observations < min_observations:
            continue
        has_pass = bucket["passed"] > 0
        has_bad = bucket["failed"] + bucket["broken"] + bucket["crashed"] > 0
        if not (has_pass and has_bad):
            continue
        latest_status, latest_run_id = latest.get(name, (None, None))  # type: ignore[assignment]
        flaky.append(
            FlakySimulation(
                name=name,
                observations=observations,
                passed=bucket["passed"],
                failed=bucket["failed"],
                broken=bucket["broken"],
                crashed=bucket["crashed"],
                latest_status=latest_status,
                latest_run_id=latest_run_id,
            )
        )

    flaky.sort(key=lambda s: (-s.failed - s.broken - s.crashed, s.name.lower()))
    return FlakinessReport(
        branch=branch,
        arch=arch,
        regtests_branch=regtests_branch,
        limit=limit,
        min_observations=min_observations,
        runs_considered=len(entries),
        simulations=flaky,
    )
