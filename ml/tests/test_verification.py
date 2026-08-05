"""The multi-stage verification gate.

These tests are the specification the C++ port in
``firmware/collar/src/verify.cpp`` must satisfy; ``firmware/test/test_verify.c``
runs the same cases against the firmware implementation.
"""

from __future__ import annotations

import numpy as np
import pytest

from canine_alert.verification import (
    Alert,
    VerificationGate,
    sweep_policies,
    earliest_alert_time_s,
)

STRIDE = 1.3


def gate(**kwargs) -> VerificationGate:
    defaults = dict(k=2, n=3, probability_threshold=0.5, refractory_seconds=0.0, stride_seconds=STRIDE)
    return VerificationGate(**{**defaults, **kwargs})


def test_single_positive_does_not_fire_when_k_is_two():
    assert gate().push(0.99) is None


def test_fires_on_the_kth_positive():
    g = gate()
    assert g.push(0.9) is None
    alert = g.push(0.8)
    assert isinstance(alert, Alert)
    assert alert.votes == 2
    assert alert.window_index == 1


def test_non_consecutive_positives_still_count_within_n():
    """2-of-3 means 2 anywhere in the last 3, not 2 in a row."""
    g = gate(k=2, n=3)
    assert g.push(0.9) is None
    assert g.push(0.1) is None
    assert g.push(0.9) is not None


def test_positives_further_apart_than_n_do_not_accumulate():
    g = gate(k=2, n=3)
    assert g.push(0.9) is None
    assert g.push(0.1) is None
    assert g.push(0.1) is None
    assert g.push(0.9) is None, "the first positive should have aged out of the window"


def test_threshold_is_inclusive():
    g = gate(k=1, n=1, probability_threshold=0.45)
    assert g.push(0.45) is not None


def test_below_threshold_never_votes():
    g = gate(k=1, n=1, probability_threshold=0.45)
    assert g.push(0.4499) is None


def test_confidence_averages_only_the_voting_windows():
    g = gate(k=2, n=3)
    g.push(0.9)
    g.push(0.1)  # does not vote, must not drag the average down
    alert = g.push(0.7)
    assert alert.confidence == pytest.approx(0.8)


def test_refractory_suppresses_a_second_alert():
    g = gate(k=1, n=1, refractory_seconds=60.0)
    assert g.push(0.9, timestamp_s=0.0) is not None
    assert g.push(0.9, timestamp_s=30.0) is None
    assert g.push(0.9, timestamp_s=59.9) is None


def test_refractory_releases_after_the_window():
    g = gate(k=1, n=1, refractory_seconds=60.0)
    g.push(0.9, timestamp_s=0.0)
    assert g.push(0.9, timestamp_s=60.0) is not None


def test_evidence_is_cleared_after_firing():
    """Otherwise the gate re-fires on stale votes the instant refractory ends."""
    g = gate(k=2, n=3, refractory_seconds=10.0)
    g.push(0.9, timestamp_s=0.0)
    g.push(0.9, timestamp_s=1.3)  # fires
    assert g.push(0.9, timestamp_s=11.0) is None, "needs k fresh votes, not one"
    assert g.push(0.9, timestamp_s=12.3) is not None


def test_default_timestamps_follow_the_stride():
    g = gate(k=1, n=1)
    g.push(0.9)
    alert = g.push(0.9)
    assert alert.timestamp_s == pytest.approx(STRIDE)


def test_reset_clears_all_state():
    g = gate(k=2, n=3, refractory_seconds=60.0)
    g.push(0.9, 0.0)
    g.push(0.9, 1.3)
    g.reset()
    assert g.push(0.9, 2.0) is None  # k not yet reached again
    assert g.push(0.9, 3.3) is not None  # and refractory forgotten


def test_k_of_one_fires_immediately():
    assert gate(k=1, n=1).push(0.51) is not None


