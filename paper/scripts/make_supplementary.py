#!/usr/bin/env python3
"""Supplementary materials S1-S3 as CSV, plus the TLA+ spec, from artifacts.

    python paper/scripts/make_supplementary.py   -> paper/supplementary/
"""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "paper" / "supplementary"


def load(rel):
    return json.loads((REPO / rel).read_text())


def write(name, header, rows):
    with (OUT / name).open("w", newline="") as handle:
        w = csv.writer(handle)
        w.writerow(header)
        w.writerows(rows)
    print(f"  {name} ({len(rows)} rows)")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    results = load("ml/artifacts/results.json")
    research = load("ml/artifacts/research.json")
    abl = load("ml/artifacts/ablations.json")
    sim = load("escalation/artifacts/simulation.json")
    tlc = load("formal/results.json")

    # S1: the full single-level gate sweep, and the nested per-fold choices.
    sweep = results["verification_sweep"]["policies"]
    write("TableS1a_gate_sweep_single_level.csv",
          ["model", "vote_threshold", "k", "n", "sensitivity", "specificity", "false_alarm_rate",
           "false_alarms_per_hour", "median_latency_s", "detected", "missed", "false_alarms", "true_negatives"],
          [[results["verification_sweep"]["model"], r["vote_threshold"], r["k"], r["n"], r["sensitivity"],
            r["specificity"], r["false_alarm_rate"], r["false_alarms_per_hour"], r["median_latency_s"],
            r["detected"], r["missed"], r["false_alarms"], r["true_negatives"]] for r in sweep])
    rows = []
    for model, nested in research["nested"].items():
        for fold in nested["per_fold"]:
            p = fold["policy"] or {}
            rows.append([model, fold["group"], p.get("vote_threshold"), p.get("k"), p.get("n"),
                         fold["detected"], fold["missed"], fold["false_alarms"], fold["true_negatives"]])
    write("TableS1b_gate_nested_per_fold.csv",
          ["model", "held_out_group", "vote_threshold", "k", "n", "detected", "missed", "false_alarms",
           "true_negatives"], rows)
    rows = []
    for o in research["continuous_outcomes_deployed"]:
        rows.append([o["source_id"], o["group"], round(o["duration_s"], 2), round(o["exposure_s"], 2),
                     o["n_spins"], o["spins_detected"], o["n_episodes"], o["episodes_detected"],
                     o["false_alarms"], ";".join(f"{a:.2f}" for a in o["alerts_s"])])
    write("TableS1c_continuous_streams_deployed.csv",
          ["recording", "group", "duration_s", "spin_free_exposure_s", "n_spins", "spins_detected",
           "n_episodes", "episodes_detected", "false_alarms", "alert_times_s"], rows)

    # S2: every TLC check, and the simulation outcomes.
    write("TableS2a_tlc_checks.csv",
          ["property", "kind", "spec", "watchdog_mode", "caregiver_configured", "holds", "expected_to_hold",
           "distinct_states", "states_generated", "counterexample_length", "description"],
          [[c["property"], c["kind"], c["spec"], c["watchdog_mode"], c["caregiver_configured"], c["holds"],
            c["expected_to_hold"], c.get("distinct_states"), c.get("states_generated"),
            c.get("counterexample_length"), c["description"]] for c in tlc["checks"]])
    rows = []
    for name, s in sim["scenarios"].items():
        rows.append([name, s["n"], s["p_detected"], s["p_human_within"]["60"], s["p_human_within"]["180"],
                     s["p_human_within"]["300"], s["median_time_to_human_s"], s["p90_time_to_human_s"],
                     s["p_caregiver_paged"], s["p_emergency_paged"], s["p_caregiver_skipped"],
                     s["p_duplicate_emergency"], s["p_page_after_owner_response"], s["p_detected_but_lost"]])
    write("TableS2b_simulation_scenarios.csv",
          ["scenario", "episodes", "p_detected", "p_human_60s", "p_human_180s", "p_human_300s",
           "median_time_to_human_s", "p90_time_to_human_s", "p_caregiver_paged", "p_emergency_paged",
           "p_caregiver_tier_skipped", "p_duplicate_emergency_page", "p_page_after_owner_response",
           "p_detected_but_lost"], rows)
    write("TableS2c_t1_t2_grid.csv",
          ["t1_s", "t2_s", "median_time_to_human_s", "p_human_180s", "p_human_300s",
           "p_false_alarm_reaches_caregiver", "caregiver_pages_per_day_at_measured_rate"],
          [[g["t1_s"], g["t2_s"], g["median_time_to_human_s"], g["p_human_within_180"], g["p_human_within_300"],
            g["burden_at_measured_far"]["p_reaches_caregiver"],
            g["burden_at_measured_far"]["caregiver_pages_per_day"]] for g in sim["t1_t2_grid"]])
    (OUT / "FileS2_simulation_assumptions.json").write_text(
        json.dumps({"assumptions": sim["assumptions"], "detector": sim["detector"],
                    "requirement": sim["requirement"]}, indent=2) + "\n")

    # S3: every robustness and ablation result.
    rows = []
    for bucket, entries in abl["robustness"].items():
        for label, r in entries.items():
            rows.append([bucket, label, r["segment_f1"], r["segment_auc"], r["event_recall"], r["event_specificity"]])
    write("TableS3a_robustness.csv",
          ["training", "perturbation", "segment_f1", "segment_auc", "event_recall", "event_specificity"], rows)
    rows = []
    for section in ("baselines", "feature_families", "n_selected", "window_seconds"):
        for label, r in abl[section].items():
            rows.append([section, label, r["segment_f1"], r["segment_auc"], r["event_recall"],
                         r["event_specificity"], r["event_f1"]])
    write("TableS3b_ablations.csv",
          ["study", "setting", "segment_f1", "segment_auc", "event_recall", "event_specificity", "event_f1"], rows)
    write("TableS3c_embedded_front.csv",
          ["n_trees", "max_depth", "n_nodes", "flash_bytes", "segment_f1", "segment_auc", "event_f1"],
          [[r["n_trees"], r["max_depth"], r["n_nodes"], r["flash_bytes"], r["segment_f1"], r["segment_auc"],
            r["event_f1"]] for r in abl["embedded_front"]])

    shutil.copy(REPO / "formal" / "Escalation.tla", OUT / "FileS1_Escalation.tla")
    print("  FileS1_Escalation.tla")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
