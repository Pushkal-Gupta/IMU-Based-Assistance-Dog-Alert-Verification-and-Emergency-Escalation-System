"""Fixtures for the escalation tests.

Everything runs on a manually advanced clock.  A test that needs to know what
happens after three minutes advances three minutes and asserts; it never sleeps.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from escalation import (  # noqa: E402
    Channel,
    Contact,
    DetectionEvent,
    EscalationEngine,
    EscalationPolicy,
    Location,
    RecordingNotifier,
)


class FakeClock:
    """A monotonic clock that only moves when a test moves it."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        if seconds < 0:
            raise ValueError("a monotonic clock cannot go backwards")
        self.now += seconds
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def owner() -> Contact:
    return Contact("owner-1", "Alex Rivera", Channel.OWNER, "+15550100")


@pytest.fixture
def caregiver() -> Contact:
    return Contact("care-1", "Sam Okafor", Channel.CAREGIVER, "+15550111")


@pytest.fixture
def emergency() -> Contact:
    return Contact("emerg-1", "Emergency Services", Channel.EMERGENCY, "112")


@pytest.fixture
def policy(owner, caregiver, emergency) -> EscalationPolicy:
    return EscalationPolicy(
        owner=owner,
        caregivers=(caregiver,),
        emergency=(emergency,),
        owner_name="Alex",
        owner_ack_seconds=60.0,
        caregiver_ack_seconds=120.0,
    )


@pytest.fixture
def notifier() -> RecordingNotifier:
    return RecordingNotifier()


@pytest.fixture
def engine(policy, notifier, clock) -> EscalationEngine:
    return EscalationEngine(policy=policy, notifier=notifier, clock=clock)


@pytest.fixture
def detection() -> DetectionEvent:
    return DetectionEvent(
        dog_id="stuart",
        sequence=1,
        device_uptime_ms=123456,
        confidence=0.82,
        votes=2,
        window_count=4,
        firmware_version="1.0.0",
    )


@pytest.fixture
def fresh_location() -> Location:
    return Location(latitude=53.3862, longitude=-6.2568, accuracy_m=8.0, age_seconds=12.0)
