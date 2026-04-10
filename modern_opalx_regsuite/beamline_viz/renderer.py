"""Matplotlib-based beamline diagram renderer.

Produces an SVG file showing each beamline element as a coloured rectangle
above a horizontal reference line (the beam axis).  Overlapping elements are
stacked in separate vertical lanes using a greedy interval-scheduling
algorithm.  Drift spaces are rendered as faint background bands so the active
elements stand out.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # noqa: E402 — must be set before pyplot import
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

from .elements import ELEMENT_STYLES, BeamlineElement

# ---------------------------------------------------------------------------
# Layout constants (all in matplotlib data-unit space)
# ---------------------------------------------------------------------------

BOX_HEIGHT = 0.42       # Height of each element rectangle
LANE_STEP = 0.60        # Vertical distance between lane baselines
LANE_BASE_Y = 0.12      # Distance from the axis (y=0) to the bottom of lane 0
AXIS_Y = 0.0            # y-coordinate of the beam axis line


# ---------------------------------------------------------------------------
# Lane assignment
# ---------------------------------------------------------------------------


def _assign_lanes(elements: list[BeamlineElement]) -> list[tuple[BeamlineElement, int]]:
    """Assign each non-drift element to the lowest available lane.

    Two elements overlap when their intervals overlap strictly (touching
    endpoints are not considered an overlap).  Sorted by start position with
    longest elements first when starts are equal so that enclosing elements
    end up in lower (more prominent) lanes.
    """
    candidates = sorted(
        [e for e in elements if e.elem_type.lower() != "drift"],
        key=lambda e: (e.start, -(e.end - e.start)),
    )

    # lane_ends[i] = s-coordinate of the last placed element's end in lane i
    lane_ends: list[float] = []
    result: list[tuple[BeamlineElement, int]] = []

    for elem in candidates:
        assigned = -1
        for lane_idx, lane_end in enumerate(lane_ends):
            if elem.start >= lane_end:  # strictly no overlap
                assigned = lane_idx
                lane_ends[lane_idx] = elem.end
                break
        if assigned == -1:
            assigned = len(lane_ends)
            lane_ends.append(elem.end)
        result.append((elem, assigned))

    return result


# ---------------------------------------------------------------------------
# Main renderer
# ---------------------------------------------------------------------------


def render_beamline(elements: list[BeamlineElement], output_path: Path) -> None:
    """Render *elements* as a beamline SVG saved at *output_path*.

    The file is always written in SVG format regardless of the suffix of
    *output_path*.
    """
    if not elements:
        return

    drifts = [e for e in elements if e.elem_type.lower() == "drift"]
    assigned = _assign_lanes(elements)

    n_lanes = max((lane for _, lane in assigned), default=0) + 1
    total_length = max(e.end for e in elements)
    # Guard against degenerate beamlines
    if total_length <= 0:
        return

    # Minimum rendered width so very short elements remain visible
    min_box_width = total_length * 0.004

    fig_height = max(1.6, 0.9 + n_lanes * LANE_STEP)
    fig, ax = plt.subplots(figsize=(12, fig_height))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    # -- Drift background bands ------------------------------------------
    for drift in drifts:
        if drift.length <= 0:
            continue
        y_bottom = LANE_BASE_Y - 0.05
        band_height = n_lanes * LANE_STEP + BOX_HEIGHT + 0.05
        ax.add_patch(FancyBboxPatch(
            (drift.start, y_bottom),
            drift.length,
            band_height,
            boxstyle="square,pad=0",
            facecolor="#F2F3F4",
            edgecolor="#E5E7E9",
            linewidth=0.5,
            zorder=1,
            alpha=0.8,
        ))
        # Tiny "DRIFT" label at the top of the band
        ax.text(
            drift.start + drift.length / 2,
            y_bottom + band_height + 0.03,
            f"{drift.name}  ({drift.length:.2f} m)",
            ha="center", va="bottom",
            fontsize=6, color="#AAAAAA",
            zorder=3,
        )

    # -- Beam axis -----------------------------------------------------------
    ax.axhline(AXIS_Y, color="#2C3E50", linewidth=1.5, zorder=0)

    # -- Active elements -----------------------------------------------------
    legend_entries: dict[str, str] = {}  # type_key → display label

    for elem, lane in assigned:
        style = ELEMENT_STYLES.get(elem.elem_type.lower(), ELEMENT_STYLES["_default"])
        color: str = style["color"]
        legend_entries[elem.elem_type.lower()] = style["label"]

        length = max(elem.end - elem.start, min_box_width)
        y_bottom = LANE_BASE_Y + lane * LANE_STEP

        # Element rectangle
        ax.add_patch(FancyBboxPatch(
            (elem.start, y_bottom),
            length,
            BOX_HEIGHT,
            boxstyle="round,pad=0.025",
            facecolor=color,
            edgecolor="white",
            linewidth=1.5,
            zorder=2,
            alpha=0.92,
        ))

        # Connecting tick from axis to bottom of rectangle
        x_mid = elem.start + (elem.end - elem.start) / 2
        ax.plot(
            [x_mid, x_mid],
            [AXIS_Y, y_bottom],
            color=color,
            linewidth=0.8,
            alpha=0.5,
            zorder=1,
        )

        # Element name label (white, inside the box)
        # Show "Name\nType" when there is enough room
        type_short = style["label"]
        pixel_width_approx = (length / total_length) * 12 * 72  # 12" fig × 72 dpi
        if pixel_width_approx > 60:
            label = f"{elem.name}\n{type_short}"
            fontsize = 6.5
        elif pixel_width_approx > 28:
            label = elem.name
            fontsize = 6.5
        else:
            label = ""  # too narrow for a legible label

        if label:
            ax.text(
                x_mid,
                y_bottom + BOX_HEIGHT / 2,
                label,
                ha="center", va="center",
                fontsize=fontsize, fontweight="bold",
                color="white",
                zorder=3,
                clip_on=True,
                linespacing=1.2,
            )

    # -- Axes styling --------------------------------------------------------
    x_pad = total_length * 0.02
    ax.set_xlim(-x_pad, total_length + x_pad)
    y_top = LANE_BASE_Y + n_lanes * LANE_STEP + BOX_HEIGHT + 0.25
    ax.set_ylim(-0.3, y_top)

    ax.set_xlabel("s  (m)", fontsize=9, color="#444444")
    ax.set_yticks([])
    for spine in ("left", "right", "top"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color("#BBBBBB")
    ax.tick_params(axis="x", labelsize=8, colors="#666666", length=3)

    # -- Legend --------------------------------------------------------------
    handles = [
        mpatches.Patch(
            facecolor=ELEMENT_STYLES.get(k, ELEMENT_STYLES["_default"])["color"],
            label=v,
            alpha=0.92,
        )
        for k, v in legend_entries.items()
    ]
    if handles:
        ax.legend(
            handles=handles,
            loc="upper right",
            fontsize=7,
            framealpha=0.9,
            edgecolor="#DDDDDD",
            handlelength=1.0,
            handleheight=0.9,
            borderpad=0.6,
        )

    # -- Save ----------------------------------------------------------------
    plt.tight_layout(pad=0.4)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, format="svg", bbox_inches="tight")
    plt.close(fig)
