#!/usr/bin/env python3
"""Vector figures for the manuscript, drawn only from generated artifacts
(plus one held-out replay for the timeline figure).

    python paper/scripts/make_figures.py      -> paper/figures/*.pdf

Style follows ml/canine_alert/plotting.py: three validated categorical slots
in fixed order, a single-hue sequential ramp, recessive grid, direct labels
where a series would otherwise be identified by colour alone.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "ml"))
warnings.filterwarnings("ignore")

from canine_alert.plotting import (  # noqa: E402
    GRID,
    INK,
    INK_MUTED,
    INK_SECONDARY,
    SERIES,
    sequential_cmap,
    tidy,
    use_report_style,
)

OUT = REPO / "paper" / "figures"
WHITE = "#ffffff"
BLUE, ORANGE, AQUA = SERIES


def load(rel):
    return json.loads((REPO / rel).read_text())


def style():
    use_report_style()
    matplotlib.rcParams.update({
        "figure.facecolor": WHITE, "axes.facecolor": WHITE, "savefig.facecolor": WHITE,
        "pdf.fonttype": 42, "font.size": 8, "axes.titlesize": 9, "axes.labelsize": 8,
        "legend.fontsize": 7.5, "xtick.labelsize": 7.5, "ytick.labelsize": 7.5,
    })


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.pdf", metadata={"CreationDate": None})
    plt.close(fig)
    print(f"  {name}.pdf")


def panel(ax, letter, title=None):
    """Panel letter; when the panel has a title, the letter leads it."""
    if title is not None:
        ax.set_title(f"({letter})  {title}", loc="left")
        return
    ax.text(-0.12, 1.04, f"({letter})", transform=ax.transAxes, fontsize=9, fontweight="bold",
            color=INK, va="bottom")


# --------------------------------------------------------------------------- #
# 1. What the collar sees: one held-out recording, end to end
# --------------------------------------------------------------------------- #
def fig_timeline():
    from canine_alert.dataset import load_recordings
    from canine_alert.evaluate import prepare
    from canine_alert.models import EMBEDDED_MODEL, build_model
    from canine_alert.streaming import GatePolicy, alert_times, recording_streams, score_stream

    research = load("ml/artifacts/research.json")
    data = prepare()
    streams = {s.source_id: s for s in recording_streams(load_recordings())}
    # The recording with the most annotated spins: the richest timeline.
    sid = max(streams, key=lambda k: (len(streams[k].spins_s()), streams[k].duration_s))
    stream = streams[sid]
    train = data.groups != stream.group
    model = build_model(EMBEDDED_MODEL, data.feature_names).fit(data.features[train], data.y[train])
    probs, ends = score_stream(model, stream)
    fold = next(f for f in research["nested"][EMBEDDED_MODEL]["per_fold"] if f["group"] == stream.group)
    pol = fold["policy"]
    alerts = alert_times(probs, ends, GatePolicy(pol["vote_threshold"], pol["k"], pol["n"], 0.0))
    t = np.arange(stream.signals.shape[0]) / stream.fs_hz
    gmag = np.linalg.norm(stream.signals[:, 3:6], axis=1)

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(7.0, 3.9), sharex=True,
                                 gridspec_kw={"height_ratios": [1.2, 1], "hspace": 0.45})
    for on, off in stream.spins_s():
        for ax in (a1, a2):
            ax.axvspan(on, off, color=BLUE, alpha=0.12, lw=0)
    a1.plot(t, gmag, color=INK_SECONDARY, lw=0.8)
    a1.axhline(research["sensor_range"]["gyro_full_scale_dps"], color=INK_MUTED, lw=0.8, ls="--")
    a1.text(t[-1], research["sensor_range"]["gyro_full_scale_dps"], " per-axis full scale",
            va="center", ha="left", fontsize=7, color=INK_MUTED)
    a1.set_ylabel("|gyro| (°/s)")
    tidy(a1)
    panel(a1, "a")
    a2.step(ends, probs, where="post", color=BLUE, lw=1.6, label="p(spin), held-out model")
    a2.axhline(pol["vote_threshold"], color=INK_MUTED, lw=0.8, ls="--")
    a2.text(ends[0], pol["vote_threshold"] + 0.03, f"vote threshold θ = {pol['vote_threshold']:.2f}",
            fontsize=7, color=INK_MUTED)
    for at in alerts:
        hit = any(on <= at <= off + 2.6 for on, off in stream.spins_s())
        a2.plot([at], [1.04], marker="v", ms=7, color=BLUE if hit else ORANGE, clip_on=False,
                mec=WHITE, mew=1.0)
    a2.set_ylim(0, 1.1)
    a2.set_ylabel("probability")
    a2.set_xlabel("time (s)")
    a2.plot([], [], marker="v", ls="", color=BLUE, label="alert, true detection")
    a2.plot([], [], marker="v", ls="", color=ORANGE, label="alert, false alarm")
    a2.legend(loc="lower left", ncol=3, bbox_to_anchor=(0.0, 1.06), fontsize=7)
    tidy(a2)
    panel(a2, "b")
    fig.suptitle(f"{sid}: shaded = annotated spins; gate {pol['k']}-of-{pol['n']}", fontsize=8,
                 color=INK_SECONDARY, y=1.0)
    save(fig, "fig_timeline")
    return sid


# --------------------------------------------------------------------------- #
# 2. Model comparison with cluster-bootstrap intervals
# --------------------------------------------------------------------------- #
LABELS = {
    "heuristic_baseline": "Heuristic",
    "naive_bayes": "Naive Bayes",
    "logistic_regression": "Logistic reg.",
    "svm": "SVM",
    "random_forest": "RF (200)",
    "random_forest_embedded": "RF (32), deployed",
}


def fig_models():
    r = load("ml/artifacts/research.json")["logo_intervals"]
    order = list(LABELS)
    fig, axes = plt.subplots(1, 3, figsize=(7.0, 2.4), sharey=True)
    for ax, (key, title), letter in zip(axes, (("segment_f1", "Segment F1"), ("segment_roc_auc", "Segment AUC"),
                                               ("event_recall", "Event recall")), "abc"):
        for y, m in enumerate(order):
            iv = r[m][key]
            color = BLUE if m == "random_forest_embedded" else INK_SECONDARY
            ax.plot([iv["low"], iv["high"]], [y, y], color=color, lw=2, solid_capstyle="round")
            ax.plot([iv["estimate"]], [y], "o", color=color, ms=6, mec=WHITE, mew=1.2)
            ax.text(iv["high"] + 0.008, y, f"{iv['estimate']:.2f}", va="center", fontsize=7, color=INK_SECONDARY)
        tidy(ax, grid_axis="x")
        panel(ax, letter, title)
    axes[0].set_yticks(range(len(order)), [LABELS[m] for m in order])
    axes[0].invert_yaxis()
    fig.text(0.5, -0.04, "leave-one-group-out; bars are 95% cluster-bootstrap intervals over recording groups",
             ha="center", fontsize=7, color=INK_MUTED)
    save(fig, "fig_models")


# --------------------------------------------------------------------------- #
# 3. The gate: single-level sweep, nested estimate, continuous streams
# --------------------------------------------------------------------------- #
def fig_gate():
    res = load("ml/artifacts/results.json")
    research = load("ml/artifacts/research.json")
    rows = res["verification_sweep"]["policies"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.0, 2.8))
    for k, color, marker in ((1, INK_MUTED, "o"), (2, BLUE, "s"), (3, ORANGE, "^")):
        pts = [r for r in rows if r["k"] == k]
        a1.scatter([100 * r["false_alarm_rate"] for r in pts], [r["sensitivity"] for r in pts], s=16,
                   color=color, marker=marker, label=f"K = {k}", edgecolors=WHITE, linewidths=0.5, zorder=3)
    op = res["verification_sweep"]["operating_point"]
    a1.scatter([100 * op["false_alarm_rate"]], [op["sensitivity"]], s=90, facecolors="none",
               edgecolors=INK, linewidths=1.2, zorder=4)
    a1.annotate("selected (single-level)", (100 * op["false_alarm_rate"], op["sensitivity"]),
                xytext=(10, -22), textcoords="offset points", fontsize=7, color=INK_SECONDARY,
                arrowprops={"arrowstyle": "-", "color": INK_MUTED, "lw": 0.7})
    n = research["nested"]["random_forest_embedded"]
    a1.errorbar([100 * n["false_alarm_rate"]], [n["sensitivity"]],
                yerr=[[n["sensitivity"] - n["sensitivity_ci"]["low"]], [n["sensitivity_ci"]["high"] - n["sensitivity"]]],
                xerr=[[100 * (n["false_alarm_rate"] - n["false_alarm_rate_ci"]["low"])],
                      [100 * (n["false_alarm_rate_ci"]["high"] - n["false_alarm_rate"])]],
                fmt="D", color=INK, ms=5, lw=1, capsize=0, zorder=5)
    a1.annotate("nested estimate", (100 * n["false_alarm_rate"], n["sensitivity"]), xytext=(12, 10),
                textcoords="offset points", fontsize=7, color=INK)
    a1.axvline(100 * res["verification_sweep"]["max_false_alarm_rate"], color=INK_MUTED, lw=0.8, ls="--")
    a1.set_xlabel("false alarms per negative event (%)")
    a1.set_ylabel("event sensitivity")
    a1.legend(loc="lower right")
    tidy(a1)
    panel(a1, "a", "Curated events: policy sweep")

    tol_rows = []
    for m, color, label in (("random_forest_embedded", BLUE, "RF (32), deployed"),
                            ("random_forest", ORANGE, "RF (200)"),
                            ("heuristic_baseline", AQUA, "Heuristic")):
        tol = research["continuous"][m]["tolerance_refractory_0s"]
        xs = sorted(float(k) for k in tol)
        ys = [tol[str(x) if str(x) in tol else f"{x}"]["false_alarms_per_hour"] for x in xs]
        a2.plot(xs, ys, marker="o", color=color, ms=4, lw=1.8, label=label)
        tol_rows.append((m, xs, ys))
    a2.axhline(op["false_alarms_per_hour"], color=INK_MUTED, lw=0.8, ls="--")
    a2.text(0.2, op["false_alarms_per_hour"] + 2, "curated-event estimate", fontsize=7, color=INK_MUTED)
    a2.set_xlabel("post-spin scoring tolerance τ (s)")
    a2.set_ylabel("false alarms per hour")
    a2.set_xlim(-0.5, 21)
    a2.set_ylim(0, None)
    a2.legend(loc="lower right", bbox_to_anchor=(1.0, 0.02))
    tidy(a2)
    panel(a2, "b", "Continuous streams, nested policy")
    fig.tight_layout()
    save(fig, "fig_gate")


# --------------------------------------------------------------------------- #
# 4. Robustness to sensor transfer
# --------------------------------------------------------------------------- #
ROB_ORDER = [
    ("clean", "no perturbation"),
    ("rot_x_30deg", "rotate x 30°"), ("rot_x_90deg", "rotate x 90°"), ("rot_x_180deg", "rotate x 180°"),
    ("rot_y_90deg", "rotate y 90°"),
    ("rot_z_30deg", "rotate z 30°"), ("rot_z_90deg", "rotate z 90°"), ("rot_z_180deg", "rotate z 180°"),
    ("rot_random_so3", "random SO(3)"),
    ("mpu6050_datasheet", "MPU6050 noise+bias+gain"),
    ("gyro_full_scale_250dps", "gyro full scale 250°/s"),
    ("jitter_5ms", "sampling jitter 5 ms"),
    ("rate_50hz", "collar at 50 Hz"),
    ("rate_45hz", "collar at 45 Hz"),
]


def fig_robustness():
    rob = load("ml/artifacts/ablations.json")["robustness"]
    fig, ax = plt.subplots(figsize=(7.0, 3.6))
    ys = np.arange(len(ROB_ORDER))
    series = (("clean_training", BLUE, "all features, clean training", -0.22),
              ("augmented", ORANGE, "all features, rotation-augmented training", 0.0),
              ("magnitudes_only", AQUA, "magnitude features only (rotation-invariant)", 0.22))
    for bucket, color, label, dy in series:
        xs, yy = [], []
        for y, (key, _) in zip(ys, ROB_ORDER):
            if key in rob[bucket]:
                xs.append(rob[bucket][key]["event_recall"])
                yy.append(y + dy)
        ax.scatter(xs, yy, s=22, color=color, label=label, edgecolors=WHITE, linewidths=0.6, zorder=3)
    base = rob["clean_training"]["clean"]["event_recall"]
    ax.axvline(base, color=INK_MUTED, lw=0.8, ls="--")
    ax.set_yticks(ys, [lab for _, lab in ROB_ORDER])
    ax.invert_yaxis()
    ax.set_xlabel("event recall on perturbed held-out windows (LOGO)")
    ax.legend(loc="lower left", bbox_to_anchor=(0.0, 1.0), ncol=1, fontsize=7)
    tidy(ax, grid_axis="x")
    fig.tight_layout()
    save(fig, "fig_robustness")


# --------------------------------------------------------------------------- #
# 5. Embedded size/accuracy front
# --------------------------------------------------------------------------- #
def fig_front():
    front = load("ml/artifacts/ablations.json")["embedded_front"]
    fig, ax = plt.subplots(figsize=(3.4, 2.6))
    depths = sorted({r["max_depth"] for r in front})
    cmap = sequential_cmap()
    for r in front:
        c = cmap(0.35 + 0.65 * depths.index(r["max_depth"]) / (len(depths) - 1))
        ax.scatter(r["flash_bytes"] / 1024, r["segment_auc"], s=10 + 2.2 * np.sqrt(r["n_trees"]) * 4,
                   color=c, edgecolors=WHITE, linewidths=0.6, zorder=3)
    ship = next(r for r in front if r["n_trees"] == 32 and r["max_depth"] == 8)
    ax.scatter([ship["flash_bytes"] / 1024], [ship["segment_auc"]], s=110, facecolors="none", edgecolors=INK, lw=1.1)
    ax.annotate("shipped:\n32 trees, depth 8", (ship["flash_bytes"] / 1024, ship["segment_auc"]),
                xytext=(60, 0.8795), textcoords="data", fontsize=7, color=INK_SECONDARY,
                arrowprops={"arrowstyle": "-", "color": INK_MUTED, "lw": 0.7})
    ax.set_xscale("log")
    ax.set_xlabel("flash for forest tables (KiB, log)")
    ax.set_ylabel("segment AUC (LOGO)")
    ax.text(0.02, 0.97, "darker = deeper\nlarger = more trees", transform=ax.transAxes, fontsize=6.5,
            color=INK_MUTED, va="top", ha="left")
    tidy(ax)
    fig.tight_layout()
    save(fig, "fig_front")


# --------------------------------------------------------------------------- #
# 6. Simulation: time to a human, and the watchdog variants
# --------------------------------------------------------------------------- #
def fig_sim():
    sim = load("escalation/artifacts/simulation.json")
    sc = sim["scenarios"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.0, 2.7), gridspec_kw={"width_ratios": [1.25, 1]})
    for name, color, label in (("owner_awake", BLUE, "owner awake"), ("owner_asleep", ORANGE, "owner asleep"),
                               ("owner_incapacitated", AQUA, "owner incapacitated")):
        cdf = sc[name]["cdf_time_to_human"]
        a1.plot(cdf["t_s"], cdf["p"], color=color, lw=1.8, label=label)
    rep = sc["incapacitated_dog_repeats"]["cdf_time_to_human"]
    a1.plot(rep["t_s"], rep["p"], color=AQUA, lw=1.2, ls="--", label="incapacitated, dog repeats ×3")
    a1.legend(loc="lower right", fontsize=6.8)
    for x in (60, 180):
        a1.axvline(x, color=GRID, lw=0.8)
    a1.text(60, 1.02, "T1", fontsize=7, color=INK_MUTED, ha="center")
    a1.text(180, 1.02, "T1+T2", fontsize=7, color=INK_MUTED, ha="center")
    a1.set_xlim(0, 600)
    a1.set_ylim(0, 1.05)
    a1.set_xlabel("seconds after the dog alerts")
    a1.set_ylabel("P(a human has responded)")
    tidy(a1)
    panel(a1, "a")

    cases = (("incapacitated_relay_dies", "phone dies\n(incap.)"), ("incapacitated_partition", "partition\n(incap.)"),
             ("awake_relay_dies", "phone dies\n(awake)"), ("awake_partition", "partition\n(awake)"))
    x = np.arange(len(cases))
    direct = [100 * sc[c]["p_caregiver_skipped"] for c, _ in cases]
    ladder = [100 * sc[f"{c}__ladder"]["p_caregiver_skipped"] for c, _ in cases]
    a2.bar(x - 0.19, direct, 0.36, color=ORANGE, label="watchdog as built (Direct)")
    a2.bar(x + 0.19, ladder, 0.36, color=BLUE, label="ladder-aware watchdog")
    for xi, v in zip(x, direct):
        a2.text(xi - 0.19, v + 0.3, f"{v:.1f}", ha="center", fontsize=6.5, color=INK_SECONDARY)
    for xi, v in zip(x, ladder):
        a2.text(xi + 0.19, v + 0.3, f"{v:.0f}" if v == 0 else f"{v:.1f}", ha="center", fontsize=6.5,
                color=INK_SECONDARY)
    a2.set_ylim(0, max(direct) * 1.25)
    a2.set_xticks(x, [lab for _, lab in cases], fontsize=6.5)
    a2.set_ylabel("caregiver tier skipped (% of episodes)")
    a2.legend(loc="upper right", fontsize=6.5)
    tidy(a2)
    panel(a2, "b")
    fig.tight_layout()
    save(fig, "fig_sim")


def fig_burden():
    sim = load("escalation/artifacts/simulation.json")
    curve = sim["burden_curve"]
    req = sim["requirement"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.0, 2.8))
    x = [r["false_alarms_per_hour"] for r in curve]
    a1.loglog(x, [r["caregiver_pages_per_day"] for r in curve], color=BLUE, lw=1.8, label="caregiver pages / day")
    a1.loglog(x, [r["emergency_pages_per_day"] for r in curve], color=ORANGE, lw=1.8, label="emergency pages / day")
    a1.axhline(1 / 7, color=BLUE, lw=0.8, ls="--")
    a1.axhline(1 / 30, color=ORANGE, lw=0.8, ls="--")
    a1.text(x[0], 1 / 7 * 1.25, "1 per week", fontsize=6.5, color=BLUE)
    a1.text(x[0], 1 / 30 * 0.45, "1 per month", fontsize=6.5, color=ORANGE, va="top")
    a1.axvline(req["max_far_per_hour_for_target"], color=INK_MUTED, lw=0.8, ls=":")
    measured = sim["detector"]["false_alarms_per_hour"]
    a1.axvline(measured, color=INK, lw=0.8)
    a1.text(measured * 0.8, 3e2, "measured", fontsize=6.5, color=INK, ha="right")
    a1.text(req["max_far_per_hour_for_target"] * 1.2, 3e2, "required", fontsize=6.5, color=INK_SECONDARY)
    a1.set_xlabel("detector false alarms per hour of wear")
    a1.set_ylabel("pages caused by false alarms")
    a1.legend(loc="lower right", fontsize=6.8)
    tidy(a1)
    panel(a1, "a")

    grid = sim["t1_t2_grid"]
    t1s = sorted({r["t1_s"] for r in grid})
    t2s = sorted({r["t2_s"] for r in grid})
    M = np.array([[next(r for r in grid if r["t1_s"] == a and r["t2_s"] == b)["p_human_within_180"]
                   for a in t1s] for b in t2s])
    P = np.array([[next(r for r in grid if r["t1_s"] == a and r["t2_s"] == b)["burden_at_measured_far"]["p_reaches_caregiver"]
                   for a in t1s] for b in t2s])
    im = a2.imshow(M, cmap=sequential_cmap(), vmin=0, vmax=max(0.7, M.max()), origin="lower", aspect="auto")
    for yi in range(len(t2s)):
        for xi in range(len(t1s)):
            v = M[yi, xi]
            a2.text(xi, yi, f"{v:.2f}", ha="center", va="center", fontsize=6.5,
                    color=WHITE if v > 0.45 else INK)
    a2.set_xticks(range(len(t1s)), [f"{t:g}" for t in t1s])
    a2.set_yticks(range(len(t2s)), [f"{t:g}" for t in t2s])
    a2.set_xlabel("T1, owner window (s)")
    a2.set_ylabel("T2, caregiver window (s)")
    a2.grid(False)
    sec = a2.secondary_xaxis("top")
    sec.set_xticks(range(len(t1s)), [f"{100 * P[0, i]:.0f}%" for i in range(len(t1s))])
    sec.tick_params(labelsize=6.5, colors=INK_MUTED)
    sec.set_xlabel("false alarms reaching the caregiver", fontsize=6.5, color=INK_MUTED)
    a2.text(-0.2, 1.22, "(b)", transform=a2.transAxes, fontsize=9, fontweight="bold", color=INK)
    fig.tight_layout()
    save(fig, "fig_burden")


def main() -> int:
    style()
    print("figures:")
    sid = fig_timeline()
    fig_models()
    fig_gate()
    fig_robustness()
    fig_front()
    fig_sim()
    fig_burden()
    (REPO / "paper" / "generated").mkdir(parents=True, exist_ok=True)
    (REPO / "paper" / "generated" / "timeline_source.tex").write_text(
        "\\newcommand{\\TimelineRecording}{\\texttt{" + sid.replace("_", "\\_") + "}}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
