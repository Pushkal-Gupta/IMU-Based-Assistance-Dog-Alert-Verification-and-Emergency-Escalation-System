#!/usr/bin/env python3
"""Fit the embedded-size forest on the whole dataset and emit firmware/collar/src/model.h.

The operating point (vote threshold and K-of-N policy) is read from
``ml/artifacts/results.json`` so the firmware ships the configuration the
evaluation actually selected, rather than a hand-copied constant.  Run
``run_experiments.py`` first.

Usage::

    python ml/scripts/export_firmware_model.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from canine_alert.config import DEFAULT_ARTIFACT_DIR, DEFAULT_CONFIG, DEFAULT_DATASET_DIR, REPO_ROOT
from canine_alert.evaluate import prepare
from canine_alert.export import export_summary, generate_header, predict_from_tables, flatten_forest
from canine_alert.models import EMBEDDED_MODEL, build_model

DEFAULT_HEADER = REPO_ROOT / "firmware" / "collar" / "src" / "model.h"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_HEADER)
    args = parser.parse_args()

    results_path = args.artifact_dir / "results.json"
    if results_path.exists():
        results = json.loads(results_path.read_text())
        point = results.get("verification_sweep", {}).get("operating_point") or {}
    else:
        print(f"warning: {results_path} not found, falling back to config defaults", file=sys.stderr)
        point = {}

    verify_k = int(point.get("k", DEFAULT_CONFIG.verify_k))
    verify_n = int(point.get("n", DEFAULT_CONFIG.verify_n))
    vote_threshold = float(point.get("vote_threshold", DEFAULT_CONFIG.verify_probability_threshold))

    print(f"loading dataset from {args.dataset_dir} ...", flush=True)
    data = prepare(args.dataset_dir, DEFAULT_CONFIG)
    fs = data.segments.fs_hz

    print(f"fitting {EMBEDDED_MODEL} on all {len(data.segments)} windows ...", flush=True)
    pipeline = build_model(EMBEDDED_MODEL, data.feature_names, DEFAULT_CONFIG)
    pipeline.fit(data.features, data.y)

    # Verify the flattened tables reproduce scikit-learn before writing them out.
    selected = pipeline.named_steps["select"].transform(data.features)
    scaled = pipeline.named_steps["scale"].transform(selected)
    reference = pipeline.named_steps["clf"].predict_proba(scaled)[:, 1]
    tables = flatten_forest(pipeline.named_steps["clf"])
    transpiled = predict_from_tables(tables, scaled)
    max_error = float(np.max(np.abs(reference - transpiled)))
    print(f"transpiled-vs-sklearn max probability error: {max_error:.3e}")
    if max_error > 1e-6:
        print("ERROR: transpiled forest disagrees with scikit-learn; refusing to write header",
              file=sys.stderr)
        return 1

    header = generate_header(
        pipeline=pipeline,
        model_name=EMBEDDED_MODEL,
        fs_hz=fs,
        verify_k=verify_k,
        verify_n=verify_n,
        vote_threshold=vote_threshold,
        refractory_seconds=DEFAULT_CONFIG.refractory_seconds,
        window_samples=DEFAULT_CONFIG.window_samples(fs),
        stride_samples=DEFAULT_CONFIG.stride_samples(fs),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(header)

    info = export_summary(pipeline)
    print(
        f"wrote {args.output}\n"
        f"  trees={info['n_trees']} nodes={info['n_nodes']} "
        f"tables={info['flash_kib']} KiB\n"
        f"  gate: {verify_k}-of-{verify_n} at p>={vote_threshold:.2f}, "
        f"refractory {DEFAULT_CONFIG.refractory_seconds:.0f}s\n"
        f"  features: {', '.join(info['selected_features'])}"
    )

    (args.artifact_dir / "firmware_export.json").write_text(
        json.dumps(
            {
                "model": EMBEDDED_MODEL,
                "fs_hz": fs,
                "window_samples": DEFAULT_CONFIG.window_samples(fs),
                "stride_samples": DEFAULT_CONFIG.stride_samples(fs),
                "verify_k": verify_k,
                "verify_n": verify_n,
                "vote_threshold": vote_threshold,
                "refractory_seconds": DEFAULT_CONFIG.refractory_seconds,
                "max_transpile_error": max_error,
                **info,
            },
            indent=2,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
