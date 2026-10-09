#!/usr/bin/env python3
"""Run every simulation the paper reports; write escalation/artifacts/simulation.json.

Detector parameters (per-episode sensitivity and latency samples) are read from
``ml/artifacts/research.json`` -- the nested, continuous-stream evaluation of
the deployed model -- so the simulation inherits the measured detector rather
than an assumed one.

    python -m escalation.sim.run_sim            # ~1-2 min
    python -m escalation.sim.run_sim --n 2000   # quick
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from escalation.sim.scenario import (  # noqa: E402
    CAREGIVER,
    OWNER_ASLEEP,
    OWNER_AWAKE,
    SCENARIOS,
    Responder,
)
from escalation.sim.simulate import false_alarm_burden, run_scenario, summarise  # noqa: E402

RESEARCH = REPO / "ml" / "artifacts" / "research.json"
OUT = REPO / "escalation" / "artifacts" / "simulation.json"

T1_GRID = (15.0, 30.0, 45.0, 60.0, 90.0, 120.0)
T2_GRID = (30.0, 60.0, 120.0, 180.0)
#: False-alarm rates for the burden curve: from the measured training-session
#: rate down to the order of clinically validated wearables (~0.1/day).
FA_GRID = tuple(10 ** (k / 4.0) for k in range(-16, 7))


def detector_from_artifacts() -> dict:
    research = json.loads(RESEARCH.read_text())
    deployed = research["deployed_model"]
    stream = research["continuous"][deployed]["nested_refractory_60s"]
    latencies = tuple(x for x in stream["latencies_s"] if x is not None and math.isfinite(x))
    return {
        "model": deployed,
        "p_detect": stream["episode_sensitivity"],
        "latencies_s": latencies,
        "false_alarms_per_hour": stream["false_alarms_per_hour"],
        "false_alarms_per_hour_strict": research["continuous"][deployed]["nested_refractory_0s"][
            "false_alarms_per_hour"
        ],
        "source": "ml/artifacts/research.json: continuous.<deployed>.nested_refractory_60s",
    }


def _clean(summary: dict) -> dict:
    out = dict(summary)
    times = out.pop("time_to_human_s")
    # A CDF on a fixed grid is all the figure needs; keeps the JSON small.
    grid = list(range(0, 601, 5))
    n = out["n"]
    out["cdf_time_to_human"] = {"t_s": grid, "p": [sum(1 for x in times if x <= g) / n for g in grid]}
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=20_000, help="episodes per scenario")
    parser.add_argument("--seed", type=int, default=2025)
    args = parser.parse_args()
    logging.getLogger("escalation").setLevel(logging.CRITICAL)
    started = time.time()

    det = detector_from_artifacts()
    base = dict(p_detect=det["p_detect"], latencies_s=det["latencies_s"])
    print(f"detector: p_detect={det['p_detect']:.3f}, {len(det['latencies_s'])} latency samples")

    # 1. headline scenarios, both watchdog modes where faults are present
    scenarios = {}
    for name, sc in SCENARIOS.items():
        sc = sc.with_(**base)
        modes = ("direct", "ladder") if (sc.p_relay_dies or sc.p_partition) else ("direct",)
        for mode in modes:
            key = name if mode == "direct" else f"{name}__ladder"
            scenarios[key] = _clean(summarise(run_scenario(sc.with_(watchdog_mode=mode), args.n, args.seed)))
            s = scenarios[key]
            print(f"  {key:38s} P(human<=300s)={s['p_human_within']['300']:.3f} "
                  f"median={s['median_time_to_human_s']} skipped={s['p_caregiver_skipped']:.3f}")

    # 2. the dog repeating an unacknowledged alert
    repeats = {}
    for r in (0, 1, 2, 3, 5):
        sc = SCENARIOS["owner_incapacitated"].with_(**base, max_repeats=r)
        s = summarise(run_scenario(sc, args.n // 2, args.seed + r))
        repeats[str(r)] = {k: s[k] for k in ("p_detected", "p_human_within", "median_time_to_human_s")}

    # 3. T1/T2 trade-off: time-to-help when the owner cannot respond, against
    #    caregiver pages per day that false alarms cause when they can.
    grid = []
    for t1 in T1_GRID:
        for t2 in T2_GRID:
            sc = SCENARIOS["owner_incapacitated"].with_(**base, t1_s=t1, t2_s=t2)
            s = summarise(run_scenario(sc, args.n // 4, args.seed))
            grid.append({
                "t1_s": t1,
                "t2_s": t2,
                "median_time_to_human_s": s["median_time_to_human_s"],
                "p_human_within_180": s["p_human_within"]["180"],
                "p_human_within_300": s["p_human_within"]["300"],
                "burden_at_measured_far": false_alarm_burden(det["false_alarms_per_hour"], t1, t2),
                "burden_at_0p01_per_hour": false_alarm_burden(0.01, t1, t2),
            })

    # 4. burden as a function of the false-alarm rate, shipped timings
    burden_curve = [{"false_alarms_per_hour": fa, **false_alarm_burden(fa, 60.0, 120.0)} for fa in FA_GRID]
    p_care = false_alarm_burden(1.0, 60.0, 120.0)["p_reaches_caregiver"]
    p_emerg = false_alarm_burden(1.0, 60.0, 120.0)["emergency_pages_per_day"] / 24.0
    requirement = {
        "caregiver_pages_per_week_target": 1.0,
        "max_far_per_hour_for_target": (1.0 / 7.0) / (24.0 * p_care),
        "emergency_pages_per_month_target": 1.0,
        "max_far_per_hour_for_emergency_target": (1.0 / 30.0) / (24.0 * p_emerg),
    }
    requirement["required_reduction_factor"] = det["false_alarms_per_hour"] / requirement["max_far_per_hour_for_target"]

    # 5. sensitivity of the asleep-owner outcome to the human assumptions
    tornado = []
    asleep = SCENARIOS["owner_asleep"].with_(**base)
    variations = {
        "owner_asleep.p_responds": [("owner", Responder(p, OWNER_ASLEEP.median_s)) for p in (0.3, 0.6, 0.9)],
        "owner_asleep.median_s": [("owner", Responder(OWNER_ASLEEP.p_responds, m)) for m in (20.0, 40.0, 90.0)],
        "caregiver.p_responds": [("caregiver", Responder(p, CAREGIVER.median_s)) for p in (0.5, 0.8, 0.95)],
        "caregiver.median_s": [("caregiver", Responder(CAREGIVER.p_responds, m)) for m in (20.0, 45.0, 120.0)],
        "p_page_lost": [("p_page_lost", v) for v in (0.0, 0.02, 0.10)],
    }
    for label, options in variations.items():
        row = {"parameter": label, "values": []}
        for field_name, value in options:
            sc = asleep.with_(**{field_name: value})
            s = summarise(run_scenario(sc, args.n // 4, args.seed))
            shown = value.p_responds if label.endswith("p_responds") else (
                value.median_s if label.endswith("median_s") else value)
            row["values"].append({
                "value": shown,
                "p_human_within_180": s["p_human_within"]["180"],
                "p_human_within_300": s["p_human_within"]["300"],
            })
        tornado.append(row)

    out = {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_per_scenario": args.n,
        "seed": args.seed,
        "detector": {k: v for k, v in det.items() if k != "latencies_s"},
        "n_latency_samples": len(det["latencies_s"]),
        "assumptions": {
            "owner_awake": vars(OWNER_AWAKE),
            "owner_asleep": vars(OWNER_ASLEEP),
            "caregiver": vars(CAREGIVER),
            "emergency": vars(SCENARIOS["owner_awake"].emergency),
            "p_page_lost": SCENARIOS["owner_awake"].p_page_lost,
            "t1_s": 60.0,
            "t2_s": 120.0,
            "heartbeat_s": 15.0,
            "watchdog_timeout_s": 60.0,
            "hours_awake": 16.0,
            "hours_asleep": 8.0,
        },
        "scenarios": scenarios,
        "dog_repeats": repeats,
        "t1_t2_grid": grid,
        "burden_curve": burden_curve,
        "requirement": requirement,
        "tornado_owner_asleep": tornado,
        "runtime_seconds": round(time.time() - started, 1),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {OUT} in {out['runtime_seconds']} s")
    print(f"  FA/h for <=1 caregiver page/week: {requirement['max_far_per_hour_for_target']:.4f} "
          f"({requirement['required_reduction_factor']:.0f}x below measured)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
