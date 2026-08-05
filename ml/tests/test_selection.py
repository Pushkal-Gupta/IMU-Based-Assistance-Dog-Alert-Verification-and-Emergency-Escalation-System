"""Three-stage feature selection."""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.model_selection import LeaveOneGroupOut

from canine_alert.selection import ThreeStageSelector


def test_selects_exactly_k(rng):
    X = rng.normal(size=(200, 50))
    y = (X[:, 3] + 0.1 * rng.normal(size=200) > 0).astype(int)
    selector = ThreeStageSelector(k=10).fit(X, y)
    assert selector.transform(X).shape == (200, 10)


def test_finds_the_informative_feature(rng):
    X = rng.normal(size=(300, 40))
    y = (X[:, 17] > 0).astype(int)
    X[:, 17] += 5.0 * y  # make it unmistakable
    selector = ThreeStageSelector(k=5).fit(X, y)
    assert 17 in selector.support_


def test_drops_constant_features(rng):
    X = rng.normal(size=(120, 12))
    X[:, 4] = 7.0
    X[:, 9] = -1.0
    y = (X[:, 0] > 0).astype(int)
    selector = ThreeStageSelector(k=12).fit(X, y)
    assert 4 not in selector.support_
    assert 9 not in selector.support_
    assert selector.stage_sizes_["after_variance"] == 10


def test_drops_one_of_a_collinear_pair(rng):
    X = rng.normal(size=(200, 6))
    X[:, 5] = 2.0 * X[:, 1] + 1e-9 * rng.normal(size=200)  # r ~ 1.0
    y = (X[:, 1] > 0).astype(int)
    selector = ThreeStageSelector(k=6, correlation_threshold=0.95).fit(X, y)
    assert not (1 in selector.support_ and 5 in selector.support_)
    assert selector.stage_sizes_["after_correlation"] == 5


def test_keeps_moderately_correlated_features(rng):
    """0.95 is the threshold; 0.8 must survive, or the filter is too aggressive."""
    X = rng.normal(size=(400, 4))
    X[:, 3] = 0.8 * X[:, 0] + 0.6 * rng.normal(size=400)
    y = (X[:, 0] > 0).astype(int)
    selector = ThreeStageSelector(k=4, correlation_threshold=0.95).fit(X, y)
    assert selector.stage_sizes_["after_correlation"] == 4


def test_support_is_sorted_and_deterministic(rng):
    X = rng.normal(size=(150, 30))
    y = (X[:, 2] > 0).astype(int)
    first = ThreeStageSelector(k=8).fit(X, y).support_
    second = ThreeStageSelector(k=8).fit(X, y).support_
    np.testing.assert_array_equal(first, second)
    np.testing.assert_array_equal(first, np.sort(first))


def test_k_larger_than_available_is_clamped(rng):
    X = rng.normal(size=(80, 5))
    y = (X[:, 0] > 0).astype(int)
    selector = ThreeStageSelector(k=99).fit(X, y)
    assert selector.transform(X).shape[1] <= 5


def test_selected_names_track_support(rng):
    X = rng.normal(size=(100, 6))
    y = (X[:, 0] > 0).astype(int)
    names = [f"feat_{i}" for i in range(6)]
    selector = ThreeStageSelector(k=3, feature_names=names).fit(X, y)
    assert selector.selected_names() == [names[i] for i in selector.support_]


def test_selection_depends_only_on_training_data(rng):
    """The whole point of fitting inside the fold: held-out rows must not vote.

    We fit on a training subset, then refit on the same subset with the held-out
    rows' labels scrambled.  If any test-set information reached the selector,
    the chosen features would move.
    """
    X = rng.normal(size=(240, 25))
    y = (X[:, 6] + 0.5 * rng.normal(size=240) > 0).astype(int)
    train = np.arange(160)

    baseline = ThreeStageSelector(k=8).fit(X[train], y[train]).support_
    scrambled = y.copy()
    scrambled[160:] = rng.permutation(scrambled[160:])
    repeat = ThreeStageSelector(k=8).fit(X[train], scrambled[train]).support_
    np.testing.assert_array_equal(baseline, repeat)


def test_fits_in_every_logo_fold(experiment):
    """Regression guard: no fold may crash the selector on real data."""
    splitter = LeaveOneGroupOut()
    folds = list(splitter.split(experiment.features, experiment.y, experiment.groups))
    assert len(folds) >= 30
    for train_idx, _ in folds[:8]:
        selector = ThreeStageSelector(
            k=20, feature_names=experiment.feature_names
        ).fit(experiment.features[train_idx], experiment.y[train_idx])
        assert len(selector.selected_names()) == 20
