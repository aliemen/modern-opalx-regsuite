"""The SVG writer of the runner before series.json.gz (was runner/plotting.py).

Kept only to generate legacy SVG fixtures for the migration tests; the runner no
longer draws plots. Unchanged apart from importing the difference helper.
"""
from __future__ import annotations

from pathlib import Path

from modern_opalx_regsuite.series import common_s_differences as _common_s_differences


def _write_stat_plot(
    s_vals: list[float],
    values: list[float],
    ref_s_vals: list[float],
    ref_values: list[float],
    out_path: Path,
    test_name: str,
    var_name: str,
    var_unit: str,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax1 = plt.subplots(figsize=(9, 4.5))
    ax2 = ax1.twinx()
    diff_s, diffs = _common_s_differences(s_vals, values, ref_s_vals, ref_values)

    ax1.plot(s_vals[: len(values)], values, label="current", linewidth=2)
    ref_s = (
        ref_s_vals
        if len(ref_s_vals) == len(ref_values)
        else s_vals[: len(ref_values)]
    )
    ax1.plot(ref_s, ref_values, label="reference", linewidth=2)
    if diff_s:
        ax2.plot(
            diff_s,
            diffs,
            "--",
            color="grey",
            label="difference",
            linewidth=1.0,
        )

    pretty_var = var_name.replace("_", "(")
    if "(" in pretty_var and not pretty_var.endswith(")"):
        pretty_var += ")"
    y_unit = f" [{var_unit}]" if var_unit else ""

    ax1.set_title(test_name)
    ax1.set_xlabel("s [m]")
    ax1.set_ylabel(f"{pretty_var}{y_unit}")
    ax2.set_ylabel(f"delta {pretty_var}{y_unit}")
    ax1.legend(loc="lower left")
    if diff_s:
        ax2.legend(loc="lower right")
    ax1.grid(True)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
