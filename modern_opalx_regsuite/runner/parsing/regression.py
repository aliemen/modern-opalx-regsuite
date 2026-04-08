"""Regression test discovery and SDDS .stat file parsing."""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Optional

from ...data_model import (
    RegressionMetric,
    RegressionSimulation,
    RegressionTestsReport,
)


def _parse_regression_output(output: str) -> RegressionTestsReport:
    """Fallback: derive a single pass/fail result from raw command output."""
    state = "passed"
    if "failed" in output.lower() or "error" in output.lower():
        state = "failed"
    sim = RegressionSimulation(
        name="regression-suite",
        description="Aggregated regression tests.",
        metrics=[
            RegressionMetric(
                metric="suite",
                mode="aggregate",
                state=state,
                eps=None,
                delta=None,
                reference_value=None,
                current_value=None,
                plot=None,
            )
        ],
    )
    return RegressionTestsReport(simulations=[sim])


def _discover_regression_tests(tests_root: Path) -> list[str]:
    tests: list[str] = []
    if not tests_root.is_dir():
        return tests
    for entry in sorted(tests_root.iterdir()):
        if entry.name.startswith(".") or not entry.is_dir():
            continue
        test = entry.name
        if (entry / "disabled").exists():
            continue
        if not (entry / f"{test}.in").is_file():
            continue
        if not (entry / "reference" / f"{test}.stat").is_file():
            continue
        tests.append(test)
    return tests


def _parse_rt_file(rt_path: Path) -> tuple[Optional[str], list[tuple[str, str, float]]]:
    if not rt_path.is_file():
        return None, []
    lines = [l.strip() for l in rt_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not lines:
        return None, []
    description = lines[0].strip().strip('"')
    checks: list[tuple[str, str, float]] = []
    for line in lines[1:]:
        if not line.startswith("stat"):
            continue
        m = re.match(r'^stat\s+"([^"]+)"\s+(\S+)\s+(\S+)\s*$', line)
        if not m:
            continue
        var = m.group(1)
        mode = m.group(2)
        try:
            eps = float(m.group(3))
        except ValueError:
            continue
        checks.append((var, mode, eps))
    return description, checks


def _extract_local_run_command(local_script: Path) -> Optional[str]:
    """Extract the effective run command from a legacy *.local script."""
    if not local_script.is_file():
        return None
    lines = local_script.read_text(encoding="utf-8", errors="replace").splitlines()
    for raw in reversed(lines):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("cd "):
            continue
        return line
    return None


def _parse_sdds_kv(block: str, key: str) -> Optional[str]:
    m = re.search(rf"{key}=([^,]+)", block)
    if not m:
        return None
    return m.group(1).strip().strip('"')


def _read_stat_data(
    path: Path, var_name: str
) -> tuple[Optional[str], list[float], list[float], Optional[str]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    columns: dict[str, dict[str, int | str]] = {}
    params: dict[str, int] = {}

    i = 0
    while i < len(lines):
        line = lines[i]
        if "&column" in line:
            block = line
            while "&end" not in lines[i] and i + 1 < len(lines):
                i += 1
                block += lines[i]
            name = _parse_sdds_kv(block, "name")
            unit = _parse_sdds_kv(block, "units")
            if name:
                columns[name] = {"column": len(columns), "units": unit or ""}
        elif "&parameter" in line:
            block = line
            while "&end" not in lines[i] and i + 1 < len(lines):
                i += 1
                block += lines[i]
            name = _parse_sdds_kv(block, "name")
            if name:
                params[name] = len(params)
        elif "&data" in line:
            while "&end" not in lines[i] and i + 1 < len(lines):
                i += 1
            i += 1
            break
        i += 1

    header_lines = i
    rev_line = params.get("revision")
    revision: Optional[str] = None
    if rev_line is not None and header_lines + rev_line < len(lines):
        revision = lines[header_lines + rev_line]
        m = re.search(r"(.* git rev\. )#([A-Za-z0-9]{7})[A-Za-z0-9]*", revision)
        if m:
            revision = f"{m.group(1)}{m.group(2)}"

    if "s" not in columns or var_name not in columns:
        return revision, [], [], None

    s_col = int(columns["s"]["column"])
    var_col = int(columns[var_name]["column"])
    var_unit = str(columns[var_name].get("units", "")).strip('"')

    data_start = header_lines + len(params)
    s_vals: list[float] = []
    values: list[float] = []
    for row in lines[data_start:]:
        parts = row.split()
        if len(parts) <= max(s_col, var_col):
            continue
        try:
            s_vals.append(float(parts[s_col]))
            values.append(float(parts[var_col]))
        except ValueError:
            continue

    return revision, s_vals, values, var_unit


def _compute_delta(mode: str, values: list[float], ref_values: list[float]) -> Optional[float]:
    if not values or not ref_values or len(values) != len(ref_values):
        return None
    if mode == "last":
        return abs(values[-1] - ref_values[-1])
    if mode == "avg":
        sq = sum((values[i] - ref_values[i]) ** 2 for i in range(len(values)))
        return math.sqrt(sq) / len(values)
    return None
