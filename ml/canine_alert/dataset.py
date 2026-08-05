"""Loading and event curation for the DCU spin-alert dataset.

Dataset: "Package of motion sensor data of spin alert behaviour", figshare
https://doi.org/10.6084/m9.figshare.30022441 (Brady et al., Animals 2025, 15, 3081).

Layout on disk::

    spinning_dataset/<session>/Shimmer_<device>-<recording>-<part>.pkl

Each pickle is a pandas DataFrame with a millisecond ``Timestamp``, the
Shimmer3 low-noise and wide-range accelerometers, gyroscope, magnetometer,
battery voltage, and a ``Spin`` annotation column that is 0 outside an
annotated alert and 200 inside one (200 is a plotting amplitude, not a class
index -- we binarise it on load).

Subject identity
----------------
The published package does **not** carry the dog names used in the paper
(Stuart, Rosie, Teddy, Ranger, Tori, Nadia), so a literal Leave-One-Dog-Out
split cannot be reconstructed from it.  We therefore group by *recording*
(``<session>/<recording>``), which is the finest identifier the release
provides, and run Leave-One-Group-Out.  A recording is a single continuous
capture from one collar on one animal, so this is a strictly *harder* and never
a leakier split than LODO within a recording; it simply cannot guarantee that
two recordings of the same dog land in different folds.  Section 7 of
``docs/07-evaluation.md`` states this deviation explicitly.
"""

from __future__ import annotations

import pickle
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

import numpy as np
import pandas as pd

from .config import (
    DEFAULT_DATASET_DIR,
    IMU_CHANNELS,
    LABEL_COLUMN,
    TIME_COLUMN,
    PipelineConfig,
    DEFAULT_CONFIG,
)

_FILENAME_RE = re.compile(r"Shimmer_(?P<device>\w+)-(?P<recording>\d+)-(?P<part>\d+)\.pkl$")


def _install_numpy2_unpickle_shim() -> None:
    """Allow NumPy>=2 pickles to be read by a NumPy 1.x runtime.

    The published pickles were written with NumPy 2.x, whose array
    reconstructors live in ``numpy._core``.  NumPy 1.x exposes the same
    callables under ``numpy.core``.  Aliasing the module names is enough; no
    array data is reinterpreted.  Under NumPy>=2 this is a no-op.

    NumPy 1.26 ships a stub ``numpy._core`` package that has no ``numeric`` or
    ``multiarray`` submodule, so probing for the parent package alone is not a
    sufficient version test -- we probe for the submodule the pickles name.
    """
    try:  # NumPy >= 2 already provides the real module tree
        import numpy._core.numeric  # noqa: F401, PLC0415
        import numpy._core.multiarray  # noqa: F401, PLC0415

        return
    except ImportError:
        pass

    import numpy.core  # noqa: PLC0415
    import numpy.core.multiarray  # noqa: PLC0415
    import numpy.core.numeric  # noqa: PLC0415

    sys.modules.setdefault("numpy._core", numpy.core)
    sys.modules["numpy._core.multiarray"] = numpy.core.multiarray
    sys.modules["numpy._core.numeric"] = numpy.core.numeric


@dataclass(frozen=True)
class Recording:
    """One pickle file: a continuous IMU capture with a spin annotation."""

    path: Path
    session: str
    device: str
    recording: int
    part: int
    frame: pd.DataFrame

    @property
    def group(self) -> str:
        """Grouping key used as the leave-one-out unit (see module docstring)."""
        return f"{self.session}/{self.recording:03d}"

    @property
    def source_id(self) -> str:
        return f"{self.session}/{self.path.stem}"

    @property
    def fs_hz(self) -> float:
        ts = self.frame[TIME_COLUMN].to_numpy()
        if ts.size < 2:
            return float("nan")
        dt = np.median(np.diff(ts))
        return float(1000.0 / dt) if dt > 0 else float("nan")

    @property
    def labels(self) -> np.ndarray:
        """Binary spin annotation, one entry per sample."""
        return (self.frame[LABEL_COLUMN].to_numpy() > 0).astype(np.int8)

    def channels(self, names: Sequence[str] = IMU_CHANNELS) -> np.ndarray:
        """``(n_samples, n_channels)`` float array of the selected channels."""
        return self.frame.loc[:, list(names)].to_numpy(dtype=np.float64)


@dataclass(frozen=True)
class Event:
    """A behaviourally *pure* slice of a recording.

    Positive events contain one or more complete annotated spins; negative
    events contain no spin sample and are separated from any spin by
    ``negative_guard_seconds``.  All splitting happens at this granularity so
    that no single behavioural occurrence can straddle train and test.
    """

    event_id: str
    group: str
    source_id: str
    label: int
    fs_hz: float
    signals: np.ndarray  # (n_samples, n_channels)
    sample_labels: np.ndarray  # (n_samples,) binary
    start_index: int

    @property
    def n_samples(self) -> int:
        return self.signals.shape[0]

    @property
    def duration_s(self) -> float:
        return self.n_samples / self.fs_hz

    @property
    def onset_s(self) -> float:
        """Time of the first annotated spin sample, in seconds from event start.

        Zero for negative events (they have no onset).  Detection latency is
        measured against this, not against the start of the padded event.
        """
        positive = np.flatnonzero(self.sample_labels)
        return float(positive[0] / self.fs_hz) if positive.size else 0.0


def parse_filename(path: Path) -> tuple[str, int, int]:
    match = _FILENAME_RE.search(path.name)
    if match is None:
        raise ValueError(f"unexpected dataset filename: {path.name}")
    return match["device"], int(match["recording"]), int(match["part"])


