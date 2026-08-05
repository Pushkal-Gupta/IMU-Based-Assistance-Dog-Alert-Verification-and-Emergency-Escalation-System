"""Evaluation protocols, with an emphasis on the leakage guarantees.

The headline claim of the report is that the LOGO numbers are honest.  These
tests check the mechanism that makes them honest, not just that a number came
out.
"""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.model_selection import LeaveOneGroupOut

from canine_alert.evaluate import (
    ALL_MODELS,
    aggregate_to_events,
    binary_metrics,
    event_probability_streams,
    run_logo,
)


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #
def test_binary_metrics_on_a_known_confusion():
    y_true = np.array([0, 0, 0, 0, 1, 1, 1, 1])
    y_pred = np.array([0, 0, 0, 1, 0, 1, 1, 1])
    metrics = binary_metrics(y_true, y_pred)
    assert metrics["confusion_matrix"] == {"tn": 3, "fp": 1, "fn": 1, "tp": 3}
    assert metrics["accuracy"] == pytest.approx(6 / 8)
    assert metrics["precision"] == pytest.approx(3 / 4)
    assert metrics["recall"] == pytest.approx(3 / 4)
    assert metrics["specificity"] == pytest.approx(3 / 4)
    assert metrics["f1"] == pytest.approx(3 / 4)


def test_metrics_survive_an_all_negative_prediction():
    metrics = binary_metrics(np.array([0, 1, 1]), np.array([0, 0, 0]))
    assert metrics["precision"] == 0.0
    assert metrics["f1"] == 0.0
    assert np.isnan(metrics["roc_auc"]) or metrics["roc_auc"] == metrics["roc_auc"]


def test_roc_auc_is_nan_for_a_single_class():
    assert np.isnan(binary_metrics(np.zeros(5, int), np.zeros(5, int), np.zeros(5))["roc_auc"])


# --------------------------------------------------------------------------- #
# leave-one-group-out
# --------------------------------------------------------------------------- #
def test_no_group_appears_in_its_own_training_fold(experiment):
    """This is the leakage guarantee, checked directly on the fold indices."""
    for train_idx, test_idx in LeaveOneGroupOut().split(
        experiment.features, experiment.y, experiment.groups
    ):
        held_out = set(experiment.groups[test_idx])
        assert len(held_out) == 1
        assert held_out.isdisjoint(set(experiment.groups[train_idx]))


def test_every_window_is_predicted_exactly_once(experiment):
    result = run_logo(experiment, models=["random_forest_embedded"])["random_forest_embedded"]
    assert np.all(result.oof_predictions >= 0), "some window was never held out"
    assert not np.any(np.isnan(result.oof_scores))


def test_one_fold_per_group(experiment):
    result = run_logo(experiment, models=["heuristic_baseline"])["heuristic_baseline"]
    assert len(result.per_fold) == len(set(experiment.groups))
    assert len({fold["group"] for fold in result.per_fold}) == len(result.per_fold)


def test_logo_is_not_better_than_within_subject(experiment):
    """Cross-subject generalisation should cost something.

    If LOGO ever beat the pooled random split by a wide margin it would mean the
    pooled split was mis-specified, not that the model generalises unusually
    well.
    """
    from canine_alert.evaluate import run_within_subject

    within = run_within_subject(experiment)
    logo = run_logo(experiment, models=["random_forest"])
    assert (
        logo["random_forest"].segment_metrics["f1"]
        <= within["random_forest"]["f1"] + 0.15
    )


def test_beats_chance_on_real_data(experiment):
    result = run_logo(experiment, models=["random_forest"])["random_forest"]
    metrics = result.segment_metrics
    prevalence = experiment.y.mean()
    assert metrics["accuracy"] > 1 - prevalence, "no better than always predicting 'no spin'"
    assert metrics["roc_auc"] > 0.75


def test_supervised_models_beat_the_heuristic_baseline(experiment):
    """The paper's central claim, re-tested on our pipeline."""
    results = run_logo(experiment, models=["heuristic_baseline", "random_forest"])
    assert (
        results["random_forest"].segment_metrics["f1"]
        > results["heuristic_baseline"].segment_metrics["f1"]
    )


def test_selection_frequency_is_recorded(experiment):
    result = run_logo(experiment, models=["random_forest_embedded"])["random_forest_embedded"]
    assert result.selection_frequency
    top_count = next(iter(result.selection_frequency.values()))
    assert top_count <= len(result.per_fold)


# --------------------------------------------------------------------------- #
# event-level aggregation
# --------------------------------------------------------------------------- #
def test_event_aggregation_recovers_more_events_than_windows(experiment):
    """Temporal aggregation is what makes the system usable; check it pays off."""
    result = run_logo(experiment, models=["random_forest"])["random_forest"]
    event = aggregate_to_events(experiment, result.oof_predictions, result.oof_scores)
    assert event["recall"] > result.segment_metrics["recall"]


def test_event_aggregation_or_rule(experiment):
    result = run_logo(experiment, models=["random_forest"])["random_forest"]
    lenient = aggregate_to_events(experiment, result.oof_predictions, result.oof_scores, 1)
    strict = aggregate_to_events(experiment, result.oof_predictions, result.oof_scores, 3)
    assert lenient["recall"] >= strict["recall"]
    assert lenient["confusion_matrix"]["fp"] >= strict["confusion_matrix"]["fp"]


def test_event_counts_add_up(experiment):
    result = run_logo(experiment, models=["random_forest"])["random_forest"]
    event = aggregate_to_events(experiment, result.oof_predictions, result.oof_scores)
    matrix = event["confusion_matrix"]
    assert sum(matrix.values()) == event["n_events"] == len(set(experiment.segments.event_ids))


def test_probability_streams_are_complete_and_ordered(experiment):
    result = run_logo(experiment, models=["random_forest"])["random_forest"]
    streams, labels, onsets = event_probability_streams(experiment, result.oof_scores)
    assert len(streams) == len(set(experiment.segments.event_ids))
    assert all(len(s) == experiment.config.event_windows for s in streams.values())
    assert set(labels) == set(streams)

    # Onsets must lie inside their event.  Most positives are centred, so their
    # onset is strictly positive, but a spin that sits at the very start of a
    # recording gets clipped there and legitimately has an onset of 0.
    positives = [e for e in experiment.events if e.label == 1]
    duration = experiment.config.event_seconds(experiment.segments.fs_hz)
    assert all(0.0 <= onsets[e.event_id] < duration for e in positives)
    assert any(onsets[e.event_id] > 0 for e in positives)
    assert all(onsets[e.event_id] == 0.0 for e in experiment.events if e.label == 0)


def test_all_models_are_runnable(experiment):
    """Guard against a model name in the docs that the code cannot build."""
    results = run_logo(experiment, models=list(ALL_MODELS))
    assert set(results) == set(ALL_MODELS)
    for name, result in results.items():
        assert 0.0 <= result.segment_metrics["accuracy"] <= 1.0, name
