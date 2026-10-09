#!/usr/bin/env python3
"""Run the full detection-layer evaluation and write artifacts.

Outputs (under ``ml/artifacts/`` by default):

``dataset_summary.json``   descriptive statistics of the figshare package
``results.json``           every metric quoted in ``docs/07-evaluation.md``
``model_deployed.joblib``  the deployable (embedded) pipeline, fitted on all data

Usage::

    python ml/scripts/run_experiments.py
    python ml/scripts/run_experiments.py --dataset-dir /path/to/spinning_dataset
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from canine_alert.config import DEFAULT_ARTIFACT_DIR, DEFAULT_CONFIG, DEFAULT_DATASET_DIR
from canine_alert.evaluate import (
    ALL_MODELS,
    aggregate_to_events,
    event_probability_streams,
    prepare,
    run_logo,
    run_within_subject,
)
from canine_alert.models import EMBEDDED_MODEL, build_model
from canine_alert.verification import MAX_FALSE_ALARM_RATE, select_operating_point, sweep_grid



#: The model the firmware ships.  The verification sweep is run against it, not
#: against whichever model happens to win on segment F1, so the reported
#: operating point describes the system that is actually deployed.  (An earlier
#: version tuned the gate on the 200-tree reference forest and then shipped the
#: 32-tree one; the gate policy must be tuned on the model that runs it.)
DEPLOYED_MODEL = EMBEDDED_MODEL


def to_jsonable(value):
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, np.ndarray):
        return to_jsonable(value.tolist())
    if isinstance(value, float) and np.isnan(value):
        return None
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument(
        "--skip-export",
        action="store_true",
        help="do not fit and persist the final deployable model",
    )
    args = parser.parse_args()
    args.artifact_dir.mkdir(parents=True, exist_ok=True)

    started = time.time()
    print(f"[1/6] loading and featurising {args.dataset_dir} ...", flush=True)
    data = prepare(args.dataset_dir, DEFAULT_CONFIG)
    summary = data.summary
    print(
        f"      {summary['n_files']} files, {summary['n_groups']} groups, "
        f"{summary['n_spin_events']} annotated spins, "
        f"{summary['n_events']} curated events "
        f"({summary['n_positive_events']}+/{summary['n_negative_events']}-), "
        f"{summary['n_windows']} windows @ {summary['median_fs_hz']} Hz"
    )
    (args.artifact_dir / "dataset_summary.json").write_text(
        json.dumps(to_jsonable(summary), indent=2) + "\n"
    )

    print("[2/6] within-subject protocol (pooled random window split) ...", flush=True)
    within = run_within_subject(data)
    for name, metrics in within.items():
        print(f"      {name:22s} acc={metrics['accuracy']:.3f} f1={metrics['f1']:.3f}")

    print("[3/6] leave-one-group-out protocol ...", flush=True)
    logo = run_logo(data)
    for name, result in logo.items():
        metrics = result.segment_metrics
        print(
            f"      {name:22s} acc={metrics['accuracy']:.3f} f1={metrics['f1']:.3f} "
            f"auc={metrics['roc_auc']:.3f} ({len(result.per_fold)} folds)"
        )

    print("[4/6] event-level aggregation of out-of-fold predictions ...", flush=True)
    event_level = {
        name: aggregate_to_events(data, result.oof_predictions, result.oof_scores)
        for name, result in logo.items()
    }
    for name, metrics in event_level.items():
        matrix = metrics["confusion_matrix"]
        print(
            f"      {name:22s} acc={metrics['accuracy']:.3f} f1={metrics['f1']:.3f} "
            f"recall={metrics['recall']:.3f} "
            f"(tp={matrix['tp']} fn={matrix['fn']} fp={matrix['fp']} tn={matrix['tn']})"
        )

    print("[5/6] verification-gate sweep (K-of-N x vote threshold) ...", flush=True)
    streams, labels, onsets = event_probability_streams(data, logo[DEPLOYED_MODEL].oof_scores)
    sweep = sweep_grid(streams, labels, onsets, summary["event_seconds"], DEFAULT_CONFIG)

    operating_point = select_operating_point(sweep, MAX_FALSE_ALARM_RATE)
    for row in sweep:
        marker = "  <-- selected" if row is operating_point else ""
        print(
            f"      p>={row['vote_threshold']:.2f} {row['k']}-of-{row['n']}  "
            f"sens={row['sensitivity']:.3f} far={row['false_alarm_rate']:.3f} "
            f"({row['false_alarms_per_hour']:.1f}/h) "
            f"latency={row['mean_latency_s']:.2f}s{marker}"
        )
    if operating_point is None:
        print("      WARNING: no policy met the false-alarm bound")

    results = {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "config": DEFAULT_CONFIG.as_dict(),
        "dataset": {k: v for k, v in summary.items() if k != "per_recording"},
        "within_subject": within,
        "logo": {
            name: {
                "segment_metrics": result.segment_metrics,
                "per_fold": result.per_fold,
                "selection_frequency": result.selection_frequency,
            }
            for name, result in logo.items()
        },
        "event_level": event_level,
        "verification_sweep": {
            "model": DEPLOYED_MODEL,
            "max_false_alarm_rate": MAX_FALSE_ALARM_RATE,
            "policies": sweep,
            "operating_point": operating_point,
        },
        "best_model_by_logo_f1": max(logo, key=lambda n: logo[n].segment_metrics["f1"]),
        "runtime_seconds": round(time.time() - started, 1),
    }

    if not args.skip_export:
        print(f"[6/6] fitting deployable {DEPLOYED_MODEL} on the full dataset ...", flush=True)
        import joblib

        final = build_model(DEPLOYED_MODEL, data.feature_names, DEFAULT_CONFIG)
        final.fit(data.features, data.y)
        joblib.dump(
            {
                "pipeline": final,
                "feature_names": data.feature_names,
                "selected_features": final.named_steps["select"].selected_names(),
                "fs_hz": data.segments.fs_hz,
                "config": DEFAULT_CONFIG.as_dict(),
            },
            args.artifact_dir / "model_deployed.joblib",
        )
        results["deployed_model"] = {
            "name": DEPLOYED_MODEL,
            "selected_features": final.named_steps["select"].selected_names(),
            "selection_stages": final.named_steps["select"].stage_sizes_,
            "n_trees": final.named_steps["clf"].n_estimators,
            "max_depth": final.named_steps["clf"].max_depth,
        }
    else:
        print("[6/6] skipped model export")

    (args.artifact_dir / "results.json").write_text(
        json.dumps(to_jsonable(results), indent=2) + "\n"
    )
    print(f"\nwrote {args.artifact_dir}/results.json in {results['runtime_seconds']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
