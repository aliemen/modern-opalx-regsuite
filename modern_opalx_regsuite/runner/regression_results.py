from __future__ import annotations

import math
import signal as _signal
import time
from pathlib import Path
from typing import Optional

from ..beamline_viz import extract_beamline_json, generate_beamline_svg
from ..data_model import (
    RegressionContainer,
    RegressionMetric,
    RegressionSimulation,
)
from .execution import _append_pipeline_line
from .parsing.regression import (
    _compute_delta,
    _enumerate_stat_containers,
    _parse_rt_file,
    _read_stat_data,
)
from .plotting import _write_stat_plot


def _append_regression_warning(
    pipeline_log_path: Path,
    test_log_path: Optional[Path],
    message: str,
) -> None:
    line = f"[regression] WARNING: {message}"
    _append_pipeline_line(pipeline_log_path, line)
    if test_log_path is None or test_log_path == pipeline_log_path:
        return
    test_log_path.parent.mkdir(parents=True, exist_ok=True)
    with test_log_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _count_common_s_values(s_vals: list[float], ref_s_vals: list[float]) -> int:
    count = 0
    i = 0
    j = 0
    while i < len(s_vals) and j < len(ref_s_vals):
        s = s_vals[i]
        ref_s = ref_s_vals[j]
        if math.isclose(s, ref_s, rel_tol=1e-9, abs_tol=1e-12):
            count += 1
            i += 1
            j += 1
        elif s < ref_s:
            i += 1
        else:
            j += 1
    return count


def _stat_grid_mismatch_warning(
    test_name: str,
    container_id: Optional[str],
    var_name: str,
    s_vals: list[float],
    values: list[float],
    ref_s_vals: list[float],
    ref_values: list[float],
) -> Optional[str]:
    current_samples = min(len(s_vals), len(values))
    reference_samples = min(len(ref_s_vals), len(ref_values))
    if current_samples == 0 or reference_samples == 0:
        return None

    current_s = s_vals[:current_samples]
    reference_s = ref_s_vals[:reference_samples]
    same_count = current_samples == reference_samples
    same_grid = same_count and all(
        math.isclose(current_s[i], reference_s[i], rel_tol=1e-9, abs_tol=1e-12)
        for i in range(current_samples)
    )
    if same_grid:
        return None

    tag = (
        f"{test_name}:{var_name}"
        if container_id is None
        else f"{test_name}[{container_id}]:{var_name}"
    )
    if same_count:
        detail = f"both have {current_samples} samples but s coordinates differ"
    else:
        detail = (
            f"current samples={current_samples}, "
            f"reference samples={reference_samples}"
        )
    common_count = _count_common_s_values(current_s, reference_s)
    return (
        f"{tag} stat sample grid mismatch ({detail}; "
        f"common s samples={common_count}). Difference plots use matching "
        "s coordinates only."
    )


def _classify_crash(rc: int, log_path: Path) -> tuple[Optional[str], Optional[str]]:
    """Return (signal_name, crash_summary) when *rc* indicates a signal kill."""
    if rc >= 0:
        return None, None
    try:
        sig_name = _signal.Signals(abs(rc)).name
    except ValueError:
        sig_name = f"SIG{abs(rc)}"
    crash_summary: Optional[str] = None
    if log_path.exists():
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
            start = text.find("*** Process received signal ***")
            end = text.find("*** End of error message ***")
            if start != -1:
                end_idx = (
                    end + len("*** End of error message ***")
                    if end != -1
                    else start + 2000
                )
                crash_summary = text[start:end_idx].strip()
        except OSError:
            pass
    return sig_name, crash_summary


def _plot_basename(test_name: str, container_id: Optional[str], var_name: str) -> str:
    """Generate plot filename, preserving legacy single-beam names."""
    if container_id is None:
        return f"{test_name}_{var_name}.svg"
    return f"{test_name}_{container_id}_{var_name}.svg"


