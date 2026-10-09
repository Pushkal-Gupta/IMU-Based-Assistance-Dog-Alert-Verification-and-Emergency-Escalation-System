"""Statistics used for every interval and test in the paper."""

from __future__ import annotations

import numpy as np
import pytest
from scipy import stats as st
from sklearn.metrics import f1_score, roc_auc_score

from canine_alert import stats


def test_auc_matches_sklearn_including_ties(rng):
    y = rng.integers(0, 2, 300)
    s = np.round(rng.normal(size=300) + y, 1)  # rounding forces ties
    assert stats.auc_from(y, s) == pytest.approx(roc_auc_score(y, s))


def test_f1_matches_sklearn(rng):
    y = rng.integers(0, 2, 200)
    p = rng.integers(0, 2, 200)
    assert stats.f1_from(y, p) == pytest.approx(f1_score(y, p))


def test_cluster_bootstrap_resamples_groups_not_rows():
    # Two groups with very different means: a row bootstrap would give a
    # tight interval around 0.5, a group bootstrap must span both groups.
    groups = np.array(["a"] * 100 + ["b"] * 100, dtype=object)
    values = np.array([0.0] * 100 + [1.0] * 100)
    interval, draws = stats.cluster_bootstrap(groups, lambda i: values[i].mean(), n_boot=500)
    assert interval.estimate == pytest.approx(0.5)
    assert interval.low == pytest.approx(0.0)
    assert interval.high == pytest.approx(1.0)
    assert set(np.round(draws, 6)) <= {0.0, 0.5, 1.0}


def test_bootstrap_is_deterministic_for_a_seed(rng):
    groups = np.repeat(np.arange(10), 5).astype(object)
    values = rng.normal(size=50)
    a, _ = stats.cluster_bootstrap(groups, lambda i: values[i].mean(), n_boot=200, seed=7)
    b, _ = stats.cluster_bootstrap(groups, lambda i: values[i].mean(), n_boot=200, seed=7)
    assert (a.low, a.high) == (b.low, b.high)


def test_bootstrap_p_value_is_one_for_a_degenerate_null_distribution():
    assert stats.bootstrap_p_value(np.zeros(100)) == 1.0
    assert stats.bootstrap_p_value(np.ones(100)) == 0.0


def test_garwood_interval_matches_known_values():
    # 0 events: upper bound -ln(0.025) = 3.689; 5 events: 1.623 -- 11.668.
    zero = stats.poisson_rate_interval(0, 1.0)
    assert zero.low == 0.0 and zero.high == pytest.approx(3.689, abs=1e-3)
    five = stats.poisson_rate_interval(5, 1.0)
    assert (five.low, five.high) == (pytest.approx(1.623, abs=1e-3), pytest.approx(11.668, abs=1e-3))
    # Rates scale with exposure.
    assert stats.poisson_rate_interval(5, 0.5).estimate == pytest.approx(10.0)


def test_wilson_interval_stays_inside_unit_interval():
    for k, n in ((0, 10), (10, 10), (3, 7)):
        w = stats.wilson_interval(k, n)
        assert 0.0 <= w.low <= w.estimate <= w.high <= 1.0


def test_mcnemar_exact_matches_binomial():
    assert stats.mcnemar_exact(12, 1) == pytest.approx(2 * st.binom.cdf(1, 13, 0.5))
    assert stats.mcnemar_exact(0, 0) == 1.0


def test_holm_is_monotone_and_never_below_raw():
    raw = {"a": 0.01, "b": 0.04, "c": 0.03}
    adj = stats.holm(raw)
    assert adj["a"] == pytest.approx(0.03)
    assert adj["c"] == pytest.approx(0.06)
    assert adj["b"] == pytest.approx(0.06)  # monotone step-down
    assert all(adj[k] >= raw[k] for k in raw)


def test_wilcoxon_returns_one_when_nothing_differs():
    assert stats.wilcoxon_paired([0.5, 0.6], [0.5, 0.6]) == 1.0
