#!/usr/bin/env python3
"""End-to-end replay: real IMU data in, escalation timeline out.

Streams a recording from the published dataset through the whole pipeline --
sliding windows, the trained classifier, the verification gate, the escalation
ladder -- on a simulated clock, and prints what would have happened.

This is the integration test for the system as a *system*.  The unit tests prove
each layer in isolation; this proves they fit together, on real motion data,
with real timings.

Scenarios
---------
``responsive``   the owner acknowledges quickly -- nobody else is disturbed
``asleep``       the owner never responds -- the reason the project exists
``delayed``      the owner responds after the caregiver has already been paged
``false-alarm``  the owner dismisses the alert as a false positive

Usage::

    python gateway/replay.py --scenario asleep
    python gateway/replay.py --recording 2nd_0098/Shimmer_0098-008-1 --scenario delayed
    python gateway/replay.py --scenario asleep --backend http://localhost:8080
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "ml"))

from canine_alert.config import DEFAULT_ARTIFACT_DIR, DEFAULT_CONFIG, DEFAULT_DATASET_DIR
from canine_alert.dataset import load_recordings, spin_events
from canine_alert.features import extract_features
from canine_alert.segmentation import sliding_windows
from canine_alert.verification import VerificationGate

from escalation import (
    AlertState,
    Channel,
    Contact,
    DetectionEvent,
    EscalationEngine,
    EscalationPolicy,
    Location,
    RecordingNotifier,
)
from gateway.backend_client import BackendClient, NullBackendClient

SCENARIOS = ("responsive", "asleep", "delayed", "false-alarm")

#: Seconds after an alert at which the owner reacts, per scenario.  ``None``
#: means they never do.
OWNER_REACTION = {
    "responsive": 8.0,
    "asleep": None,
    "delayed": 95.0,  # after T1 (60 s), so the caregiver has already been paged
    "false-alarm": 5.0,
}


class SimulatedClock:
    """Advances only when the replay advances it."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance_to(self, when: float) -> None:
        if when < self.now:
            raise ValueError("simulated time cannot go backwards")
        self.now = when


@dataclass
class ReplayResult:
    recording: str
    duration_s: float
    annotated_spins: int
    windows: int
    detections: int
    alerts: list
    timeline: list[tuple[float, str]]


def load_model(artifact_dir: Path):
    import joblib

    path = artifact_dir / "model_deployed.joblib"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- run: python ml/scripts/run_experiments.py"
        )
    return joblib.load(path)


def choose_recording(recordings, wanted: str | None):
    if wanted:
        for recording in recordings:
            if recording.source_id == wanted or recording.path.stem == wanted:
                return recording
        raise SystemExit(f"no recording matching {wanted!r}")
    # Default to the longest recording that actually contains a spin, so the
    # replay shows both quiet time and an alert.
    candidates = [r for r in recordings if spin_events(r)]
    return max(candidates, key=lambda r: len(r.frame))


