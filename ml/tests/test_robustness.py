"""Perturbations used by the sensor-transfer analysis."""

from __future__ import annotations

import numpy as np
import pytest

from canine_alert import robustness as rb
from canine_alert.features import extract_features, feature_names


def _windows(rng, n=4, width=133):
    return rng.normal(size=(n, width, 6)) * np.array([2, 2, 2, 100, 100, 100]) + np.array([0, 0, 9.8, 0, 0, 0])


def test_random_rotations_are_proper_rotations(rng):
    R = rb.random_rotations(50, rng)
    eye = np.einsum("nij,nkj->nik", R, R)
    assert np.allclose(eye, np.eye(3), atol=1e-12)
    assert np.allclose(np.linalg.det(R), 1.0)


def test_rotation_preserves_magnitude_features_exactly(rng):
    W = _windows(rng)
    Wr = rb.rotate(W, rb.random_rotations(W.shape[0], rng))
    names = feature_names()
    mag = [i for i, n in enumerate(names) if n.startswith(("amag_", "gmag_"))]
    a = extract_features(W, 51.2)[:, mag]
    b = extract_features(Wr, 51.2)[:, mag]
    assert np.allclose(a, b, rtol=1e-9, atol=1e-9)


def test_axis_rotation_by_90_degrees_permutes_axes(rng):
    W = _windows(rng, n=1)
    R = rb.axis_rotation(2, np.array([np.pi / 2]))[0]
    Wr = rb.rotate(W, R)
    assert np.allclose(Wr[0, :, 0], -W[0, :, 1]) and np.allclose(Wr[0, :, 1], W[0, :, 0])


def test_sensor_model_clips_to_full_scale_and_quantises(rng):
    W = _windows(rng)
    W[:, :, 3] = 5000.0
    out = rb.apply_sensor(W, rb.SensorModel(noise_scale=0, bias_scale=0, gain_scale=0), rng)
    assert out[:, :, 3].max() <= 2000.0
    lsb = 2000.0 / 2 ** 15
    assert np.allclose(np.round(out[:, :, 4] / lsb), out[:, :, 4] / lsb)


def test_datasheet_noise_has_the_expected_scale(rng):
    W = np.zeros((200, 133, 6))
    out = rb.apply_sensor(W, rb.SensorModel(bias_scale=0, gain_scale=0, quantise=False), rng)
    expected = 0.005 * np.sqrt(25.6)
    assert out[:, :, 3].std() == pytest.approx(expected, rel=0.05)


def test_resample_by_one_is_identity_and_jitter_zero_is_identity(rng):
    W = _windows(rng)
    assert np.allclose(rb.resample(W, 1.0), W)
    assert np.allclose(rb.jitter(W, 0.0, 51.2, rng), W)
