#!/usr/bin/env python3
"""Populate a backend with a realistic alert history for the dashboard.

Replays several different recordings through the full pipeline, varying the
owner's behaviour, so the caregiver view shows what it is meant to show: a mix
of alerts the owner answered, alerts that escalated, and false positives they
dismissed.

Replaying the *same* recording under different scenarios would not work -- the
alert id is derived from the episode, so the backend correctly treats the
repeats as one alert and keeps only the latest state.  That idempotence is the
property that stops a BLE retransmission paging a caregiver twice; here it just
means the demo needs different episodes.

Usage::

    python tools/devserver.py --port 8080 &
    python tools/seed_demo.py --backend http://localhost:8080
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "ml"))

from canine_alert.config import DEFAULT_ARTIFACT_DIR, DEFAULT_CONFIG, DEFAULT_DATASET_DIR
from canine_alert.dataset import load_recordings, spin_events

from escalation import Channel, Contact, EscalationPolicy
from gateway.backend_client import BackendClient
from gateway.replay import load_model, replay

# Weighted towards responsive: an assistance dog's owner usually *is* able to
# answer, and a demo that implies otherwise misrepresents the system.
SCENARIO_CYCLE = (
    "responsive",
    "responsive",
    "asleep",
    "responsive",
    "false-alarm",
    "delayed",
    "responsive",
    "asleep",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", default="http://localhost:8080")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--count", type=int, default=8, help="how many recordings to replay")
    args = parser.parse_args()

    bundle = load_model(args.artifact_dir)
    backend = BackendClient(base_url=args.backend)

    recordings = [r for r in load_recordings(args.dataset_dir) if spin_events(r)]
    # Longest first: recordings with more context around the spin produce the
    # most representative timelines.
    recordings.sort(key=lambda r: len(r.frame), reverse=True)
    chosen = recordings[: args.count]

    policy = EscalationPolicy(
        owner=Contact("owner-1", "Alex", Channel.OWNER, "+353850000001"),
        caregivers=(Contact("care-1", "Sam Okafor", Channel.CAREGIVER, "+353850000002"),),
        emergency=(Contact("emerg-1", "Emergency Services", Channel.EMERGENCY, "112"),),
        owner_name="Alex",
        owner_ack_seconds=60.0,
        caregiver_ack_seconds=120.0,
    )

    print(f"seeding {args.backend} from {len(chosen)} recordings\n")
    total_alerts = 0
    for index, recording in enumerate(chosen):
        scenario = SCENARIO_CYCLE[index % len(SCENARIO_CYCLE)]
        result = replay(
            recording,
            bundle,
            scenario,
            policy,
            backend,
            vote_threshold=DEFAULT_CONFIG.verify_probability_threshold,
            verify_k=DEFAULT_CONFIG.verify_k,
            verify_n=DEFAULT_CONFIG.verify_n,
        )
        outcomes = ", ".join(sorted({a.state.value for a in result.alerts})) or "no alert"
        print(
            f"  {recording.source_id:38s} {scenario:12s} "
            f"{result.detections} alert(s)  {outcomes}"
        )
        total_alerts += len(result.alerts)

    backend.flush()
    print(f"\n{total_alerts} alerts written")
    if not backend.reachable:
        print(f"WARNING: backend unreachable, {backend.pending} events still queued")
        return 1
    print(f"open the dashboard at {args.backend}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
