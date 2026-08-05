"""Feature extraction: correctness, invariances and firmware portability."""

from __future__ import annotations

import numpy as np
import pytest

from canine_alert.features import (
    FREQ_FEATURES,
    SIGNAL_NAMES,
    TIME_FEATURES,
    describe_feature,
    derive_signals,
    extract_features,
    extract_single,
    feature_names,
    gyro_magnitude_mean,
    selected_signal_set,
)

FS = 51.2
WIDTH = 133


def _window(rng, n=4):
    return rng.normal(0, 3, size=(n, WIDTH, 6))


def test_names_match_matrix_width(rng):
    features = extract_features(_window(rng), FS)
    assert features.shape[1] == len(feature_names())


def test_expected_feature_count():
    expected = (
        len(SIGNAL_NAMES) * len(TIME_FEATURES)
        + len(SIGNAL_NAMES) * len(FREQ_FEATURES)
        + 15  # pairwise correlations among the six raw channels
    )
    assert len(feature_names()) == expected == 159


def test_names_are_unique():
    names = feature_names()
    assert len(set(names)) == len(names)


def test_derived_magnitudes(rng):
    windows = _window(rng)
    signals = derive_signals(windows)
    assert signals.shape[2] == 8
    np.testing.assert_allclose(
        signals[:, :, 6], np.linalg.norm(windows[:, :, 0:3], axis=2), rtol=1e-12
    )
    np.testing.assert_allclose(
        signals[:, :, 7], np.linalg.norm(windows[:, :, 3:6], axis=2), rtol=1e-12
    )


def test_time_features_against_numpy(rng):
    windows = _window(rng, n=3)
    features = extract_features(windows, FS)
    names = feature_names()

    for axis, signal in enumerate(("ax", "ay", "az", "gx", "gy", "gz")):
        channel = windows[:, :, axis]
        for statistic, expected in (
            ("mean", channel.mean(axis=1)),
            ("std", channel.std(axis=1)),
            ("min", channel.min(axis=1)),
            ("max", channel.max(axis=1)),
            ("range", channel.max(axis=1) - channel.min(axis=1)),
            ("median", np.median(channel, axis=1)),
            ("rms", np.sqrt((channel**2).mean(axis=1))),
            ("energy", (channel**2).mean(axis=1)),
        ):
            column = names.index(f"{signal}_{statistic}")
            np.testing.assert_allclose(
                features[:, column], expected, rtol=1e-10, err_msg=f"{signal}_{statistic}"
            )


def test_constant_window_is_finite_and_zero_variance():
    """A stationary collar must not produce NaN -- skew/kurtosis divide by std."""
    window = np.full((1, WIDTH, 6), 2.5)
    features = extract_features(window, FS)
    assert np.all(np.isfinite(features))
    names = feature_names()
    assert features[0, names.index("ax_std")] == 0.0
    assert features[0, names.index("ax_skew")] == 0.0
    assert features[0, names.index("ax_kurtosis")] == 0.0


def test_dominant_frequency_recovers_a_known_tone():
    t = np.arange(WIDTH) / FS
    window = np.zeros((1, WIDTH, 6))
    window[0, :, 5] = 50 * np.sin(2 * np.pi * 4.0 * t)
    features = extract_features(window, FS)
    dominant = features[0, feature_names().index("gz_dom_freq")]
    # Bin spacing at 133 samples / 51.2 Hz is 0.385 Hz.
    assert dominant == pytest.approx(4.0, abs=0.4)


def test_dc_offset_does_not_change_frequency_features():
    """Gravity and gyro bias are DC; the spectrum must be blind to them."""
    t = np.arange(WIDTH) / FS
    base = np.zeros((1, WIDTH, 6))
    base[0, :, 5] = 40 * np.sin(2 * np.pi * 3.0 * t)
    shifted = base + 1000.0

    names = feature_names()
    columns = [names.index(f"gz_{f}") for f in FREQ_FEATURES]
    np.testing.assert_allclose(
        extract_features(base, FS)[0, columns],
        extract_features(shifted, FS)[0, columns],
        rtol=1e-8,
        atol=1e-8,
    )


def test_magnitude_features_are_rotation_invariant(rng):
    """The collar rotates around the dog's neck; |a| and |g| must not care.

    This is why the feature set carries magnitudes at all -- per-axis features
    shift when the collar is refitted, magnitudes do not.
    """
    windows = _window(rng, n=5)
    theta = 0.7
    rotation = np.array(
        [
            [np.cos(theta), -np.sin(theta), 0.0],
            [np.sin(theta), np.cos(theta), 0.0],
            [0.0, 0.0, 1.0],
        ]
    )
    rotated = windows.copy()
    rotated[:, :, 0:3] = windows[:, :, 0:3] @ rotation.T
    rotated[:, :, 3:6] = windows[:, :, 3:6] @ rotation.T

    names = feature_names()
    magnitude_columns = [
        i for i, n in enumerate(names) if n.startswith(("amag_", "gmag_"))
    ]
    np.testing.assert_allclose(
        extract_features(windows, FS)[:, magnitude_columns],
        extract_features(rotated, FS)[:, magnitude_columns],
        rtol=1e-8,
        atol=1e-8,
    )


def test_correlations_stay_in_range(rng):
    features = extract_features(_window(rng, n=10), FS)
    names = feature_names()
    columns = [i for i, n in enumerate(names) if n.startswith("corr_")]
    values = features[:, columns]
    assert np.all(values >= -1.0 - 1e-9)
    assert np.all(values <= 1.0 + 1e-9)


def test_perfectly_correlated_channels_give_unit_correlation():
    window = np.zeros((1, WIDTH, 6))
    t = np.arange(WIDTH) / FS
    window[0, :, 0] = np.sin(2 * np.pi * 2 * t)
    window[0, :, 1] = 3.0 * window[0, :, 0] + 5.0
    features = extract_features(window, FS)
    assert features[0, feature_names().index("corr_ax_ay")] == pytest.approx(1.0, abs=1e-9)


def test_extract_single_matches_batch(rng):
    windows = _window(rng, n=4)
    batch = extract_features(windows, FS)
    for i in range(windows.shape[0]):
        np.testing.assert_allclose(extract_single(windows[i], FS), batch[i], rtol=1e-12)


def test_windows_are_independent(rng):
    """No feature may depend on neighbouring windows -- the collar sees a stream."""
    windows = _window(rng, n=6)
    batch = extract_features(windows, FS)
    shuffled_order = [3, 0, 5, 1, 4, 2]
    shuffled = extract_features(windows[shuffled_order], FS)
    np.testing.assert_allclose(shuffled, batch[shuffled_order], rtol=1e-12)


def test_gyro_magnitude_statistic(rng):
    windows = _window(rng, n=4)
    expected = np.linalg.norm(windows[:, :, 3:6], axis=2).mean(axis=1)
    np.testing.assert_allclose(gyro_magnitude_mean(windows), expected, rtol=1e-12)


def test_every_name_is_describable():
    for name in feature_names():
        info = describe_feature(name)
        assert info["kind"] in {"time", "frequency", "correlation"}
        for signal in info["signal"].split(","):
            assert signal in SIGNAL_NAMES


def test_selected_signal_set_is_a_subset():
    names = ["gmag_std", "corr_ax_gz", "az_dom_freq"]
    assert selected_signal_set(names) == {"gmag", "ax", "gz", "az"}


def test_rejects_wrong_channel_count(rng):
    with pytest.raises(ValueError, match="expected"):
        extract_features(rng.normal(size=(2, WIDTH, 4)), FS)
