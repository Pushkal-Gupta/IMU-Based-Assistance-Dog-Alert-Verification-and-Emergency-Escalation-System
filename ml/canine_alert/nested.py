"""Nested cross-validation of the verification-gate operating point.

The single-level sweep in ``run_experiments.py`` chooses the gate policy by
looking at the same out-of-fold predictions it then reports, so its sensitivity
is optimistic by construction.  Here the choice is made *inside* each outer
fold:

    for each held-out group g:
        inner LOGO over the remaining groups  -> out-of-fold scores for them
        sweep the policy grid on those scores -> choose (threshold, K, N)
        fit on all remaining groups           -> score g
        apply the chosen policy to g          -> outcome for g

Nothing about g influences the policy that is applied to it, so the pooled
outer outcomes are an unbiased estimate of the *procedure* -- including the
variability of which policy it picks.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from joblib import Parallel, delayed

from .config import DEFAULT_CONFIG
from .evaluate import ExperimentData, event_probability_streams
from .models import build_model, predict_scores
from .verification import (
    MAX_FALSE_ALARM_RATE,
    SWEEP_POLICIES,
    SWEEP_THRESHOLDS,
    select_operating_point,
    sweep_grid,
    sweep_policies,
)


def _fit(name: str, data: ExperimentData, rows: np.ndarray):
    model = build_model(name, data.feature_names, data.config)
    # Folds run in parallel processes; nested thread pools only add contention.
    if "n_jobs" in model.named_steps["clf"].get_params():
        model.set_params(clf__n_jobs=1)
    model.fit(data.features[rows], data.y[rows])
    return model


def _streams_for(data: ExperimentData, rows: np.ndarray, scores: np.ndarray):
    full = np.full(len(data.segments), np.nan)
    full[rows] = scores
    return event_probability_streams(data, full)


@dataclass
class NestedFold:
    group: str
    policy: dict | None
    inner_sensitivity: float
    inner_false_alarm_rate: float
    outer: dict
    model: object = field(repr=False, default=None)
    outer_scores: np.ndarray = field(repr=False, default=None)
    outer_rows: np.ndarray = field(repr=False, default=None)


def _outer_fold(
    name: str,
    data: ExperimentData,
    group: str,
    max_far: float,
    event_seconds: float,
) -> NestedFold:
    groups = data.groups
    test = np.flatnonzero(groups == group)
    train = np.flatnonzero(groups != group)

    inner_scores = np.full(len(data.segments), np.nan)
    for inner_group in sorted(set(groups[train].tolist())):
        inner_test = train[groups[train] == inner_group]
        inner_train = train[groups[train] != inner_group]
        if len(np.unique(data.y[inner_train])) < 2:
            continue
        model = _fit(name, data, inner_train)
        inner_scores[inner_test] = predict_scores(model, data.features[inner_test])

    streams, labels, onsets = event_probability_streams(data, inner_scores)
    sweep = sweep_grid(streams, labels, onsets, event_seconds, data.config)
    chosen = select_operating_point(sweep, max_far)

    outer_model = _fit(name, data, train)
    outer_scores = predict_scores(outer_model, data.features[test])
    o_streams, o_labels, o_onsets = _streams_for(data, test, outer_scores)
    if chosen is None:
        outer = {"detected": 0, "missed": sum(o_labels.values()), "false_alarms": 0,
                 "true_negatives": len(o_labels) - sum(o_labels.values()), "latencies": []}
    else:
        row = sweep_policies(
            o_streams,
            o_labels,
            [(chosen["k"], chosen["n"])],
            data.config,
            probability_threshold=chosen["vote_threshold"],
            onset_by_event=o_onsets,
            event_seconds=event_seconds,
        )[0]
        outer = {
            "detected": row["detected"],
            "missed": row["missed"],
            "false_alarms": row["false_alarms"],
            "true_negatives": row["true_negatives"],
            "mean_latency_s": row["mean_latency_s"],
            "median_latency_s": row["median_latency_s"],
        }
    return NestedFold(
        group=group,
        policy=(
            {"vote_threshold": chosen["vote_threshold"], "k": chosen["k"], "n": chosen["n"]}
            if chosen
            else None
        ),
        inner_sensitivity=float(chosen["sensitivity"]) if chosen else float("nan"),
        inner_false_alarm_rate=float(chosen["false_alarm_rate"]) if chosen else float("nan"),
        outer=outer,
        model=outer_model,
        outer_scores=outer_scores,
        outer_rows=test,
    )


def run_nested(
    data: ExperimentData,
    model_name: str,
    max_false_alarm_rate: float = MAX_FALSE_ALARM_RATE,
    n_jobs: int = -1,
) -> list[NestedFold]:
    event_seconds = data.summary["event_seconds"]
    groups = sorted(set(data.groups.tolist()))
    folds = Parallel(n_jobs=n_jobs)(
        delayed(_outer_fold)(model_name, data, g, max_false_alarm_rate, event_seconds) for g in groups
    )
    return list(folds)


def pool_nested(folds: list[NestedFold], event_seconds: float) -> dict:
    detected = sum(f.outer["detected"] for f in folds)
    missed = sum(f.outer["missed"] for f in folds)
    false_alarms = sum(f.outer["false_alarms"] for f in folds)
    negatives = false_alarms + sum(f.outer["true_negatives"] for f in folds)
    policies: dict[str, int] = {}
    for f in folds:
        key = "none" if f.policy is None else f"{f.policy['k']}-of-{f.policy['n']}@{f.policy['vote_threshold']:.2f}"
        policies[key] = policies.get(key, 0) + 1
    hours = negatives * event_seconds / 3600.0
    return {
        "detected": detected,
        "missed": missed,
        "sensitivity": detected / (detected + missed) if detected + missed else float("nan"),
        "false_alarms": false_alarms,
        "negatives": negatives,
        "false_alarm_rate": false_alarms / negatives if negatives else float("nan"),
        "negative_hours": hours,
        "false_alarms_per_hour": false_alarms / hours if hours else float("nan"),
        "policy_counts": dict(sorted(policies.items(), key=lambda kv: -kv[1])),
        "mean_inner_sensitivity": float(np.nanmean([f.inner_sensitivity for f in folds])),
    }
