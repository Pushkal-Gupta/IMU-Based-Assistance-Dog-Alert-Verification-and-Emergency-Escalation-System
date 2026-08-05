"""Domain types for the escalation layer.

These definitions are the contract shared by the relay app, the backend and the
dashboard.  The Java entities in ``backend/src/main/java/.../domain`` mirror them
field for field; ``docs/06-api.md`` is generated from the same names.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class AlertState(str, Enum):
    """States of one alert episode.

    The terminal states are deliberately distinct rather than a single
    ``CLOSED``: a caregiver reviewing the log needs to see *who* closed each
    alert, because "the owner said they were fine" and "nobody ever answered
    and we called the emergency contact" are the two outcomes the whole system
    exists to tell apart.
    """

    #: Raised by the collar, waiting for the owner.
    PENDING_OWNER = "PENDING_OWNER"
    #: Owner window elapsed; the caregiver has been paged and has not replied.
    PENDING_CAREGIVER = "PENDING_CAREGIVER"
    #: Owner acknowledged in time -- they are conscious and responding.
    ACKNOWLEDGED_BY_OWNER = "ACKNOWLEDGED_BY_OWNER"
    #: Caregiver acknowledged after the owner did not.
    ACKNOWLEDGED_BY_CAREGIVER = "ACKNOWLEDGED_BY_CAREGIVER"
    #: Both windows elapsed; the emergency contact has been notified.
    ESCALATED_EMERGENCY = "ESCALATED_EMERGENCY"
    #: Owner marked it a false positive.  Kept separate from an acknowledgement
    #: so the training-quality statistics are not polluted by dismissals.
    DISMISSED_FALSE_POSITIVE = "DISMISSED_FALSE_POSITIVE"
    #: Cancelled before any human was paged (e.g. the collar retracted it).
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_STATES

    @property
    def is_open(self) -> bool:
        return not self.is_terminal


_TERMINAL_STATES = frozenset(
    {
        AlertState.ACKNOWLEDGED_BY_OWNER,
        AlertState.ACKNOWLEDGED_BY_CAREGIVER,
        AlertState.ESCALATED_EMERGENCY,
        AlertState.DISMISSED_FALSE_POSITIVE,
        AlertState.CANCELLED,
    }
)


class Channel(str, Enum):
    """Who a notification is addressed to."""

    OWNER = "OWNER"
    CAREGIVER = "CAREGIVER"
    EMERGENCY = "EMERGENCY"


class DeliveryStatus(str, Enum):
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class Location:
    """A GPS fix, with the age needed to decide whether it is worth sending.

    An escalation carrying a two-hour-old fix is worse than one carrying none:
    it sends a responder to where the owner used to be.  ``age_seconds`` is
    measured against the alert, not against wall-clock now, so a fix is judged
    by how stale it was *when the alert happened*.
    """

    latitude: float
    longitude: float
    accuracy_m: float
    age_seconds: float

    def __post_init__(self) -> None:
        if not -90.0 <= self.latitude <= 90.0:
            raise ValueError(f"latitude out of range: {self.latitude}")
        if not -180.0 <= self.longitude <= 180.0:
            raise ValueError(f"longitude out of range: {self.longitude}")
        if self.accuracy_m < 0 or self.age_seconds < 0:
            raise ValueError("accuracy and age must be non-negative")

    def is_fresh(self, max_age_seconds: float) -> bool:
        return self.age_seconds <= max_age_seconds

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def map_url(self) -> str:
        return f"https://www.openstreetmap.org/?mlat={self.latitude:.6f}&mlon={self.longitude:.6f}#map=17"


@dataclass(frozen=True)
class Contact:
    """A person the system can page."""

    contact_id: str
    name: str
    channel: Channel
    #: Free-form address: a phone number for SMS, a device token for push.
    address: str

    def redacted_address(self) -> str:
        """Address with all but the last three characters masked.

        Alert logs are shown to vets and trainers, who have no business seeing a
        caregiver's full phone number.
        """
        if len(self.address) <= 3:
            return "*" * len(self.address)
        return "*" * (len(self.address) - 3) + self.address[-3:]


@dataclass(frozen=True)
class DetectionEvent:
    """What the collar sends over BLE once its verification gate fires.

    ``dog_id`` and ``sequence`` together identify the episode.  The relay may
    receive the same packet more than once -- BLE notifications are not
    de-duplicated by the link layer and the collar retransmits when it does not
    see a subscription -- so the engine keys on :meth:`alert_id` and treats
    repeats as no-ops.
    """

    dog_id: str
    sequence: int
    #: Collar uptime in milliseconds when the gate fired.
    device_uptime_ms: int
    confidence: float
    votes: int
    window_count: int
    #: Firmware version, so a log can be attributed to a specific model build.
    firmware_version: str = "unknown"

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.dog_id):
            raise ValueError(f"dog_id must be 1-64 url-safe characters, got {self.dog_id!r}")

    def alert_id(self) -> str:
        """Stable identifier derived from the episode, not from arrival time.

        Two deliveries of the same detection must produce the same id, or a
        retransmission would open a second alert and page the caregiver twice.
        """
        digest = hashlib.sha256(
            f"{self.dog_id}:{self.sequence}:{self.device_uptime_ms}".encode()
        ).hexdigest()
        return f"alert_{digest[:16]}"


@dataclass(frozen=True)
class NotificationAttempt:
    """One delivery attempt, recorded whether it succeeded or not."""

    channel: Channel
    contact_id: str
    attempt: int
    at_seconds: float
    status: DeliveryStatus
    detail: str = ""


@dataclass(frozen=True)
class Transition:
    """An entry in an alert's audit trail."""

    at_seconds: float
    from_state: AlertState | None
    to_state: AlertState
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "at_seconds": self.at_seconds,
            "from_state": self.from_state.value if self.from_state else None,
            "to_state": self.to_state.value,
            "reason": self.reason,
        }


