#!/usr/bin/env python3
"""Research-grade evaluation: intervals, paired tests, shift protocols,
nested operating-point selection and continuous-stream scoring.

Reads nothing from ``results.json`` -- it refits everything it reports, so the
two scripts can be run in either order.  Writes ``ml/artifacts/research.json``.

    python ml/scripts/run_research.py            # ~3 min on 8+ cores
    python ml/scripts/run_research.py --quick    # fewer bootstrap draws, for CI
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from canine_alert import stats
from canine_alert.config import DEFAULT_ARTIFACT_DIR, DEFAULT_CONFIG, DEFAULT_DATASET_DIR
from canine_alert.dataset import load_recordings
from canine_alert.evaluate import ALL_MODELS, BASELINE_NAME, prepare, run_logo
from canine_alert.models import EMBEDDED_MODEL, GyroMagnitudeBaseline, build_model
from canine_alert.nested import pool_nested, run_nested
from canine_alert.streaming import (
    GatePolicy,
    evaluate_streams,
    recording_streams,
    score_stream,
    summarise_outcomes,
)
from canine_alert.verification import SWEEP_THRESHOLDS, select_operating_point, sweep_grid
from canine_alert.evaluate import event_probability_streams

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_experiments import to_jsonable  # noqa: E402

warnings.filterwarnings("ignore", category=FutureWarning)

DEPLOYED = EMBEDDED_MODEL
REFERENCE = "random_forest"
NESTED_MODELS = (DEPLOYED, REFERENCE, BASELINE_NAME)
#: The heuristic's pseudo-probability is a logistic squash centred on its own
#: threshold, so nothing below ~0.5 is selective; it gets a wider vote grid so
#: that the comparison is not lost by construction.
BASELINE_THRESHOLDS = tuple(round(t, 2) for t in np.arange(0.25, 0.951, 0.05))


# --------------------------------------------------------------------------- #
# segment- and event-level intervals
# --------------------------------------------------------------------------- #
def event_table(data, predictions, scores):
    """Per-event (group, label, predicted, max score), from window OOF output."""
    evaluated = predictions >= 0
    ids = data.segments.event_ids[evaluated]
    unique, inverse = np.unique(ids, return_inverse=True)
    pos = np.zeros(unique.size, dtype=int)
    best = np.zeros(unique.size)
    np.add.at(pos, inverse, predictions[evaluated])
    np.maximum.at(best, inverse, np.nan_to_num(scores[evaluated]))
    label = np.zeros(unique.size, dtype=int)
    group = np.empty(unique.size, dtype=object)
    label[inverse] = data.segments.event_labels[evaluated]
    group[inverse] = data.groups[evaluated]
    return group, label, (pos >= 1).astype(int), best


def model_intervals(data, result, n_boot):
    y = data.y
    pred = result.oof_predictions
    score = result.oof_scores
    ok = pred >= 0
    rows = np.flatnonzero(ok)
    g = data.groups[rows]
    yy, pp, ss = y[rows], pred[rows], score[rows]

    out = {}
    for key, fn in {
        "f1": lambda i: stats.f1_from(yy[i], pp[i]),
        "roc_auc": lambda i: stats.auc_from(yy[i], ss[i]),
        "recall": lambda i: stats.recall_from(yy[i], pp[i]),
        "specificity": lambda i: stats.recall_from(1 - yy[i], 1 - pp[i]),
    }.items():
        interval, _ = stats.cluster_bootstrap(g, fn, n_boot=n_boot)
        out[f"segment_{key}"] = interval.as_dict()

    eg, el, ep, es = event_table(data, pred, score)
    for key, fn in {
        "f1": lambda i: stats.f1_from(el[i], ep[i]),
        "recall": lambda i: stats.recall_from(el[i], ep[i]),
        "specificity": lambda i: stats.recall_from(1 - el[i], 1 - ep[i]),
    }.items():
        interval, _ = stats.cluster_bootstrap(eg, fn, n_boot=n_boot)
        out[f"event_{key}"] = interval.as_dict()
    return out


def paired_comparisons(data, logo, n_boot):
    """Every model against the deployed one, paired on the same groups."""
    rows = np.flatnonzero(logo[DEPLOYED].oof_predictions >= 0)
    g = data.groups[rows]
    y = data.y[rows]
    ref_pred = logo[DEPLOYED].oof_predictions[rows]
    ref_score = logo[DEPLOYED].oof_scores[rows]
    # Per-fold F1 is undefined on a fold with no positive window, so only folds
    # that contain a spin enter the signed-rank test.
    ref_fold = {f["group"]: f["f1"] for f in logo[DEPLOYED].per_fold if f["n_test_positive"]}
    _, ref_el, ref_ep, _ = event_table(data, logo[DEPLOYED].oof_predictions, logo[DEPLOYED].oof_scores)

    comparisons = {}
    p_f1, p_auc = {}, {}
    for name, result in logo.items():
        if name == DEPLOYED:
            continue
        pred = result.oof_predictions[rows]
        score = result.oof_scores[rows]
        d_f1, draws_f1 = stats.cluster_bootstrap(
            g, lambda i: stats.f1_from(y[i], pred[i]) - stats.f1_from(y[i], ref_pred[i]), n_boot=n_boot
        )
        d_auc, draws_auc = stats.cluster_bootstrap(
            g, lambda i: stats.auc_from(y[i], score[i]) - stats.auc_from(y[i], ref_score[i]), n_boot=n_boot
        )
        folds = {f["group"]: f["f1"] for f in result.per_fold if f["n_test_positive"]}
        common = [k for k in ref_fold if k in folds and folds[k] is not None]
        wilcoxon = stats.wilcoxon_paired([folds[k] for k in common], [ref_fold[k] for k in common])
        _, el, ep, _ = event_table(data, result.oof_predictions, result.oof_scores)
        correct_ref = ref_ep == ref_el
        correct_other = ep == el
        b = int(np.sum(correct_ref & ~correct_other))
        c = int(np.sum(~correct_ref & correct_other))
        p_f1[name] = stats.bootstrap_p_value(draws_f1)
        p_auc[name] = stats.bootstrap_p_value(draws_auc)
        comparisons[name] = {
            "delta_segment_f1": d_f1.as_dict(),
            "delta_segment_auc": d_auc.as_dict(),
            "p_bootstrap_f1": p_f1[name],
            "p_bootstrap_auc": p_auc[name],
            "p_wilcoxon_fold_f1": wilcoxon,
            "n_folds_paired": len(common),
            "event_mcnemar": {"deployed_only_correct": b, "other_only_correct": c, "p": stats.mcnemar_exact(b, c)},
        }
    for name, p in stats.holm(p_f1).items():
        comparisons[name]["p_holm_f1"] = p
    for name, p in stats.holm(p_auc).items():
        comparisons[name]["p_holm_auc"] = p
    return comparisons


# --------------------------------------------------------------------------- #
# continuous streams
# --------------------------------------------------------------------------- #
def stream_probabilities(streams, models_by_group, fallback):
    probs = {}
    for s in streams:
        model = models_by_group.get(s.group, fallback)
        probs[s.source_id] = score_stream(model, s)
    return probs


TOLERANCES_S = (0.0, 2.5, 5.0, 10.0, 20.0)


def stream_summary(streams, probs, policy_for, n_boot, tolerance_after_s=0.0):
    outcomes = evaluate_streams(streams, probs, policy_for, tolerance_after_s=tolerance_after_s)
    pooled = summarise_outcomes(outcomes)
    groups = np.array([o.group for o in outcomes], dtype=object)

    def ratio(num, den):
        return lambda i: (sum(getattr(outcomes[j], num) for j in i) /
                          max(1e-12, sum(getattr(outcomes[j], den) for j in i)))

    far_h, _ = stats.cluster_bootstrap(
        groups, lambda i: 3600.0 * ratio("false_alarms", "exposure_s")(i), n_boot=n_boot
    )
    ep, _ = stats.cluster_bootstrap(groups, ratio("episodes_detected", "n_episodes"), n_boot=n_boot)
    sp, _ = stats.cluster_bootstrap(groups, ratio("spins_detected", "n_spins"), n_boot=n_boot)
    pooled["false_alarms_per_hour_ci_bootstrap"] = far_h.as_dict()
    pooled["false_alarms_per_hour_ci_exact"] = stats.poisson_rate_interval(
        pooled["false_alarms"], pooled["exposure_hours"]
    ).as_dict()
    pooled["episode_sensitivity_ci_bootstrap"] = ep.as_dict()
    pooled["episode_sensitivity_ci_wilson"] = stats.wilson_interval(
        pooled["episodes_detected"], pooled["n_episodes"]
    ).as_dict()
    pooled["spin_sensitivity_ci_bootstrap"] = sp.as_dict()
    pooled["latencies_s"] = [l for o in outcomes for l in o.latencies_s]
    return pooled, outcomes


def sensor_range(recordings) -> dict:
    """How often the Shimmer3 channels sit at their full-scale limits.

    The training data saturate; the collar's MPU6050 is configured for a wider
    range and would not.  Reported so the transfer analysis can say how much of
    the signal the training distribution never saw.
    """
    X = np.concatenate([r.channels() for r in recordings])
    y = np.concatenate([r.labels for r in recordings]).astype(bool)
    gyro, acc = np.abs(X[:, 3:6]), np.abs(X[:, 0:3])
    g_fs, a_fs = float(gyro.max()), float(acc.max())
    g_sat = np.any(gyro >= 0.999 * g_fs, axis=1)
    a_sat = np.any(acc >= 0.999 * a_fs, axis=1)
    return {
        "gyro_full_scale_dps": g_fs,
        "accel_full_scale_ms2": a_fs,
        "gyro_saturated_fraction_spin": float(g_sat[y].mean()),
        "gyro_saturated_fraction_nonspin": float(g_sat[~y].mean()),
        "accel_saturated_fraction_spin": float(a_sat[y].mean()),
        "accel_saturated_fraction_nonspin": float(a_sat[~y].mean()),
        "gyro_p99_spin_dps": float(np.percentile(np.linalg.norm(X[y, 3:6], axis=1), 99)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    n_boot = 200 if args.quick else stats.N_BOOT
    started = time.time()

    print("[1/7] loading ...", flush=True)
    data = prepare(args.dataset_dir, DEFAULT_CONFIG)
    recordings = load_recordings(args.dataset_dir)
    streams = recording_streams(recordings)
    group_session = {g: g.split("/")[0] for g in set(data.groups.tolist())}
    session_device = {r.session: r.device for r in recordings}

    print("[2/7] LOGO with fold models ...", flush=True)
    logo = run_logo(data, keep_models=True)

    print(f"[3/7] cluster-bootstrap intervals ({n_boot} draws) ...", flush=True)
    intervals = {name: model_intervals(data, result, n_boot) for name, result in logo.items()}
    comparisons = paired_comparisons(data, logo, n_boot)

    print("[4/7] shift protocols: leave-one-session-out, leave-one-device-out ...", flush=True)
    sessions = np.array([group_session[g] for g in data.groups], dtype=object)
    devices = np.array([session_device[s] for s in sessions], dtype=object)
    shift = {}
    for label, folds in (("leave_one_session_out", sessions), ("leave_one_device_out", devices)):
        res = run_logo(data, models=[BASELINE_NAME, DEPLOYED, REFERENCE], fold_labels=folds)
        shift[label] = {
            name: {
                "segment": r.segment_metrics,
                "per_fold": [
                    {k: f[k] for k in ("group", "n_test_windows", "n_test_positive", "f1", "recall", "specificity", "roc_auc")}
                    for f in r.per_fold
                ],
                "event": _event_metrics(data, r),
            }
            for name, r in res.items()
        }

    print("[5/7] nested operating-point selection ...", flush=True)
    nested = {}
    nested_folds = {}
    for name in NESTED_MODELS:
        if name == BASELINE_NAME:
            folds = _nested_baseline(data)
        else:
            folds = run_nested(data, name)
        nested_folds[name] = folds
        pooled = pool_nested(folds, data.summary["event_seconds"])
        fg = np.array([f.group for f in folds], dtype=object)
        sens, _ = stats.cluster_bootstrap(
            fg,
            lambda i: sum(folds[j].outer["detected"] for j in i)
            / max(1, sum(folds[j].outer["detected"] + folds[j].outer["missed"] for j in i)),
            n_boot=n_boot,
        )
        far, _ = stats.cluster_bootstrap(
            fg,
            lambda i: sum(folds[j].outer["false_alarms"] for j in i)
            / max(1, sum(folds[j].outer["false_alarms"] + folds[j].outer["true_negatives"] for j in i)),
            n_boot=n_boot,
        )
        pooled["sensitivity_ci"] = sens.as_dict()
        pooled["false_alarm_rate_ci"] = far.as_dict()
        pooled["per_fold"] = [
            {"group": f.group, "policy": f.policy, **{k: v for k, v in f.outer.items() if k != "latencies"}}
            for f in folds
        ]
        nested[name] = pooled
        print(f"      {name:22s} sens={pooled['sensitivity']:.3f} far={pooled['false_alarm_rate']:.3f} "
              f"policies={pooled['policy_counts']}")

    # Single-level ("optimistic") selection on the same OOF scores, for the
    # optimism estimate.
    single = {}
    for name in NESTED_MODELS:
        s_streams, s_labels, s_onsets = event_probability_streams(data, logo[name].oof_scores)
        grid = BASELINE_THRESHOLDS if name == BASELINE_NAME else SWEEP_THRESHOLDS
        sweep = sweep_grid(
            s_streams, s_labels, s_onsets, data.summary["event_seconds"], data.config, thresholds=grid
        )
        single[name] = select_operating_point(sweep)

    print("[6/7] continuous-stream evaluation ...", flush=True)
    continuous = {}
    stream_outcomes = {}
    for name in NESTED_MODELS:
        fallback = _fit_all(name, data)
        fold_models = {f.group: f.model for f in nested_folds[name]}
        probs = stream_probabilities(streams, fold_models, fallback)
        fold_policy = {f.group: f.policy for f in nested_folds[name]}
        sp = single[name]
        fixed = GatePolicy(sp["vote_threshold"], sp["k"], sp["n"])
        variants = {}
        for refractory in (0.0, DEFAULT_CONFIG.refractory_seconds):
            def nested_policy(stream, r=refractory):
                p = fold_policy.get(stream.group) or {"vote_threshold": fixed.threshold, "k": fixed.k, "n": fixed.n}
                return GatePolicy(p["vote_threshold"], p["k"], p["n"], r)

            def fixed_policy(stream, r=refractory):
                return GatePolicy(fixed.threshold, fixed.k, fixed.n, r)

            tag = f"refractory_{int(refractory)}s"
            variants[f"nested_{tag}"], outs = stream_summary(streams, probs, nested_policy, n_boot)
            variants[f"single_{tag}"], _ = stream_summary(streams, probs, fixed_policy, n_boot)
            if refractory and name == DEPLOYED:
                stream_outcomes = [o.as_dict() for o in outs]
            # Scoring-tolerance sensitivity, nested policy, cheap bootstrap.
            variants[f"tolerance_{tag}"] = {
                str(tol): {
                    k: v
                    for k, v in stream_summary(streams, probs, nested_policy, 200, tol)[0].items()
                    if k != "latencies_s"
                }
                for tol in TOLERANCES_S
            }
        continuous[name] = variants
        v = variants["nested_refractory_60s"]
        print(f"      {name:22s} episode sens={v['episode_sensitivity']:.3f} "
              f"FA/h={v['false_alarms_per_hour']:.1f} over {v['exposure_hours']:.2f} h")

    print("[7/7] writing research.json ...", flush=True)
    research = {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_boot": n_boot,
        "deployed_model": DEPLOYED,
        "reference_model": REFERENCE,
        "logo_intervals": intervals,
        "paired_vs_deployed": comparisons,
        "shift": shift,
        "single_level_operating_point": single,
        "nested": nested,
        "continuous": continuous,
        "continuous_outcomes_deployed": stream_outcomes,
        "dataset_hours": sum(s.duration_s for s in streams) / 3600.0,
        "sensor_range": sensor_range(recordings),
        "n_streams": len(streams),
        "runtime_seconds": round(time.time() - started, 1),
    }
    out = args.artifact_dir / "research.json"
    out.write_text(json.dumps(to_jsonable(research), indent=2) + "\n")
    print(f"wrote {out} in {research['runtime_seconds']} s")
    return 0


def _event_metrics(data, result):
    from canine_alert.evaluate import aggregate_to_events

    m = aggregate_to_events(data, result.oof_predictions, result.oof_scores)
    return {k: m[k] for k in ("f1", "recall", "specificity", "confusion_matrix")}


def _fit_all(name, data):
    if name == BASELINE_NAME:
        return GyroMagnitudeBaseline().fit(data.gyro_statistic, data.y)
    return build_model(name, data.feature_names, data.config).fit(data.features, data.y)


def _nested_baseline(data):
    """Nested selection for the heuristic: cheap enough to run serially."""
    from canine_alert.nested import NestedFold
    from canine_alert.verification import sweep_policies

    groups = data.groups
    folds = []
    for group in sorted(set(groups.tolist())):
        test = np.flatnonzero(groups == group)
        train = np.flatnonzero(groups != group)
        inner = np.full(len(data.segments), np.nan)
        for h in sorted(set(groups[train].tolist())):
            it = train[groups[train] == h]
            tr = train[groups[train] != h]
            m = GyroMagnitudeBaseline().fit(data.gyro_statistic[tr], data.y[tr])
            inner[it] = m.predict_proba(data.gyro_statistic[it])[:, 1]
        s, l, o = event_probability_streams(data, inner)
        chosen = select_operating_point(
            sweep_grid(s, l, o, data.summary["event_seconds"], data.config, thresholds=BASELINE_THRESHOLDS)
        )
        model = GyroMagnitudeBaseline().fit(data.gyro_statistic[train], data.y[train])
        full = np.full(len(data.segments), np.nan)
        full[test] = model.predict_proba(data.gyro_statistic[test])[:, 1]
        s, l, o = event_probability_streams(data, full)
        row = sweep_policies(s, l, [(chosen["k"], chosen["n"])], data.config,
                             probability_threshold=chosen["vote_threshold"], onset_by_event=o,
                             event_seconds=data.summary["event_seconds"])[0]
        folds.append(NestedFold(
            group=group,
            policy={"vote_threshold": chosen["vote_threshold"], "k": chosen["k"], "n": chosen["n"]},
            inner_sensitivity=chosen["sensitivity"],
            inner_false_alarm_rate=chosen["false_alarm_rate"],
            outer={k: row[k] for k in ("detected", "missed", "false_alarms", "true_negatives",
                                       "mean_latency_s", "median_latency_s")},
            model=model,
        ))
    return folds


if __name__ == "__main__":
    raise SystemExit(main())
