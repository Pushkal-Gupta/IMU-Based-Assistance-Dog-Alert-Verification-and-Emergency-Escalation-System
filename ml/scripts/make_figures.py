#!/usr/bin/env python3
"""Render the report figures from ``ml/artifacts/results.json`` and the dataset.

Run ``run_experiments.py`` first.  Figures land in ``docs/figures/``.

Every figure is drawn from the saved results rather than by re-fitting, so the
numbers in the report, the numbers in the JSON and the numbers in the pictures
cannot disagree.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from canine_alert.config import DEFAULT_ARTIFACT_DIR, DEFAULT_DATASET_DIR, REPO_ROOT  # noqa: E402
from canine_alert.dataset import load_recordings, spin_events  # noqa: E402
from canine_alert.plotting import (  # noqa: E402
    GRID,
    SURFACE,
    INK,
    INK_SECONDARY,
    SERIES,
    STATUS_CRITICAL,
    label_bars,
    sequential_cmap,
    tidy,
    use_report_style,
)

DEFAULT_FIGURE_DIR = REPO_ROOT / "docs" / "figures"

MODEL_LABELS = {
    "heuristic_baseline": "Heuristic\nbaseline",
    "random_forest": "Random\nForest",
    "svm": "SVM",
    "naive_bayes": "Naive\nBayes",
    "logistic_regression": "Logistic\nRegression",
    "random_forest_embedded": "RF\n(embedded)",
}


def fig_spin_signal(recordings, out: Path) -> None:
    """A raw spin, annotated -- the paper's Figure 1a, from our loader.

    Two rotation-invariant magnitudes rather than six raw axes: the six-line
    version is unreadable at report size, and the magnitudes are what the
    classifier's strongest features are built from anyway.
    """
    chosen = max(
        recordings,
        key=lambda r: len(spin_events(r)) if 1000 < len(r.frame) < 4000 else -1,
    )
    fs = chosen.fs_hz
    signals = chosen.channels()
    labels = chosen.labels
    spans = spin_events(chosen)

    stop = min(len(labels), (spans[-1][1] if spans else len(labels)) + int(3 * fs))
    start = max(0, (spans[0][0] if spans else 0) - int(3 * fs))
    t = np.arange(start, stop) / fs

    accel = np.linalg.norm(signals[start:stop, 0:3], axis=1)
    gyro = np.linalg.norm(signals[start:stop, 3:6], axis=1)

    fig, (top, bottom) = plt.subplots(
        2, 1, figsize=(7.4, 4.0), sharex=True, gridspec_kw={"hspace": 0.28}
    )

    for start_i, stop_i in spans:
        if stop_i < start or start_i > stop:
            continue
        for ax in (top, bottom):
            ax.axvspan(start_i / fs, stop_i / fs, color=SERIES[1], alpha=0.14, linewidth=0)

    # One series per panel, so the y-axis label is the label -- no legend, no
    # in-plot annotation competing with a dense trace.  Thin lines: at ~50 Hz
    # over 30 s there are more samples than pixels.
    top.plot(t, gyro, color=SERIES[0], linewidth=0.9)
    top.set_ylabel("|gyroscope|  (deg/s)")
    top.set_title("A trained double-spin alert, as the collar sees it", loc="left")
    top.text(
        0.995,
        0.95,
        "shaded = annotated spin",
        transform=top.transAxes,
        ha="right",
        va="top",
        fontsize=8,
        color=INK_SECONDARY,
    )

    bottom.plot(t, accel, color=SERIES[2], linewidth=0.9)
    bottom.set_ylabel("|acceleration|  (m/s$^2$)")
    bottom.set_xlabel("time (s)")

    for ax in (top, bottom):
        tidy(ax, grid_axis="y")
    fig.suptitle("")
    fig.savefig(out / "fig1_spin_signal.png")
    plt.close(fig)


def fig_dataset(recordings, results, out: Path) -> None:
    """Event durations and how unevenly the annotations are spread."""
    durations = []
    per_group: dict[str, int] = {}
    for rec in recordings:
        fs = rec.fs_hz
        spans = spin_events(rec)
        durations.extend((b - a) / fs for a, b in spans)
        per_group[rec.group] = per_group.get(rec.group, 0) + len(spans)

    fig, (left, right) = plt.subplots(1, 2, figsize=(7.4, 3.0), gridspec_kw={"wspace": 0.28})

    left.hist(durations, bins=12, color=SERIES[0])
    median = float(np.median(durations))
    left.axvline(median, color=STATUS_CRITICAL, linewidth=1.6)
    left.text(
        median,
        left.get_ylim()[1] * 0.95,
        f" median {median:.2f} s",
        color=STATUS_CRITICAL,
        fontsize=8,
        va="top",
    )
    left.set_xlabel("spin event duration (s)")
    left.set_ylabel("events")
    left.set_title(f"Duration of {len(durations)} annotated spins", loc="left")
    tidy(left)

    counts = sorted(per_group.values(), reverse=True)
    bars = right.bar(range(len(counts)), counts, color=SERIES[0], width=0.75)
    right.set_xlabel("recording group (sorted)")
    right.set_ylabel("annotated spins")
    right.set_title(f"Spins per group ({len(counts)} groups)", loc="left")
    right.text(
        0.98,
        0.92,
        f"max {max(counts)}  ·  min {min(counts)}",
        transform=right.transAxes,
        ha="right",
        va="top",
        fontsize=8,
        color=INK_SECONDARY,
    )
    tidy(right)
    label_bars(right, bars, counts, fmt="{:.0f}", pad=0.15)

    fig.savefig(out / "fig2_dataset.png")
    plt.close(fig)


def fig_model_comparison(results, out: Path) -> None:
    """Within-subject vs LOGO F1, per model.

    Two protocols = two categorical slots.  The gap between them *is* the
    finding: it is the price of generalising to an unseen animal.
    """
    models = [m for m in MODEL_LABELS if m in results["logo"]]
    within = [results["within_subject"][m]["f1"] for m in models]
    logo = [results["logo"][m]["segment_metrics"]["f1"] for m in models]

    x = np.arange(len(models))
    width = 0.38

    fig, ax = plt.subplots(figsize=(7.4, 3.4))
    # edgecolor in the surface colour puts a 2px gap between adjacent bars, so
    # the pair reads as two marks rather than one two-tone block.
    bar_kw = dict(edgecolor=SURFACE, linewidth=1.4)
    b1 = ax.bar(
        x - width / 2, within, width, color=SERIES[0],
        label="Within-subject (pooled split)", **bar_kw,
    )
    b2 = ax.bar(
        x + width / 2, logo, width, color=SERIES[1],
        label="Leave-one-group-out", **bar_kw,
    )
    label_bars(ax, b1, within)
    label_bars(ax, b2, logo)

    ax.set_xticks(x)
    ax.set_xticklabels([MODEL_LABELS[m] for m in models])
    ax.set_ylabel("F1 (spin class)")
    ax.set_ylim(0, max(max(within), max(logo)) * 1.25)
    ax.set_title("Segment-level F1 by model and evaluation protocol", loc="left")
    ax.legend(loc="upper left", bbox_to_anchor=(0, 1.02), ncol=2)
    tidy(ax)
    fig.savefig(out / "fig3_model_comparison.png")
    plt.close(fig)


def _confusion(ax, matrix: dict, title: str, note: str) -> None:
    grid = np.array([[matrix["tn"], matrix["fp"]], [matrix["fn"], matrix["tp"]]], dtype=float)
    ax.imshow(grid / grid.max(), cmap=sequential_cmap(), vmin=0, vmax=1)
    for i in range(2):
        for j in range(2):
            value = int(grid[i, j])
            ax.text(
                j,
                i,
                f"{value}",
                ha="center",
                va="center",
                fontsize=13,
                color="#ffffff" if grid[i, j] / grid.max() > 0.55 else INK,
            )
    ax.set_xticks([0, 1], ["predicted\nno spin", "predicted\nspin"])
    ax.set_yticks([0, 1], ["actual\nno spin", "actual\nspin"])
    ax.set_title(title, loc="left", pad=26)
    ax.text(0.0, 1.04, note, transform=ax.transAxes, fontsize=8, color=INK_SECONDARY, va="bottom")
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(False)


def fig_confusion(results, out: Path, model: str = "random_forest") -> None:
    segment = results["logo"][model]["segment_metrics"]["confusion_matrix"]
    event = results["event_level"][model]["confusion_matrix"]
    event_seconds = results["dataset"]["event_seconds"]

    fig, (left, right) = plt.subplots(1, 2, figsize=(7.0, 3.2), gridspec_kw={"wspace": 0.45})
    _confusion(
        left,
        segment,
        "Segment level (2.6 s windows)",
        f"recall {results['logo'][model]['segment_metrics']['recall']:.2f}"
        f"  ·  {segment['fn']} missed windows",
    )
    _confusion(
        right,
        event,
        f"Event level ({event_seconds:.2f} s episodes)",
        f"recall {results['event_level'][model]['recall']:.2f}"
        f"  ·  {event['fn']} missed events",
    )
    fig.savefig(out / "fig4_confusion.png")
    plt.close(fig)


def fig_operating_curve(results, out: Path) -> None:
    """Sensitivity against wall-clock false-alarm rate, one line per K.

    This is the figure the escalation design is argued from: K is the knob that
    trades missed alerts against nuisance pages, and the vote threshold moves
    along each curve.
    """
    sweep = results["verification_sweep"]["policies"]
    point = results["verification_sweep"].get("operating_point")

    fig, ax = plt.subplots(figsize=(7.0, 3.8))
    for slot, k in enumerate(sorted({row["k"] for row in sweep})):
        rows = sorted(
            (r for r in sweep if r["k"] == k and r["n"] == max(r["k"], r["k"] + 1)),
            key=lambda r: r["vote_threshold"],
        ) or sorted((r for r in sweep if r["k"] == k), key=lambda r: r["vote_threshold"])
        xs = [r["false_alarms_per_hour"] for r in rows]
        ys = [r["sensitivity"] for r in rows]
        ax.plot(xs, ys, marker="o", color=SERIES[slot % len(SERIES)], label=f"K = {k}")
        ax.annotate(
            f"K={k}",
            (xs[0], ys[0]),
            textcoords="offset points",
            xytext=(6, 6),
            fontsize=8.5,
            color=INK_SECONDARY,
        )

    if point:
        ax.scatter(
            [point["false_alarms_per_hour"]],
            [point["sensitivity"]],
            s=140,
            facecolor="none",
            edgecolor=STATUS_CRITICAL,
            linewidth=2,
            zorder=5,
        )
        ax.annotate(
            f"shipped: {point['k']}-of-{point['n']} at p>={point['vote_threshold']:.2f}",
            (point["false_alarms_per_hour"], point["sensitivity"]),
            textcoords="offset points",
            xytext=(10, -16),
            fontsize=8.5,
            color=STATUS_CRITICAL,
        )

    ax.set_xlabel("false alarms per hour of spin-free training-session motion")
    ax.set_ylabel("event-level sensitivity")
    ax.set_ylim(0, 1.0)
    ax.set_title("Verification gate: what each K-of-N policy costs and buys", loc="left")
    ax.legend(loc="lower right")
    tidy(ax, grid_axis="both")
    ax.grid(True, color=GRID, linewidth=0.8)
    fig.savefig(out / "fig5_operating_curve.png")
    plt.close(fig)


def fig_feature_stability(results, out: Path, model: str = "random_forest_embedded") -> None:
    """How often each feature survives selection across the LOGO folds.

    A feature chosen in every fold is a property of the behaviour; one chosen in
    three is a property of three recordings.
    """
    frequency = results["logo"][model]["selection_frequency"]
    n_folds = len(results["logo"][model]["per_fold"])
    top = list(frequency.items())[:20][::-1]
    names = [n for n, _ in top]
    counts = [c for _, c in top]

    fig, ax = plt.subplots(figsize=(7.0, 4.6))
    ax.barh(range(len(names)), counts, color=SERIES[0], height=0.72)
    for i, count in enumerate(counts):
        ax.text(
            count + n_folds * 0.012,
            i,
            f"{count}/{n_folds}",
            va="center",
            fontsize=7.5,
            color=INK_SECONDARY,
        )
    ax.set_yticks(range(len(names)), names, fontsize=8)
    ax.set_xlim(0, n_folds * 1.12)
    ax.set_xlabel(f"folds in which the feature was selected (of {n_folds})")
    ax.set_title("Feature stability across leave-one-group-out folds", loc="left")
    tidy(ax, grid_axis="x")
    fig.savefig(out / "fig6_feature_stability.png")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--figure-dir", type=Path, default=DEFAULT_FIGURE_DIR)
    args = parser.parse_args()

    results_path = args.artifact_dir / "results.json"
    if not results_path.exists():
        print(f"error: {results_path} not found -- run run_experiments.py first", file=sys.stderr)
        return 1
    results = json.loads(results_path.read_text())

    args.figure_dir.mkdir(parents=True, exist_ok=True)
    use_report_style()

    recordings = load_recordings(args.dataset_dir)
    fig_spin_signal(recordings, args.figure_dir)
    fig_dataset(recordings, results, args.figure_dir)
    fig_model_comparison(results, args.figure_dir)
    fig_confusion(results, args.figure_dir)
    fig_operating_curve(results, args.figure_dir)
    fig_feature_stability(results, args.figure_dir)

    written = sorted(p.name for p in args.figure_dir.glob("fig*.png"))
    print(f"wrote {len(written)} figures to {args.figure_dir}:")
    for name in written:
        print(f"  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
