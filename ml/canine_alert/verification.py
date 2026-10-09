"""Multi-stage alert verification gate (our contribution, collar side).

A single 2.6 s window that the classifier calls 'spin' is not an alert.  The
paper itself shows why: at segment level under cross-subject validation the
model produces both false negatives *and* false positives, and it recovers
usable performance only by aggregating predictions over a longer span.  We make
that aggregation an explicit, tunable state machine rather than an offline
post-hoc step, because the escalation layer downstream needs a single
well-defined moment at which an alert exists.

The gate is a K-of-N vote over consecutive windows followed by a refractory
period:

* every ``stride_seconds`` a new window is classified;
* a window votes 'spin' when its positive-class probability is at least
  ``probability_threshold``;
* when ``k`` of the last ``n`` windows voted 'spin', an alert is emitted;
* for ``refractory_seconds`` afterwards no further alert is emitted, so one
  behavioural episode yields exactly one escalation.

This module is the reference implementation.  ``firmware/collar/src/verify.cpp``
is a line-by-line C++ port and ``ml/tests/test_verification.py`` pins the
behaviour of both.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np

from .config import DEFAULT_CONFIG, PipelineConfig


@dataclass(frozen=True)
class Alert:
    """A verified alert emitted by the gate."""

    #: Time of the window that completed the vote, in seconds from stream start.
    timestamp_s: float
    #: Index of that window in the stream.
    window_index: int
    #: Mean probability of the voting windows -- reported to the owner and
    #: caregiver as the alert's confidence.
    confidence: float
    #: Number of positive votes in the deciding buffer.
    votes: int
    #: Size of the deciding buffer.
    window_count: int


@dataclass
class VerificationGate:
    """Streaming K-of-N verification with a refractory period."""

    k: int = DEFAULT_CONFIG.verify_k
    n: int = DEFAULT_CONFIG.verify_n
    probability_threshold: float = DEFAULT_CONFIG.verify_probability_threshold
    refractory_seconds: float = DEFAULT_CONFIG.refractory_seconds
    stride_seconds: float = DEFAULT_CONFIG.stride_seconds

    _votes: deque = field(default_factory=deque, init=False, repr=False)
    _probabilities: deque = field(default_factory=deque, init=False, repr=False)
    _index: int = field(default=-1, init=False, repr=False)
    _last_alert_s: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not 1 <= self.k <= self.n:
            raise ValueError(f"require 1 <= k <= n, got k={self.k}, n={self.n}")
        self._votes = deque(maxlen=self.n)
        self._probabilities = deque(maxlen=self.n)

    def reset(self) -> None:
        self._votes.clear()
        self._probabilities.clear()
        self._index = -1
        self._last_alert_s = None

    def push(self, probability: float, timestamp_s: float | None = None) -> Alert | None:
        """Feed one window's probability; return an Alert if the vote completes.

        ``timestamp_s`` defaults to ``window_index * stride_seconds``, which is
        the correct stream time for uniformly strided windows.
        """
        self._index += 1
        now = self._index * self.stride_seconds if timestamp_s is None else float(timestamp_s)

        self._votes.append(1 if probability >= self.probability_threshold else 0)
        self._probabilities.append(float(probability))

        if sum(self._votes) < self.k:
            return None
        if self._last_alert_s is not None and now - self._last_alert_s < self.refractory_seconds:
            return None

        voting = [p for p, v in zip(self._probabilities, self._votes) if v]
        alert = Alert(
            timestamp_s=now,
            window_index=self._index,
            confidence=float(np.mean(voting)) if voting else 0.0,
            votes=int(sum(self._votes)),
            window_count=len(self._votes),
        )
        self._last_alert_s = now
        # Clear the buffer so the next alert needs a fresh k votes rather than
        # re-firing off the same evidence the moment the refractory window ends.
        self._votes.clear()
        self._probabilities.clear()
        return alert

    def run(
        self,
        probabilities: Iterable[float],
        timestamps_s: Sequence[float] | None = None,
    ) -> list[Alert]:
        """Convenience: replay a whole probability stream, collecting alerts."""
        self.reset()
        alerts: list[Alert] = []
        probabilities = list(probabilities)
        for i, probability in enumerate(probabilities):
            stamp = None if timestamps_s is None else timestamps_s[i]
            alert = self.push(probability, stamp)
            if alert is not None:
                alerts.append(alert)
        return alerts


def earliest_alert_time_s(
    k: int,
    stride_seconds: float = DEFAULT_CONFIG.stride_seconds,
    window_seconds: float = DEFAULT_CONFIG.window_seconds,
) -> float:
    """Earliest an alert can fire, measured from the start of the window stream.

    The first window can only be classified once it is full
    (``window_seconds``), and each further vote costs one stride.

    This is *not* a lower bound on the latency reported by
    :func:`sweep_policies`, which measures from the spin's onset.  A window
    spans 2.6 s and the spin lasts about 2.5 s, so a window can begin before
    the dog starts spinning and still contain enough of it to vote -- making
    onset-relative latency legitimately shorter than this figure.  The two
    answer different questions: this one is "how much signal must the collar
    see", the other is "how long does the handler wait".
    """
    return window_seconds + (k - 1) * stride_seconds


def sweep_policies(
    probabilities_by_event: dict[str, np.ndarray],
    event_labels: dict[str, int],
    policies: Sequence[tuple[int, int]],
    config: PipelineConfig = DEFAULT_CONFIG,
    probability_threshold: float | None = None,
    onset_by_event: dict[str, float] | None = None,
    event_seconds: float | None = None,
) -> list[dict]:
    """Evaluate K-of-N policies over per-event probability streams.

    Returns one record per policy with event-level sensitivity, the false-alarm
    rate on negative events, and the detection latency.  Used by
    ``scripts/run_experiments.py`` to produce the operating-point table in
    ``docs/07-evaluation.md``.

    ``onset_by_event`` gives the time of the first annotated spin sample within
    each positive event, in seconds from the event's start.  Latency is measured
    from that onset to the end of the window that completes the vote -- i.e. the
    delay a handler would actually experience between the dog beginning to spin
    and the collar raising an alert.  Without it, latency is measured from the
    event's start, which understates nothing but means something different.
    """
    threshold = (
        config.verify_probability_threshold if probability_threshold is None else probability_threshold
    )
    if event_seconds is None:
        # Fall back to the nominal geometry when the caller does not pass the
        # measured event length.
        event_seconds = config.window_seconds + (config.event_windows - 1) * config.stride_seconds
    results: list[dict] = []
    for k, n in policies:
        if k > n:
            continue
        detected = missed = false_alarms = true_negatives = 0
        latencies: list[float] = []
        for event_id, stream in probabilities_by_event.items():
            gate = VerificationGate(
                k=k,
                n=n,
                probability_threshold=threshold,
                # One event is one episode: no refractory suppression inside it.
                refractory_seconds=0.0,
                stride_seconds=config.stride_seconds,
            )
            alerts = gate.run(stream)
            positive = bool(event_labels[event_id])
            if positive:
                if alerts:
                    detected += 1
                    fired_at = (
                        config.window_seconds + alerts[0].window_index * config.stride_seconds
                    )
                    onset = 0.0 if onset_by_event is None else onset_by_event.get(event_id, 0.0)
                    latencies.append(fired_at - onset)
                else:
                    missed += 1
            else:
                if alerts:
                    false_alarms += 1
                else:
                    true_negatives += 1

        n_positive = detected + missed
        n_negative = false_alarms + true_negatives
        false_alarm_rate = false_alarms / n_negative if n_negative else float("nan")
        # Negative events tile a fixed span of spin-free signal, so the
        # per-event rate converts directly to a wall-clock rate.  Reported
        # because "4% of events" and "one every 3 minutes" are the same number
        # and only the second one tells you whether the device is wearable.
        negative_hours = (n_negative * event_seconds) / 3600.0 if n_negative else float("nan")
        results.append(
            {
                "k": k,
                "n": n,
                "sensitivity": detected / n_positive if n_positive else float("nan"),
                "specificity": true_negatives / n_negative if n_negative else float("nan"),
                "false_alarm_rate": false_alarm_rate,
                "false_alarms_per_hour": (
                    false_alarms / negative_hours if negative_hours and negative_hours > 0 else float("nan")
                ),
                "negative_hours_evaluated": round(negative_hours, 4) if n_negative else float("nan"),
                "detected": detected,
                "missed": missed,
                "false_alarms": false_alarms,
                "true_negatives": true_negatives,
                "mean_latency_s": float(np.mean(latencies)) if latencies else float("nan"),
                "median_latency_s": float(np.median(latencies)) if latencies else float("nan"),
                "earliest_alert_from_stream_start_s": earliest_alert_time_s(
                    k, config.stride_seconds, config.window_seconds
                ),
            }
        )
    return results


#: The collar is a safety device: a missed alert costs far more than a spurious
#: one, which only costs the owner a dismissal tap.  The operating point is
#: therefore the one that maximises sensitivity subject to an upper bound on the
#: per-event false-alarm rate, not the one that maximises a symmetric score.
MAX_FALSE_ALARM_RATE = 0.05


def select_operating_point(rows: Sequence[dict], max_false_alarm_rate: float = MAX_FALSE_ALARM_RATE) -> dict | None:
    """Pick the policy the collar ships from a sweep.

    Maximise sensitivity subject to ``false_alarm_rate <= max_false_alarm_rate``;
    tie-break towards fewer false alarms, then towards lower latency.  Shared by
    the single-level sweep in ``run_experiments.py`` and by the nested
    cross-validation, so both apply exactly the same rule.
    """
    feasible = [
        row
        for row in rows
        if row["false_alarm_rate"] <= max_false_alarm_rate and row["sensitivity"] > 0
    ]
    if not feasible:
        return None
    return min(
        feasible,
        key=lambda r: (
            -r["sensitivity"],
            r["false_alarm_rate"],
            r["mean_latency_s"] if np.isfinite(r["mean_latency_s"]) else np.inf,
        ),
    )


#: The policy grid every sweep in the report searches.
SWEEP_POLICIES: tuple[tuple[int, int], ...] = (
    (1, 1), (1, 2), (1, 3), (2, 2), (2, 3), (2, 4), (3, 3), (3, 4), (3, 5),
)
SWEEP_THRESHOLDS: tuple[float, ...] = (0.25, 0.30, 0.35, 0.40, 0.45, 0.50)


def sweep_grid(
    probabilities_by_event: dict[str, np.ndarray],
    event_labels: dict[str, int],
    onset_by_event: dict[str, float] | None,
    event_seconds: float | None,
    config: PipelineConfig = DEFAULT_CONFIG,
    policies: Sequence[tuple[int, int]] = SWEEP_POLICIES,
    thresholds: Sequence[float] = SWEEP_THRESHOLDS,
) -> list[dict]:
    """:func:`sweep_policies` over every vote threshold in ``thresholds``."""
    rows: list[dict] = []
    for threshold in thresholds:
        for row in sweep_policies(
            probabilities_by_event,
            event_labels,
            policies,
            config,
            probability_threshold=threshold,
            onset_by_event=onset_by_event,
            event_seconds=event_seconds,
        ):
            rows.append({"vote_threshold": threshold, **row})
    return rows