def replay(
    recording,
    bundle,
    scenario: str,
    policy: EscalationPolicy,
    backend,
    vote_threshold: float,
    verify_k: int,
    verify_n: int,
) -> ReplayResult:
    fs = recording.fs_hz
    width = DEFAULT_CONFIG.window_samples(fs)
    stride = DEFAULT_CONFIG.stride_samples(fs)

    signals = recording.channels()
    windows = sliding_windows(signals, width, stride)
    if windows.shape[0] == 0:
        raise SystemExit(f"{recording.source_id} is shorter than one window")

    features = extract_features(windows, fs)
    probabilities = bundle["pipeline"].predict_proba(features)[:, 1]

    clock = SimulatedClock()
    notifier = RecordingNotifier()
    timeline: list[tuple[float, str]] = []

    def note(message: str) -> None:
        timeline.append((clock.now, message))

    engine = EscalationEngine(
        policy=policy,
        notifier=notifier,
        clock=clock,
        on_transition=lambda alert: (
            note(f"alert {alert.alert_id[-6:]} -> {alert.state.value}"),
            backend.report_alert(alert.as_dict()),
        )[0],
    )

    gate = VerificationGate(
        k=verify_k,
        n=verify_n,
        probability_threshold=vote_threshold,
        refractory_seconds=DEFAULT_CONFIG.refractory_seconds,
        stride_seconds=DEFAULT_CONFIG.stride_seconds,
    )

    # The owner's phone has a fix from a few seconds ago -- the ordinary case
    # for a handset in a pocket.
    fix_latitude, fix_longitude = 53.38620, -6.25680
    pending_reaction: list[tuple[float, str]] = []
    sequence = 0
    detections = 0

    for index, probability in enumerate(probabilities):
        # A window is only classifiable once its last sample has arrived.
        window_end_s = (index * stride + width) / fs
        clock.advance_to(window_end_s)

        # Deliver any owner reaction that has come due, and run the timers, both
        # *before* considering a new detection -- otherwise an alert raised in
        # this same instant could be acknowledged before it was raised.
        _drain_reactions(engine, pending_reaction, clock, note)
        engine.tick()

        alert_event = gate.push(float(probability), timestamp_s=window_end_s)
        if alert_event is None:
            continue

        detections += 1
        sequence += 1
        note(
            f"collar: verification gate fired "
            f"({alert_event.votes}/{alert_event.window_count} windows, "
            f"confidence {alert_event.confidence:.2f})"
        )

        detection = DetectionEvent(
            dog_id=recording.session.split("_")[-1].lower() or "dog",
            sequence=sequence,
            device_uptime_ms=int(window_end_s * 1000),
            confidence=float(alert_event.confidence),
            votes=alert_event.votes,
            window_count=alert_event.window_count,
            firmware_version="1.0.0",
        )
        location = Location(fix_latitude, fix_longitude, accuracy_m=9.0, age_seconds=6.0)
        alert = engine.submit(detection, location)
        if alert is None:
            note("relay: detection suppressed below the confidence gate")
            continue

        reaction_delay = OWNER_REACTION[scenario]
        if reaction_delay is not None:
            action = "dismiss" if scenario == "false-alarm" else "ack"
            pending_reaction.append((clock.now + reaction_delay, f"{action}:{alert.alert_id}"))

    # The recording ends, but the escalation ladder does not: keep the clock
    # running long enough for every open alert to reach a terminal state.
    horizon = clock.now + policy.owner_ack_seconds + policy.caregiver_ack_seconds + 10.0
    step = 1.0
    while clock.now < horizon and engine.open_alerts():
        clock.advance_to(min(clock.now + step, horizon))
        _drain_reactions(engine, pending_reaction, clock, note)
        engine.tick()

    # Take notification times from the alert records rather than from the
    # notifier: the notifier has no clock, and stamping them "now" would put
    # every page at the end of the run instead of where it happened.
    for alert in engine.alerts.values():
        for attempt in alert.notifications:
            timeline.append(
                (
                    attempt.at_seconds,
                    f"notified {attempt.channel.value} ({attempt.contact_id}) "
                    f"-- {attempt.status.value.lower()}",
                )
            )

    return ReplayResult(
        recording=recording.source_id,
        duration_s=len(recording.frame) / fs,
        annotated_spins=len(spin_events(recording)),
        windows=int(windows.shape[0]),
        detections=detections,
        alerts=engine.history(),
        timeline=sorted(timeline, key=lambda item: item[0]),
    )


def _drain_reactions(engine, pending, clock, note) -> None:
    remaining = []
    for due_at, action in pending:
        if due_at > clock.now:
            remaining.append((due_at, action))
            continue
        verb, alert_id = action.split(":", 1)
        alert = engine.alerts.get(alert_id)
        if alert is None or alert.state.is_terminal:
            continue
        if verb == "ack":
            note("owner: tapped 'I'm OK'")
            engine.acknowledge(alert_id, Channel.OWNER)
        else:
            note("owner: marked it a false positive")
            engine.dismiss(alert_id)
    pending[:] = remaining


