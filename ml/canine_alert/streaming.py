"""Continuous-stream evaluation: what the collar would do on whole recordings.

The curated-event protocol in ``evaluate.py`` answers "is this 7.8 s clip a
spin?".  A deployed collar is never asked that.  It sees an unbroken stream,
classifies a window every 1.3 s, and has to decide *when* an alert exists --
including the refractory period, which the curated protocol cannot apply
because its negative clips are not contiguous.

This module replays every recording end to end, with a model that never saw the
recording's group, and scores the alerts the gate emits against the annotated
spins using the *any-overlap* convention from the seizure-detection literature:

* an alert is a **true detection** if the window that completed the vote
  overlaps an annotated spin -- i.e. it fires no earlier than the spin's onset
  and no later than one window length after its offset;
* every other alert is a **false alarm**;
* false alarms are normalised by the **spin-free exposure** of the stream: the
  recording length minus the spans in which a true detection was possible.

Spins closer together than the refractory period are merged into one *alert
episode*, because the gate is designed to emit one alert per episode and a
trained dog that is not acknowledged repeats its signal.  Sensitivity is
reported per spin (refractory off) and per episode (refractory on).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

import numpy as np

from .config import DEFAULT_CONFIG, PipelineConfig
from .dataset import Recording, spin_events
from .features import extract_features, gyro_magnitude_mean
from .models import GyroMagnitudeBaseline, predict_scores
from .segmentation import sliding_windows
from .verification import VerificationGate


@dataclass
class Stream:
    """One recording as the collar would see it."""

    source_id: str
    group: str
    session: str
    device: str
    fs_hz: float
    signals: np.ndarray
    labels: np.ndarray

    @property
    def duration_s(self) -> float:
        return self.signals.shape[0] / self.fs_hz

    def spins_s(self) -> list[tuple[float, float]]:
        """Annotated spins as ``(onset, offset)`` in seconds from stream start."""
        padded = np.concatenate(([0], self.labels.astype(np.int8), [0]))
        edges = np.diff(padded)
        starts = np.flatnonzero(edges == 1)
        stops = np.flatnonzero(edges == -1)
        return [(s / self.fs_hz, e / self.fs_hz) for s, e in zip(starts, stops)]


def recording_streams(recordings: Iterable[Recording]) -> list[Stream]:
    return [
        Stream(
            source_id=r.source_id,
            group=r.group,
            session=r.session,
            device=r.device,
            fs_hz=r.fs_hz,
            signals=r.channels(),
            labels=r.labels,
        )
        for r in recordings
        if np.isfinite(r.fs_hz)
    ]


def stream_windows(
    stream: Stream,
    config: PipelineConfig = DEFAULT_CONFIG,
    fs_hz: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Windows tiling the stream, and the time at which each one *ends*.

    The end time is when the collar can first classify the window, so it is the
    time an alert completed by that window is raised.
    """
    fs = stream.fs_hz if fs_hz is None else fs_hz
    width = config.window_samples(fs)
    stride = config.stride_samples(fs)
    windows = sliding_windows(stream.signals, width, stride)
    ends = (np.arange(windows.shape[0]) * stride + width) / fs
    return windows, ends


def score_windows(model, windows: np.ndarray, fs_hz: float) -> np.ndarray:
    """Positive-class probability for raw windows, for any of our models."""
    if windows.shape[0] == 0:
        return np.empty(0)
    if isinstance(model, GyroMagnitudeBaseline):
        return model.predict_proba(gyro_magnitude_mean(windows))[:, 1]
    return predict_scores(model, extract_features(windows, fs_hz))


def score_stream(model, stream: Stream, config: PipelineConfig = DEFAULT_CONFIG) -> tuple[np.ndarray, np.ndarray]:
    windows, ends = stream_windows(stream, config)
    return score_windows(model, windows, stream.fs_hz), ends


# --------------------------------------------------------------------------- #
# gate + scoring
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GatePolicy:
    threshold: float
    k: int
    n: int
    refractory_s: float = DEFAULT_CONFIG.refractory_seconds

    def as_dict(self) -> dict:
        return {"vote_threshold": self.threshold, "k": self.k, "n": self.n, "refractory_s": self.refractory_s}


def alert_times(
    probabilities: np.ndarray,
    window_ends: np.ndarray,
    policy: GatePolicy,
    stride_s: float = DEFAULT_CONFIG.stride_seconds,
) -> list[float]:
    gate = VerificationGate(
        k=policy.k,
        n=policy.n,
        probability_threshold=policy.threshold,
        refractory_seconds=policy.refractory_s,
        stride_seconds=stride_s,
    )
    return [a.timestamp_s for a in gate.run(probabilities, window_ends)]


def merge_episodes(spins: Sequence[tuple[float, float]], gap_s: float) -> list[tuple[float, float, int]]:
    """Merge spins whose gap is below ``gap_s`` into ``(onset, offset, n_spins)``."""
    episodes: list[list[float]] = []
    for onset, offset in sorted(spins):
        if episodes and onset - episodes[-1][1] < gap_s:
            episodes[-1][1] = max(episodes[-1][1], offset)
            episodes[-1][2] += 1
        else:
            episodes.append([onset, offset, 1])
    return [(a, b, int(c)) for a, b, c in episodes]


