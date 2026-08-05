#!/usr/bin/env python3
"""Emit golden test vectors so the C firmware can be checked against Python.

The firmware recomputes the features and the forest on-device.  Nothing
guarantees the C agrees with the Python the model was trained on except a test
that runs both on the same input, which is what these vectors are for.

Windows are sampled from the real dataset -- not synthesised -- because the
failure modes worth catching (near-constant channels, saturated gyro, ties in
argmax) occur in real recordings and not in Gaussian noise.

Format (little-endian, matching the ESP32 and every host we care about)::

    magic     char[8]  "CAVEC001"
    n_windows uint32
    width     uint32
    n_channels uint32
    n_features uint32
    n_selected uint32
    fs_hz     float32
    windows   float32[n_windows][width][n_channels]
    features  float32[n_windows][n_features]      full vector, pre-selection
    scaled    float32[n_windows][n_selected]      after select + standardise
    proba     float32[n_windows]                  sklearn predict_proba[:, 1]

Usage::

    python ml/scripts/make_firmware_vectors.py
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from canine_alert.config import DEFAULT_CONFIG, DEFAULT_DATASET_DIR, REPO_ROOT
from canine_alert.evaluate import prepare
from canine_alert.models import EMBEDDED_MODEL, build_model

MAGIC = b"CAVEC001"
DEFAULT_OUTPUT = REPO_ROOT / "firmware" / "test" / "vectors.bin"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--n-windows",
        type=int,
        default=64,
        help="how many windows to emit; balanced between spin and non-spin",
    )
    args = parser.parse_args()

    print(f"loading dataset from {args.dataset_dir} ...", flush=True)
    data = prepare(args.dataset_dir, DEFAULT_CONFIG)

    pipeline = build_model(EMBEDDED_MODEL, data.feature_names, DEFAULT_CONFIG)
    pipeline.fit(data.features, data.y)

    # Balanced sample: half the vectors exercise the positive class, so a port
    # bug that only shows up on high-energy windows cannot hide.
    rng = np.random.default_rng(DEFAULT_CONFIG.random_state)
    half = args.n_windows // 2
    positives = np.flatnonzero(data.y == 1)
    negatives = np.flatnonzero(data.y == 0)
    chosen = np.concatenate(
        [
            rng.choice(positives, size=min(half, positives.size), replace=False),
            rng.choice(
                negatives, size=min(args.n_windows - half, negatives.size), replace=False
            ),
        ]
    )
    chosen.sort()

    windows = data.segments.windows[chosen].astype(np.float32)
    features = data.features[chosen].astype(np.float32)
    selected = pipeline.named_steps["select"].transform(data.features[chosen])
    scaled = pipeline.named_steps["scale"].transform(selected).astype(np.float32)
    proba = pipeline.named_steps["clf"].predict_proba(scaled.astype(np.float64))[:, 1]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as handle:
        handle.write(MAGIC)
        handle.write(
            struct.pack(
                "<IIIIIf",
                windows.shape[0],
                windows.shape[1],
                windows.shape[2],
                features.shape[1],
                scaled.shape[1],
                float(data.segments.fs_hz),
            )
        )
        handle.write(np.ascontiguousarray(windows, dtype="<f4").tobytes())
        handle.write(np.ascontiguousarray(features, dtype="<f4").tobytes())
        handle.write(np.ascontiguousarray(scaled, dtype="<f4").tobytes())
        handle.write(np.ascontiguousarray(proba, dtype="<f4").tobytes())

    size_kib = args.output.stat().st_size / 1024
    print(
        f"wrote {args.output} ({size_kib:.0f} KiB)\n"
        f"  {windows.shape[0]} windows of {windows.shape[1]}x{windows.shape[2]} "
        f"at {data.segments.fs_hz:.2f} Hz\n"
        f"  {features.shape[1]} features -> {scaled.shape[1]} selected\n"
        f"  {int((proba >= 0.5).sum())} of {proba.size} classified as spin"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