def print_report(result: ReplayResult, scenario: str) -> None:
    print()
    print("=" * 74)
    print(f"  replay: {result.recording}   scenario: {scenario}")
    print("=" * 74)
    print(
        f"  {result.duration_s:.1f} s of motion   "
        f"{result.annotated_spins} annotated spins   "
        f"{result.windows} windows classified   "
        f"{result.detections} verified alerts"
    )
    print()
    print("  timeline (simulated seconds from the start of the recording)")
    print("  " + "-" * 70)
    for at, message in result.timeline:
        print(f"  {at:8.1f}  {message}")

    print()
    print("  outcomes")
    print("  " + "-" * 70)
    if not result.alerts:
        print("  no alert was raised")
    for alert in result.alerts:
        response = alert.owner_response_seconds()
        response_text = f"{response:.1f} s" if response is not None else "no response"
        print(f"  {alert.alert_id}  {alert.state.value}")
        print(f"      confidence {alert.confidence:.2f}   owner response: {response_text}")
        for transition in alert.transitions:
            offset = transition.at_seconds - alert.raised_at_seconds
            print(f"      +{offset:6.1f}s  {transition.to_state.value:26s} {transition.reason}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--recording", default=None, help="e.g. 2nd_0098/Shimmer_0098-008-1")
    parser.add_argument("--scenario", choices=SCENARIOS, default="asleep")
    parser.add_argument("--backend", default=None, help="mirror the timeline to a backend")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args()

    bundle = load_model(args.artifact_dir)

    results_path = args.artifact_dir / "results.json"
    point = {}
    if results_path.exists():
        point = json.loads(results_path.read_text()).get("verification_sweep", {}).get(
            "operating_point"
        ) or {}
    vote_threshold = float(point.get("vote_threshold", DEFAULT_CONFIG.verify_probability_threshold))
    verify_k = int(point.get("k", DEFAULT_CONFIG.verify_k))
    verify_n = int(point.get("n", DEFAULT_CONFIG.verify_n))

    recordings = load_recordings(args.dataset_dir)
    recording = choose_recording(recordings, args.recording)

    policy = EscalationPolicy(
        owner=Contact("owner-1", "Alex", Channel.OWNER, "+353850000001"),
        caregivers=(Contact("care-1", "Sam Okafor", Channel.CAREGIVER, "+353850000002"),),
        emergency=(Contact("emerg-1", "Emergency Services", Channel.EMERGENCY, "112"),),
        owner_name="Alex",
        owner_ack_seconds=60.0,
        caregiver_ack_seconds=120.0,
    )

    backend = BackendClient(base_url=args.backend) if args.backend else NullBackendClient()

    result = replay(
        recording, bundle, args.scenario, policy, backend, vote_threshold, verify_k, verify_n
    )

    if args.json:
        print(
            json.dumps(
                {
                    "recording": result.recording,
                    "scenario": args.scenario,
                    "duration_s": result.duration_s,
                    "annotated_spins": result.annotated_spins,
                    "windows": result.windows,
                    "detections": result.detections,
                    "gate": {"k": verify_k, "n": verify_n, "vote_threshold": vote_threshold},
                    "alerts": [alert.as_dict() for alert in result.alerts],
                },
                indent=2,
            )
        )
    else:
        print(
            f"\ngate: {verify_k}-of-{verify_n} at p>={vote_threshold:.2f} "
            f"(from ml/artifacts/results.json)"
        )
        print_report(result, args.scenario)
        if args.backend:
            print(
                f"  backend {'reachable' if backend.reachable else 'UNREACHABLE'}"
                f"   {backend.pending} events queued\n"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