def _build_container(
    test_name: str,
    container_id: Optional[str],
    rc: int,
    checks: list[tuple[str, str, float]],
    generated_stat: Path,
    reference_stat: Optional[Path],
    plots_dir: Path,
    pipeline_log_path: Path,
    test_log_path: Optional[Path],
) -> tuple[RegressionContainer, bool]:
    """Build one RegressionContainer from a single stat file pair."""
    metrics: list[RegressionMetric] = []
    any_stat_plots = False
    revision: Optional[str] = None

    if checks:
        for var_name, mode, eps in checks:
            rev, s_vals, values, unit = (
                _read_stat_data(generated_stat, var_name)
                if generated_stat.exists()
                else (None, [], [], None)
            )
            if rev and not revision:
                revision = rev
            _ref_rev, ref_s_vals, ref_values, _ = (
                _read_stat_data(reference_stat, var_name)
                if reference_stat is not None and reference_stat.exists()
                else (None, [], [], None)
            )
            grid_warning = _stat_grid_mismatch_warning(
                test_name,
                container_id,
                var_name,
                s_vals,
                values,
                ref_s_vals,
                ref_values,
            )
            if grid_warning:
                _append_regression_warning(
                    pipeline_log_path,
                    test_log_path,
                    grid_warning,
                )
            delta = _compute_delta(mode, values, ref_values)

            state = "broken"
            if delta is not None:
                state = "passed" if delta < eps else "failed"
            elif rc < 0:
                state = "crashed"
            elif rc != 0:
                state = "failed"

            plot_rel: Optional[str] = None
            can_plot = (
                s_vals
                and values
                and ref_s_vals
                and ref_values
                and len(s_vals) == len(values)
                and len(ref_s_vals) == len(ref_values)
                and min(len(values), len(ref_values)) > 1
            )
            if can_plot:
                any_stat_plots = True
                plot_name = _plot_basename(test_name, container_id, var_name)
                plot_path = plots_dir / plot_name
                try:
                    _write_stat_plot(
                        s_vals=s_vals,
                        values=values,
                        ref_s_vals=ref_s_vals,
                        ref_values=ref_values,
                        out_path=plot_path,
                        test_name=test_name,
                        var_name=var_name,
                        var_unit=unit or "",
                    )
                    plot_rel = f"plots/{plot_name}"
                except Exception as exc:
                    tag = (
                        f"{test_name}:{var_name}"
                        if container_id is None
                        else f"{test_name}[{container_id}]:{var_name}"
                    )
                    _append_pipeline_line(
                        pipeline_log_path,
                        f"[regression] plot failed for {tag}: {exc}",
                    )

            metrics.append(
                RegressionMetric(
                    metric=var_name,
                    mode=mode,
                    eps=eps,
                    delta=delta,
                    state=state,
                    reference_value=ref_values[-1] if ref_values else None,
                    current_value=values[-1] if values else None,
                    plot=plot_rel,
                )
            )
    else:
        has_stat = generated_stat.exists()
        if rc == 0 and has_stat:
            state = "passed"
        elif rc < 0:
            state = "crashed"
        elif rc != 0:
            state = "failed"
        else:
            state = "broken"
        metrics.append(
            RegressionMetric(
                metric="run",
                mode="presence",
                eps=None,
                delta=None,
                state=state,
                reference_value=None,
                current_value=None,
                plot=None,
            )
        )

    container_state = "passed"
    if any(m.state == "failed" for m in metrics):
        container_state = "failed"
    elif any(m.state == "crashed" for m in metrics):
        container_state = "crashed"
    elif any(m.state == "broken" for m in metrics):
        container_state = "broken"

    return (
        RegressionContainer(
            id=container_id,
            state=container_state,
            metrics=metrics,
            revision=revision,
        ),
        any_stat_plots,
    )