@dataclass
class StreamOutcome:
    source_id: str
    group: str
    duration_s: float
    exposure_s: float
    n_spins: int
    spins_detected: int
    n_episodes: int
    episodes_detected: int
    false_alarms: int
    latencies_s: list[float] = field(default_factory=list)
    alerts_s: list[float] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "group": self.group,
            "duration_s": self.duration_s,
            "exposure_s": self.exposure_s,
            "n_spins": self.n_spins,
            "spins_detected": self.spins_detected,
            "n_episodes": self.n_episodes,
            "episodes_detected": self.episodes_detected,
            "false_alarms": self.false_alarms,
            "latencies_s": self.latencies_s,
            "alerts_s": self.alerts_s,
        }


def score_alerts(
    stream: Stream,
    alerts: Sequence[float],
    window_s: float = DEFAULT_CONFIG.window_seconds,
    episode_gap_s: float = DEFAULT_CONFIG.refractory_seconds,
    tolerance_after_s: float = 0.0,
) -> StreamOutcome:
    """Any-overlap scoring of ``alerts`` against the stream's annotated spins.

    ``tolerance_after_s`` extends each spin's target span beyond the strict
    any-overlap bound.  An alert a few seconds after a real spin is part of the
    same behavioural episode -- the dog settling, the handler reacting -- and
    in deployment the refractory period would absorb it; whether to call it a
    false alarm is a scoring choice, so the report shows its effect rather
    than picking one value silently.
    """
    spins = stream.spins_s()
    # The span in which an alert can legitimately be caused by each spin.
    targets = [(on, off + window_s + tolerance_after_s) for on, off in spins]

    def matches(t: float, span: tuple[float, float]) -> bool:
        return span[0] <= t <= span[1]

    spin_hit = [any(matches(t, span) for t in alerts) for span in targets]
    false_alarms = sum(1 for t in alerts if not any(matches(t, span) for span in targets))

    episodes = merge_episodes(spins, episode_gap_s)
    detected_episodes = 0
    latencies: list[float] = []
    for onset, offset, _ in episodes:
        span = (onset, offset + window_s + tolerance_after_s)
        hits = [t for t in alerts if matches(t, span)]
        if hits:
            detected_episodes += 1
            latencies.append(min(hits) - onset)

    # Exposure: time in which any alert would be a false alarm.
    covered = 0.0
    for on, off in _union([(max(0.0, a), min(stream.duration_s, b)) for a, b in targets]):
        covered += off - on
    return StreamOutcome(
        source_id=stream.source_id,
        group=stream.group,
        duration_s=stream.duration_s,
        exposure_s=max(0.0, stream.duration_s - covered),
        n_spins=len(spins),
        spins_detected=int(sum(spin_hit)),
        n_episodes=len(episodes),
        episodes_detected=detected_episodes,
        false_alarms=int(false_alarms),
        latencies_s=latencies,
        alerts_s=list(map(float, alerts)),
    )


def _union(spans: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for a, b in sorted(spans):
        if b <= a:
            continue
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def summarise_outcomes(outcomes: Sequence[StreamOutcome]) -> dict:
    """Pooled sensitivity, false-alarm rate and latency over many streams."""
    n_spins = sum(o.n_spins for o in outcomes)
    n_episodes = sum(o.n_episodes for o in outcomes)
    exposure_h = sum(o.exposure_s for o in outcomes) / 3600.0
    false_alarms = sum(o.false_alarms for o in outcomes)
    latencies = [l for o in outcomes for l in o.latencies_s]
    return {
        "n_streams": len(outcomes),
        "hours": sum(o.duration_s for o in outcomes) / 3600.0,
        "exposure_hours": exposure_h,
        "n_spins": n_spins,
        "spins_detected": sum(o.spins_detected for o in outcomes),
        "spin_sensitivity": sum(o.spins_detected for o in outcomes) / n_spins if n_spins else float("nan"),
        "n_episodes": n_episodes,
        "episodes_detected": sum(o.episodes_detected for o in outcomes),
        "episode_sensitivity": (
            sum(o.episodes_detected for o in outcomes) / n_episodes if n_episodes else float("nan")
        ),
        "false_alarms": false_alarms,
        "false_alarms_per_hour": false_alarms / exposure_h if exposure_h else float("nan"),
        "median_latency_s": float(np.median(latencies)) if latencies else float("nan"),
        "mean_latency_s": float(np.mean(latencies)) if latencies else float("nan"),
    }


def evaluate_streams(
    streams: Sequence[Stream],
    probabilities: dict[str, tuple[np.ndarray, np.ndarray]],
    policy_for: Callable[[Stream], GatePolicy],
    config: PipelineConfig = DEFAULT_CONFIG,
    tolerance_after_s: float = 0.0,
) -> list[StreamOutcome]:
    """Run the gate over pre-computed probability streams and score each one."""
    outcomes = []
    for stream in streams:
        probs, ends = probabilities[stream.source_id]
        policy = policy_for(stream)
        alerts = alert_times(probs, ends, policy, config.stride_seconds)
        outcomes.append(
            score_alerts(stream, alerts, config.window_seconds, config.refractory_seconds, tolerance_after_s)
        )
    return outcomes
