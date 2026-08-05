"""Alert verification and emergency escalation for assistance-dog collars.

The detection layer (``ml/canine_alert``) answers "did the dog perform its
trained alert?".  This package answers the question the source study leaves
open: "and what happens if the owner cannot respond?".

Typical wiring::

    engine = EscalationEngine(policy=policy, notifier=notifier, clock=time.monotonic)
    engine.submit(detection, location)
    ...
    engine.tick()  # driven from the relay's loop
"""

from .engine import EscalationEngine, EscalationPolicy, summarise
from .model import (
    Alert,
    AlertState,
    Channel,
    Contact,
    DeliveryStatus,
    DetectionEvent,
    Location,
    NotificationAttempt,
    Transition,
)
from .notify import (
    ConsoleNotifier,
    FanOutNotifier,
    Notifier,
    RecordingNotifier,
    RetryingNotifier,
    compose_message,
)

__version__ = "1.0.0"

__all__ = [
    "Alert",
    "AlertState",
    "Channel",
    "ConsoleNotifier",
    "Contact",
    "DeliveryStatus",
    "DetectionEvent",
    "EscalationEngine",
    "EscalationPolicy",
    "FanOutNotifier",
    "Location",
    "NotificationAttempt",
    "Notifier",
    "RecordingNotifier",
    "RetryingNotifier",
    "Transition",
    "compose_message",
    "summarise",
]
