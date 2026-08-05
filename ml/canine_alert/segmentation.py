"""Sliding-window segmentation of curated events.

The window geometry follows the paper: 2.6 s windows with a 1.3 s stride (50%
overlap), a window being labelled 'spin' when at least half of its samples fall
inside an annotated spin.  Windows never cross an event boundary, so the event
remains the atomic unit for train/test splitting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .config import DEFAULT_CONFIG, PipelineConfig
from .dataset import Event


@dataclass
class SegmentSet:
    """Windows extracted from a collection of events.

    Attributes
    ----------
    windows:
        ``(n_windows, window_samples, n_channels)`` raw signal tensor.
    labels:
        ``(n_windows,)`` binary window labels.
    groups:
        ``(n_windows,)`` leave-one-out group key per window.
    event_ids:
        ``(n_windows,)`` originating event id, used for event-level aggregation.
    event_labels:
        ``(n_windows,)`` label of the originating event.
    fs_hz:
        Sampling rate the windows were cut at.
    """

    windows: np.ndarray
    labels: np.ndarray
    groups: np.ndarray
    event_ids: np.ndarray
    event_labels: np.ndarray
    fs_hz: float

    def __len__(self) -> int:
        return int(self.windows.shape[0])

    def subset(self, mask: np.ndarray) -> "SegmentSet":
        return SegmentSet(
            windows=self.windows[mask],
            labels=self.labels[mask],
            groups=self.groups[mask],
            event_ids=self.event_ids[mask],
            event_labels=self.event_labels[mask],
            fs_hz=self.fs_hz,
        )


def segment_events(
    events: Sequence[Event],
    config: PipelineConfig = DEFAULT_CONFIG,
) -> SegmentSet:
    """Cut every event into overlapping fixed-length windows."""
    if not events:
        raise ValueError("no events to segment")

    fs = float(np.median([event.fs_hz for event in events]))
    width = config.window_samples(fs)
    stride = config.stride_samples(fs)
    if width <= 0 or stride <= 0:
        raise ValueError("window and stride must be positive")

    windows: list[np.ndarray] = []
    labels: list[int] = []
    groups: list[str] = []
    event_ids: list[str] = []
    event_labels: list[int] = []

    for event in events:
        n = event.n_samples
        if n < width:
            continue
        for start in range(0, n - width + 1, stride):
            stop = start + width
            chunk_labels = event.sample_labels[start:stop]
            positive = chunk_labels.mean() >= config.positive_window_fraction
            windows.append(event.signals[start:stop])
            labels.append(int(positive))
            groups.append(event.group)
            event_ids.append(event.event_id)
            event_labels.append(event.label)

    if not windows:
        raise ValueError("segmentation produced no windows; check window_seconds vs event_seconds")

    return SegmentSet(
        windows=np.stack(windows).astype(np.float64),
        labels=np.asarray(labels, dtype=np.int8),
        groups=np.asarray(groups, dtype=object),
        event_ids=np.asarray(event_ids, dtype=object),
        event_labels=np.asarray(event_labels, dtype=np.int8),
        fs_hz=fs,
    )


def sliding_windows(
    signals: np.ndarray,
    width: int,
    stride: int,
) -> np.ndarray:
    """Cut a continuous ``(n_samples, n_channels)`` stream into windows.

    Used by the streaming/replay harness, where there are no curated events and
    windows simply tile the whole recording.
    """
    n = signals.shape[0]
    if n < width:
        return np.empty((0, width, signals.shape[1]), dtype=signals.dtype)
    starts = range(0, n - width + 1, stride)
    return np.stack([signals[s : s + width] for s in starts])