def _build_simulation(
    test_name: str,
    rc: int,
    rt_file: Path,
    work_test_dir: Path,
    reference_dir: Path,
    plots_dir: Path,
    pipeline_log_path: Path,
    test_start: float,
    input_file: Optional[Path] = None,
    log_path: Optional[Path] = None,
    transport_errors: Optional[list[str]] = None,
) -> RegressionSimulation:
    """Build the result model for one regression simulation."""
    test_log_path = log_path or work_test_dir / f"{test_name}-RT.log"
    crash_signal, crash_summary = _classify_crash(rc, test_log_path)

    description, checks = _parse_rt_file(rt_file)
    generated_pairs = _enumerate_stat_containers(work_test_dir, test_name)
    reference_pairs = _enumerate_stat_containers(reference_dir, test_name)
    ref_by_id: dict[Optional[str], Path] = {cid: p for cid, p in reference_pairs}

    if generated_pairs:
        pairs = generated_pairs
    elif reference_pairs:
        pairs = [(cid, work_test_dir / p.name) for cid, p in reference_pairs]
    else:
        pairs = [(None, work_test_dir / f"{test_name}.stat")]

    containers: list[RegressionContainer] = []
    any_stat_plots = False
    for container_id, generated_stat in pairs:
        reference_stat = ref_by_id.get(container_id)
        if reference_stat is None and container_id is None and reference_pairs:
            reference_stat = reference_pairs[0][1]
        container, had_plots = _build_container(
            test_name=test_name,
            container_id=container_id,
            rc=rc,
            checks=checks,
            generated_stat=generated_stat,
            reference_stat=reference_stat,
            plots_dir=plots_dir,
            pipeline_log_path=pipeline_log_path,
            test_log_path=test_log_path,
        )
        containers.append(container)
        any_stat_plots = any_stat_plots or had_plots

    sim_state = "passed"
    all_metric_states = [m.state for c in containers for m in c.metrics]
    if any(s == "failed" for s in all_metric_states):
        sim_state = "failed"
    elif any(s == "crashed" for s in all_metric_states):
        sim_state = "crashed"
    elif any(s == "broken" for s in all_metric_states):
        sim_state = "broken"

    if transport_errors:
        if sim_state in ("passed", "broken"):
            sim_state = "failed"
        combined = "SSH transport error(s) while fetching test outputs:\n  - " + (
            "\n  - ".join(transport_errors)
        )
        crash_summary = (
            f"{crash_summary}\n\n{combined}" if crash_summary else combined
        )

    beamline_plot: Optional[str] = None
    beamline_3d_data: Optional[str] = None
    data_dir = work_test_dir / "data"

    positions_file: Optional[Path] = (
        next(iter(sorted(data_dir.glob("*_ElementPositions.txt"))), None)
        if data_dir.is_dir()
        else None
    )
    if positions_file is None:
        positions_file = next(
            iter(sorted(work_test_dir.glob("*_ElementPositions.txt"))), None
        )
    if positions_file is not None and any_stat_plots:
        beamline_out = plots_dir / f"{test_name}_beamline.svg"
        try:
            generate_beamline_svg(positions_file, input_file, beamline_out)
            beamline_plot = f"plots/{test_name}_beamline.svg"
        except Exception as exc:
            _append_pipeline_line(
                pipeline_log_path,
                f"[regression] beamline SVG failed for {test_name}: {exc}",
            )

    positions_script: Optional[Path] = (
        next(iter(sorted(data_dir.glob("*_ElementPositions.py"))), None)
        if data_dir.is_dir()
        else None
    )
    if positions_script is None:
        positions_script = next(
            iter(sorted(work_test_dir.glob("*_ElementPositions.py"))), None
        )
    if positions_script is not None and any_stat_plots:
        mesh_out = plots_dir / f"{test_name}_beamline.json"
        try:
            extract_beamline_json(positions_script, mesh_out)
            beamline_3d_data = f"plots/{test_name}_beamline.json"
        except Exception as exc:
            _append_pipeline_line(
                pipeline_log_path,
                f"[regression] beamline mesh JSON failed for {test_name}: {exc}",
            )

    return RegressionSimulation(
        name=test_name,
        description=description,
        state=sim_state,
        log_file=f"logs/{test_name}-RT.log",
        containers=containers,
        duration_seconds=time.monotonic() - test_start,
        beamline_plot=beamline_plot,
        beamline_3d_data=beamline_3d_data,
        exit_code=rc,
        crash_signal=crash_signal,
        crash_summary=crash_summary,
    )
