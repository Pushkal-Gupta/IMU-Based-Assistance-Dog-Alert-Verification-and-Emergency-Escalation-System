"""Shared figure style.

One place for the palette and the axis furniture, so every figure in the report
reads as one system.  Colours are the first three slots of a categorical palette
validated for colour-vision deficiency at all pairs (worst CVD deltaE 9.2,
worst normal-vision deltaE 24.0 against a #fcfcfb surface).  The aqua slot sits
below 3:1 contrast on that surface, so every series that uses it also carries a
direct label or an accompanying table -- identity is never carried by colour
alone.

The palette is capped at three categorical slots on purpose.  A fourth would put
yellow next to orange, which fails the all-pairs separation floor; charts that
need more than three groups are faceted instead.
"""

from __future__ import annotations

from typing import Sequence

import matplotlib as mpl
import matplotlib.pyplot as plt

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#8a8880"
GRID = "#e5e4df"

#: Categorical slots, in fixed order.  Never cycled, never reordered.
SERIES = ("#2a78d6", "#eb6834", "#1baf7a")

#: Single-hue sequential ramp, light -> dark, for magnitude (heatmaps).
SEQUENTIAL = ("#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b")

#: Reserved status colours -- never reused as a series.
STATUS_GOOD = "#008300"
STATUS_CRITICAL = "#e34948"


def use_report_style() -> None:
    """Install the report's rcParams.  Call once before drawing."""
    mpl.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "savefig.dpi": 200,
            "savefig.bbox": "tight",
            "font.size": 9,
            "font.family": "sans-serif",
            "text.color": INK,
            "axes.labelcolor": INK_SECONDARY,
            "axes.edgecolor": GRID,
            "axes.titlesize": 10.5,
            "axes.titleweight": "bold",
            "axes.titlecolor": INK,
            "axes.titlepad": 10,
            "axes.labelsize": 9,
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "xtick.color": INK_MUTED,
            "ytick.color": INK_MUTED,
            "xtick.labelcolor": INK_SECONDARY,
            "ytick.labelcolor": INK_SECONDARY,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.frameon": False,
            "legend.fontsize": 8.5,
            "lines.linewidth": 2.0,
            "lines.markersize": 5,
            "patch.linewidth": 0,
        }
    )


def tidy(ax, *, grid_axis: str = "y") -> None:
    """Strip chartjunk: no top/right spines, one recessive grid direction."""
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.grid(axis=grid_axis, color=GRID, linewidth=0.8)
    if grid_axis == "y":
        ax.grid(axis="x", visible=False)
    elif grid_axis == "x":
        ax.grid(axis="y", visible=False)


def label_bars(ax, bars, values: Sequence[float], fmt: str = "{:.2f}", pad: float = 0.01) -> None:
    """Direct-label bars in ink, not in the series colour."""
    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + pad,
            fmt.format(value),
            ha="center",
            va="bottom",
            fontsize=7.5,
            color=INK_SECONDARY,
        )


def sequential_cmap():
    from matplotlib.colors import LinearSegmentedColormap

    return LinearSegmentedColormap.from_list("ca_blue", ["#ffffff", *SEQUENTIAL])