def load_recordings(dataset_dir: Path | str = DEFAULT_DATASET_DIR) -> list[Recording]:
    """Load every pickle under ``dataset_dir``, sorted for reproducibility."""
    _install_numpy2_unpickle_shim()
    dataset_dir = Path(dataset_dir)
    paths = sorted(dataset_dir.glob("*/*.pkl"))
    if not paths:
        raise FileNotFoundError(
            f"no .pkl files under {dataset_dir}. Download the figshare package "
            "'Package of motion sensor data of spin alert behaviour' and unpack "
            "it there."
        )

    recordings: list[Recording] = []
    for path in paths:
        device, recording, part = parse_filename(path)
        with path.open("rb") as handle:
            frame = pickle.load(handle)
        if not isinstance(frame, pd.DataFrame):
            raise TypeError(f"{path} did not contain a DataFrame")
        missing = [c for c in (*IMU_CHANNELS, LABEL_COLUMN, TIME_COLUMN) if c not in frame.columns]
        if missing:
            raise ValueError(f"{path} is missing columns {missing}")
        recordings.append(
            Recording(
                path=path,
                session=path.parent.name,
                device=device,
                recording=recording,
                part=part,
                frame=frame.reset_index(drop=True),
            )
        )
    return recordings


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous ``[start, stop)`` spans where ``mask`` is truthy."""
    padded = np.concatenate(([0], mask.astype(np.int8), [0]))
    edges = np.diff(padded)
    starts = np.flatnonzero(edges == 1)
    stops = np.flatnonzero(edges == -1)
    return list(zip(starts.tolist(), stops.tolist()))


def spin_events(recording: Recording) -> list[tuple[int, int]]:
    """Annotated spin spans of a recording, as ``[start, stop)`` sample indices."""
    return _runs(recording.labels)


def curate_events(
    recordings: Sequence[Recording],
    config: PipelineConfig = DEFAULT_CONFIG,
) -> list[Event]:
    """Split recordings into fixed-length, behaviourally pure events.

    Positive events are centred on an annotated spin and padded outwards to
    ``config.event_seconds``; the padding is clipped at the recording edges and
    the event is shifted rather than truncated where possible, so every positive
    event is long enough to yield the full complement of windows.

    Negative events tile the spin-free regions of each recording, keeping a
    ``negative_guard_seconds`` margin from any annotated spin.
    """
    events: list[Event] = []
    for rec in recordings:
        fs = rec.fs_hz
        if not np.isfinite(fs):
            continue
        target = config.event_samples(fs)
        guard = int(round(config.negative_guard_seconds * fs))
        signals = rec.channels()
        labels = rec.labels
        n = labels.size
        if n < target:
            continue

        spins = spin_events(rec)

        # --- positive events -------------------------------------------------
        for k, (start, stop) in enumerate(spins):
            centre = (start + stop) // 2
            begin = centre - target // 2
            begin = max(0, min(begin, n - target))
            end = begin + target
            events.append(
                Event(
                    event_id=f"{rec.source_id}#pos{k}",
                    group=rec.group,
                    source_id=rec.source_id,
                    label=1,
                    fs_hz=fs,
                    signals=signals[begin:end],
                    sample_labels=labels[begin:end],
                    start_index=begin,
                )
            )

        # --- negative events -------------------------------------------------
        blocked = labels.astype(bool).copy()
        for start, stop in spins:
            blocked[max(0, start - guard) : min(n, stop + guard)] = True
        for k, (start, stop) in enumerate(_runs(~blocked)):
            cursor = start
            index = 0
            while cursor + target <= stop:
                events.append(
                    Event(
                        event_id=f"{rec.source_id}#neg{k}_{index}",
                        group=rec.group,
                        source_id=rec.source_id,
                        label=0,
                        fs_hz=fs,
                        signals=signals[cursor : cursor + target],
                        sample_labels=labels[cursor : cursor + target],
                        start_index=cursor,
                    )
                )
                cursor += target
                index += 1
    return events


def dataset_summary(recordings: Sequence[Recording]) -> dict:
    """Descriptive statistics used by the report and the figure scripts."""
    per_recording = []
    durations: list[float] = []
    for rec in recordings:
        fs = rec.fs_hz
        spans = spin_events(rec)
        durations.extend((stop - start) / fs for start, stop in spans)
        per_recording.append(
            {
                "source_id": rec.source_id,
                "session": rec.session,
                "device": rec.device,
                "group": rec.group,
                "n_samples": int(len(rec.frame)),
                "fs_hz": round(fs, 4),
                "n_spin_events": len(spans),
                "spin_seconds": round(sum((s2 - s1) / fs for s1, s2 in spans), 3),
            }
        )

    total_samples = sum(r["n_samples"] for r in per_recording)
    fs_values = [r["fs_hz"] for r in per_recording if np.isfinite(r["fs_hz"])]
    return {
        "n_files": len(per_recording),
        "n_sessions": len({r["session"] for r in per_recording}),
        "n_groups": len({r["group"] for r in per_recording}),
        "n_spin_events": sum(r["n_spin_events"] for r in per_recording),
        "total_samples": total_samples,
        "median_fs_hz": round(float(np.median(fs_values)), 4) if fs_values else float("nan"),
        "total_seconds": round(total_samples / float(np.median(fs_values)), 1) if fs_values else 0.0,
        "spin_seconds": round(float(np.sum(durations)), 1),
        "event_duration_s": {
            "min": round(float(np.min(durations)), 3),
            "max": round(float(np.max(durations)), 3),
            "mean": round(float(np.mean(durations)), 3),
            "median": round(float(np.median(durations)), 3),
        }
        if durations
        else {},
        "per_recording": per_recording,
    }


def iter_groups(events: Sequence[Event]) -> Iterator[str]:
    seen: set[str] = set()
    for event in events:
        if event.group not in seen:
            seen.add(event.group)
            yield event.group
