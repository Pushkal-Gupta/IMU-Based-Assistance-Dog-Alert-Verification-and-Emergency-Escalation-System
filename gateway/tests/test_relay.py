"""Relay wiring that the escalation unit tests cannot see."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from escalation import Channel, Contact, EscalationPolicy, RecordingNotifier  # noqa: E402
from gateway.relay import Relay  # noqa: E402


class SpyBackend:
    reachable = True
    pending = 0

    def __init__(self) -> None:
        self.heartbeats: list[dict] = []
        self.alerts: list[dict] = []

    def report_alert(self, payload):
        self.alerts.append(payload)
        return True

    def report_heartbeat(self, dog_id, relay_id, open_alerts):
        self.heartbeats.append({"dog_id": dog_id, "relay_id": relay_id, "open_alerts": open_alerts})
        return True

    def report_suppressed(self, detection, reason):
        return True

    def flush(self):
        return 0


class Clock:
    now = 100.0

    def __call__(self):
        return self.now


def _relay(backend, clock):
    policy = EscalationPolicy(
        owner=Contact("owner-1", "Alex", Channel.OWNER, "+10000000001"),
        caregivers=(Contact("care-1", "Sam", Channel.CAREGIVER, "+10000000002"),),
        emergency=(Contact("emerg-1", "Monitor", Channel.EMERGENCY, "+10000000003"),),
    )
    return Relay(policy=policy, notifier=RecordingNotifier(), backend=backend, dog_id="stuart",
                 relay_id="relay-9", clock=clock)


def test_heartbeat_carries_the_dog_id_the_watchdog_matches_alerts_on():
    # Regression: heartbeats used to carry the owner's contact id, so the
    # backend watchdog (which pairs heartbeats and alerts by dog_id) never found
    # a heartbeat for any alert and the dead-phone takeover could not fire
    # before its 600 s ceiling.
    backend, clock = SpyBackend(), Clock()
    relay = _relay(backend, clock)
    alert = relay.handle_detection(
        {"dog_id": "stuart", "sequence": 1, "device_uptime_ms": 5, "confidence": 0.8}
    )
    relay.tick()
    assert backend.heartbeats, "relay did not heartbeat"
    assert backend.heartbeats[-1]["dog_id"] == alert.dog_id == "stuart"
    assert backend.heartbeats[-1]["relay_id"] == "relay-9"
    assert backend.alerts[-1]["dog_id"] == backend.heartbeats[-1]["dog_id"]