@dataclass
class Alert:
    """An alert episode and its full history."""

    alert_id: str
    dog_id: str
    raised_at_seconds: float
    confidence: float
    state: AlertState = AlertState.PENDING_OWNER
    location: Location | None = None
    detection: DetectionEvent | None = None
    transitions: list[Transition] = field(default_factory=list)
    notifications: list[NotificationAttempt] = field(default_factory=list)
    #: Deadline for the current pending stage, in engine-clock seconds.
    deadline_seconds: float | None = None
    #: Set when the backend escalated because the relay stopped reporting.
    escalated_by_watchdog: bool = False

    def record(self, at_seconds: float, to_state: AlertState, reason: str) -> None:
        self.transitions.append(
            Transition(
                at_seconds=at_seconds,
                from_state=self.state,
                to_state=to_state,
                reason=reason,
            )
        )
        self.state = to_state

    def owner_response_seconds(self) -> float | None:
        """How long the owner took to acknowledge, or ``None`` if they did not.

        This is the number the caregiver dashboard trends over time: a rising
        owner response time is the early signal that the arrangement is
        degrading.
        """
        for transition in self.transitions:
            if transition.to_state == AlertState.ACKNOWLEDGED_BY_OWNER:
                return transition.at_seconds - self.raised_at_seconds
        return None

    def reached_channel(self, channel: Channel) -> bool:
        return any(
            n.channel == channel and n.status is DeliveryStatus.DELIVERED
            for n in self.notifications
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "dog_id": self.dog_id,
            "raised_at_seconds": self.raised_at_seconds,
            "confidence": self.confidence,
            "state": self.state.value,
            "location": self.location.as_dict() if self.location else None,
            "escalated_by_watchdog": self.escalated_by_watchdog,
            "owner_response_seconds": self.owner_response_seconds(),
            "transitions": [t.as_dict() for t in self.transitions],
            "notifications": [
                {
                    "channel": n.channel.value,
                    "contact_id": n.contact_id,
                    "attempt": n.attempt,
                    "at_seconds": n.at_seconds,
                    "status": n.status.value,
                    "detail": n.detail,
                }
                for n in self.notifications
            ],
        }
