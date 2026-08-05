"""Feature extraction for 2.6 s IMU windows.

Design constraint
-----------------
Every feature here must be computable on an ESP32 in a few milliseconds from a
133-sample ring buffer, because the same features are recomputed on-device by
``firmware/collar/src/features.cpp``.  That rules out anything needing the whole
recording (no global normalisation, no gravity/body separation -- which the
paper also avoids, since collar orientation is not fixed) and keeps the
frequency-domain part to a single radix-2 FFT per signal.

Feature layout
--------------
Eight *signals* are derived from the six raw channels:

``ax, ay, az, gx, gy, gz`` plus the two rotation-invariant magnitudes
``amag = |a|`` and ``gmag = |g|``.  The magnitudes matter because the collar can
rotate around the dog's neck, so per-axis features are not stable across
mountings while magnitudes are.

Per signal: 13 time-domain and 5 frequency-domain features.  Plus 15 pairwise
Pearson correlations between the six raw channels.  Total 159 features, which
the three-stage selector in ``selection.py`` prunes to 20.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from .config import IMU_CHANNELS

TIME_FEATURES: tuple[str, ...] = (
    "mean",
    "std",
    "min",
    "max",
    "range",
    "median",
    "iqr",
    "rms",
    "mad",
    "skew",
    "kurtosis",
    "mcr",  # mean-crossing rate
    "energy",
)

FREQ_FEATURES: tuple[str, ...] = (
    "dom_freq",
    "spec_energy",
    "spec_entropy",
    "spec_centroid",
    "peak_power",
)

SIGNAL_NAMES: tuple[str, ...] = (
    "ax",
    "ay",
    "az",
    "gx",
    "gy",
    "gz",
    "amag",
    "gmag",
)

_EPS = 1e-12


def _pairs() -> list[tuple[int, int]]:
    return [(i, j) for i in range(len(IMU_CHANNELS)) for j in range(i + 1, len(IMU_CHANNELS))]


def feature_names() -> list[str]:
    """Ordered feature names matching the columns of :func:`extract_features`."""
    names: list[str] = []
    for signal in SIGNAL_NAMES:
        names.extend(f"{signal}_{feature}" for feature in TIME_FEATURES)
    for signal in SIGNAL_NAMES:
        names.extend(f"{signal}_{feature}" for feature in FREQ_FEATURES)
    for i, j in _pairs():
        names.append(f"corr_{SIGNAL_NAMES[i]}_{SIGNAL_NAMES[j]}")
    return names


def derive_signals(windows: np.ndarray) -> np.ndarray:
    """Expand ``(n, w, 6)`` raw channels into ``(n, w, 8)`` derived signals."""
    if windows.ndim != 3 or windows.shape[2] != len(IMU_CHANNELS):
        raise ValueError(f"expected (n, w, {len(IMU_CHANNELS)}) windows, got {windows.shape}")
    accel = windows[:, :, 0:3]
    gyro = windows[:, :, 3:6]
    accel_mag = np.sqrt(np.sum(accel**2, axis=2, keepdims=True))
    gyro_mag = np.sqrt(np.sum(gyro**2, axis=2, keepdims=True))
    return np.concatenate([windows, accel_mag, gyro_mag], axis=2)


def _time_domain(x: np.ndarray) -> np.ndarray:
    """``x`` is ``(n, w, s)``; returns ``(n, s, len(TIME_FEATURES))``."""
    axis = 1
    mean = x.mean(axis=axis)
    std = x.std(axis=axis)
    xmin = x.min(axis=axis)
    xmax = x.max(axis=axis)
    rng = xmax - xmin
    median = np.median(x, axis=axis)
    q75, q25 = np.percentile(x, [75, 25], axis=axis)
    iqr = q75 - q25
    rms = np.sqrt((x**2).mean(axis=axis))
    mad = np.abs(x - mean[:, None, :]).mean(axis=axis)

    centred = x - mean[:, None, :]
    safe_std = np.where(std < _EPS, np.nan, std)
    skew = np.divide((centred**3).mean(axis=axis), safe_std**3)
    kurtosis = np.divide((centred**4).mean(axis=axis), safe_std**4) - 3.0
    skew = np.nan_to_num(skew, nan=0.0, posinf=0.0, neginf=0.0)
    kurtosis = np.nan_to_num(kurtosis, nan=0.0, posinf=0.0, neginf=0.0)

    signs = np.signbit(centred)
    mcr = np.count_nonzero(signs[:, 1:, :] != signs[:, :-1, :], axis=axis) / max(
        x.shape[axis] - 1, 1
    )
    energy = (x**2).sum(axis=axis) / x.shape[axis]

    stacked = np.stack(
        [mean, std, xmin, xmax, rng, median, iqr, rms, mad, skew, kurtosis, mcr, energy],
        axis=-1,
    )
    return stacked


def _frequency_domain(x: np.ndarray, fs_hz: float) -> np.ndarray:
    """``x`` is ``(n, w, s)``; returns ``(n, s, len(FREQ_FEATURES))``."""
    width = x.shape[1]
    centred = x - x.mean(axis=1, keepdims=True)
    spectrum = np.fft.rfft(centred, axis=1)
    power = (np.abs(spectrum) ** 2) / width
    freqs = np.fft.rfftfreq(width, d=1.0 / fs_hz)

    # Drop the DC bin: it is zero after centring and would dominate the
    # normalised distribution used for entropy/centroid.
    power = power[:, 1:, :]
    freqs = freqs[1:]

    total = power.sum(axis=1)
    dominant_index = power.argmax(axis=1)
    dom_freq = freqs[dominant_index]
    peak_power = np.take_along_axis(power, dominant_index[:, None, :], axis=1)[:, 0, :]

    normalised = power / np.maximum(total[:, None, :], _EPS)
    spec_entropy = -(normalised * np.log(normalised + _EPS)).sum(axis=1)
    spec_centroid = (normalised * freqs[None, :, None]).sum(axis=1)

    return np.stack([dom_freq, total, spec_entropy, spec_centroid, peak_power], axis=-1)


def _correlations(windows: np.ndarray) -> np.ndarray:
    """Pairwise Pearson correlation between the six raw channels."""
    centred = windows - windows.mean(axis=1, keepdims=True)
    std = centred.std(axis=1)
    out = np.empty((windows.shape[0], len(_pairs())), dtype=np.float64)
    for column, (i, j) in enumerate(_pairs()):
        denominator = std[:, i] * std[:, j]
        covariance = (centred[:, :, i] * centred[:, :, j]).mean(axis=1)
        out[:, column] = np.where(denominator < _EPS, 0.0, covariance / np.maximum(denominator, _EPS))
    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


def extract_features(windows: np.ndarray, fs_hz: float) -> np.ndarray:
    """Turn ``(n_windows, width, 6)`` raw windows into ``(n_windows, 159)`` features."""
    signals = derive_signals(windows)
    n_windows, _, n_signals = signals.shape

    time_part = _time_domain(signals).reshape(n_windows, n_signals * len(TIME_FEATURES))
    freq_part = _frequency_domain(signals, fs_hz).reshape(n_windows, n_signals * len(FREQ_FEATURES))
    corr_part = _correlations(windows)

    features = np.concatenate([time_part, freq_part, corr_part], axis=1)
    return np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)


def extract_single(window: np.ndarray, fs_hz: float) -> np.ndarray:
    """Convenience wrapper for a single ``(width, 6)`` window."""
    return extract_features(window[None, ...], fs_hz)[0]


def gyro_magnitude_mean(windows: np.ndarray) -> np.ndarray:
    """Mean |gyro| per window -- the statistic behind the heuristic baseline."""
    gyro = windows[:, :, 3:6]
    return np.sqrt(np.sum(gyro**2, axis=2)).mean(axis=1)


def describe_feature(name: str) -> dict[str, str]:
    """Decompose a feature name into signal/kind/statistic, for the docs and the
    firmware code generator."""
    if name.startswith("corr_"):
        _, a, b = name.split("_", 2)
        return {"kind": "correlation", "signal": f"{a},{b}", "statistic": "pearson"}
    signal, statistic = name.split("_", 1)
    kind = "frequency" if statistic in FREQ_FEATURES else "time"
    return {"kind": kind, "signal": signal, "statistic": statistic}


def selected_signal_set(names: Sequence[str]) -> set[str]:
    """Signals a given feature subset actually needs -- lets the firmware skip
    computing magnitudes or FFTs it will never use."""
    needed: set[str] = set()
    for name in names:
        info = describe_feature(name)
        needed.update(info["signal"].split(","))
    return needed