def test_run_collects_every_alert():
    g = gate(k=1, n=1, refractory_seconds=0.0)
    alerts = g.run([0.9, 0.1, 0.9, 0.9])
    assert [a.window_index for a in alerts] == [0, 2, 3]


def test_run_is_repeatable():
    g = gate(k=2, n=3)
    stream = [0.9, 0.2, 0.8, 0.1, 0.9, 0.95]
    assert [a.window_index for a in g.run(stream)] == [a.window_index for a in g.run(stream)]


def test_invalid_policy_rejected():
    with pytest.raises(ValueError, match="1 <= k <= n"):
        VerificationGate(k=4, n=2)
    with pytest.raises(ValueError, match="1 <= k <= n"):
        VerificationGate(k=0, n=2)


def test_higher_k_never_increases_sensitivity():
    """Monotonicity: requiring more evidence cannot detect more events.

    This is the property the operating-point table is read against -- if it
    failed, the sweep would be meaningless.
    """
    rng = np.random.default_rng(7)
    streams = {f"e{i}": rng.uniform(0, 1, size=5) for i in range(120)}
    labels = {k: int(v.mean() > 0.5) for k, v in streams.items()}
    rows = sweep_policies(streams, labels, [(1, 5), (2, 5), (3, 5), (4, 5)])
    sensitivities = [r["sensitivity"] for r in rows]
    assert sensitivities == sorted(sensitivities, reverse=True)


def test_higher_k_never_increases_false_alarms():
    rng = np.random.default_rng(11)
    streams = {f"e{i}": rng.uniform(0, 1, size=5) for i in range(120)}
    labels = {k: int(v.mean() > 0.5) for k, v in streams.items()}
    rows = sweep_policies(streams, labels, [(1, 5), (2, 5), (3, 5), (4, 5)])
    rates = [r["false_alarm_rate"] for r in rows]
    assert rates == sorted(rates, reverse=True)


def test_sweep_reports_wall_clock_false_alarm_rate():
    streams = {"a": np.array([0.9] * 5), "b": np.array([0.0] * 5)}
    labels = {"a": 0, "b": 0}
    row = sweep_policies(streams, labels, [(1, 1)], event_seconds=7.83)[0]
    assert row["false_alarms"] == 1
    # one false alarm in 2 * 7.83 s of negative signal
    assert row["false_alarms_per_hour"] == pytest.approx(3600.0 / (2 * 7.83), rel=1e-6)


def test_sweep_latency_is_measured_from_onset():
    streams = {"a": np.array([0.0, 0.0, 0.9, 0.9, 0.9])}
    labels = {"a": 1}
    onsets = {"a": 2.6}
    plain = sweep_policies(streams, labels, [(1, 1)])[0]
    from_onset = sweep_policies(streams, labels, [(1, 1)], onset_by_event=onsets)[0]
    assert from_onset["mean_latency_s"] == pytest.approx(plain["mean_latency_s"] - 2.6)


def test_earliest_alert_time_grows_one_stride_per_extra_vote():
    assert earliest_alert_time_s(1, 1.3, 2.6) == pytest.approx(2.6)
    assert earliest_alert_time_s(2, 1.3, 2.6) == pytest.approx(3.9)
    assert earliest_alert_time_s(3, 1.3, 2.6) == pytest.approx(5.2)


def test_onset_latency_may_undercut_the_stream_start_bound():
    """Not a contradiction: the two are measured from different origins.

    A 2.6 s window can begin before the dog starts spinning and still contain
    enough of the spin to vote, so latency from onset is legitimately shorter
    than the time from stream start at which the alert could first fire.
    """
    streams = {"a": np.array([0.9, 0.9, 0.9])}
    row = sweep_policies(streams, {"a": 1}, [(2, 3)], onset_by_event={"a": 2.0})[0]
    assert row["mean_latency_s"] < row["earliest_alert_from_stream_start_s"]


def test_sweep_skips_impossible_policies():
    streams = {"a": np.array([0.9] * 3)}
    assert sweep_policies(streams, {"a": 1}, [(5, 2)]) == []
