"""Continuous-stream scoring: any-overlap matching, exposure and episodes."""

from __future__ import annotations

import numpy as np
import pytest

from canine_alert.streaming import (
    GatePolicy,
    Stream,
    alert_times,
    merge_episodes,
    score_alerts,
    summarise_outcomes,
)

FS = 10.0


def _stream(duration_s=100.0, spins=((20.0, 22.0), (60.0, 62.0))):
    n = int(duration_s * FS)
    labels = np.zeros(n, dtype=np.int8)
    for on, off in spins:
        labels[int(on * FS) : int(off * FS)] = 1
    return Stream("s", "g", "sess", "dev", FS, np.zeros((n, 6)), labels)


def test_alert_inside_the_overlap_span_is_a_detection_not_a_false_alarm():
    stream = _stream()
    # spin 20-22 s, window 2.6 s: legitimate span is [20, 24.6]
    out = score_alerts(stream, [24.0], window_s=2.6, episode_gap_s=0.0)
    assert out.spins_detected == 1 and out.false_alarms == 0


def test_alert_before_onset_or_after_the_span_is_a_false_alarm():
    stream = _stream()
    out = score_alerts(stream, [19.5, 25.0], window_s=2.6, episode_gap_s=0.0)
    assert out.spins_detected == 0 and out.false_alarms == 2


def test_tolerance_extends_the_span_and_shrinks_exposure():
    stream = _stream()
    strict = score_alerts(stream, [27.0], window_s=2.6, episode_gap_s=0.0)
    lenient = score_alerts(stream, [27.0], window_s=2.6, episode_gap_s=0.0, tolerance_after_s=5.0)
    assert strict.false_alarms == 1 and lenient.false_alarms == 0
    assert lenient.exposure_s == pytest.approx(strict.exposure_s - 2 * 5.0)


def test_exposure_excludes_each_target_span_once():
    stream = _stream()
    out = score_alerts(stream, [], window_s=2.6, episode_gap_s=0.0)
    assert out.exposure_s == pytest.approx(100.0 - 2 * 4.6)


def test_spins_closer_than_the_gap_merge_into_one_episode():
    assert merge_episodes([(20, 22), (60, 62)], gap_s=60.0) == [(20, 62, 2)]
    assert merge_episodes([(20, 22), (60, 62)], gap_s=10.0) == [(20, 22, 1), (60, 62, 1)]


def test_episode_latency_is_measured_from_the_first_spin_onset():
    stream = _stream()
    out = score_alerts(stream, [21.5, 61.0], window_s=2.6, episode_gap_s=60.0)
    assert out.n_episodes == 1 and out.episodes_detected == 1
    assert out.latencies_s == [pytest.approx(1.5)]


def test_refractory_period_suppresses_repeat_alerts():
    probs = np.ones(20)
    ends = 2.6 + np.arange(20) * 1.3
    assert len(alert_times(probs, ends, GatePolicy(0.5, 1, 1, 0.0))) == 20
    assert len(alert_times(probs, ends, GatePolicy(0.5, 1, 1, 60.0))) == 1


def test_summary_normalises_false_alarms_by_exposure():
    stream = _stream(duration_s=3600.0, spins=())
    out = score_alerts(stream, [100.0, 200.0, 300.0], window_s=2.6, episode_gap_s=60.0)
    s = summarise_outcomes([out])
    assert s["false_alarms_per_hour"] == pytest.approx(3.0)
