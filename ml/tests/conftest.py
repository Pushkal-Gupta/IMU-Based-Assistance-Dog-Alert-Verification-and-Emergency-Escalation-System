"""Shared fixtures.

The dataset-backed fixtures are session-scoped because loading and featurising
the whole figshare package takes a few seconds; the synthetic fixtures let the
fast tests run with no dataset present at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ML_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML_ROOT))

from canine_alert.config import DEFAULT_CONFIG, DEFAULT_DATASET_DIR  # noqa: E402


def _dataset_available() -> bool:
    return DEFAULT_DATASET_DIR.exists() and any(DEFAULT_DATASET_DIR.glob("*/*.pkl"))


requires_dataset = pytest.mark.skipif(
    not _dataset_available(),
    reason=f"spin dataset not present under {DEFAULT_DATASET_DIR}",
)


@pytest.fixture(scope="session")
def config():
    return DEFAULT_CONFIG


@pytest.fixture(scope="session")
def recordings():
    if not _dataset_available():
        pytest.skip("dataset not present")
    from canine_alert.dataset import load_recordings

    return load_recordings()


@pytest.fixture(scope="session")
def experiment():
    if not _dataset_available():
        pytest.skip("dataset not present")
    from canine_alert.evaluate import prepare

    return prepare()


@pytest.fixture
def rng():
    return np.random.default_rng(1234)


@pytest.fixture
def synthetic_windows(rng):
    """Windows whose positives carry a strong, obvious rotation signature.

    Positives get a sustained gyro-Z rotation plus centripetal acceleration;
    negatives get band-limited noise at the same amplitude scale.  Any working
    feature/model path must separate these almost perfectly, so a failure here
    means the pipeline is broken rather than the task being hard.
    """
    width, n_each = 133, 60
    t = np.arange(width) / 51.2

    negatives = rng.normal(0.0, 1.0, size=(n_each, width, 6))
    negatives[:, :, 2] += 9.81  # gravity on Z

    positives = rng.normal(0.0, 1.0, size=(n_each, width, 6))
    positives[:, :, 2] += 9.81
    for i in range(n_each):
        rate = 300.0 + rng.normal(0, 20)
        positives[i, :, 5] += rate * np.sin(2 * np.pi * 0.8 * t) + rate
        positives[i, :, 0] += 4.0 * np.cos(2 * np.pi * 0.8 * t)

    windows = np.concatenate([negatives, positives])
    labels = np.concatenate([np.zeros(n_each, dtype=int), np.ones(n_each, dtype=int)])
    groups = np.array([f"g{i % 6}" for i in range(2 * n_each)], dtype=object)
    return windows, labels, groups
