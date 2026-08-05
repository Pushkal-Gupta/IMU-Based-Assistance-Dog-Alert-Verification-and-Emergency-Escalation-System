"""Notification channels.

The engine never talks to a transport directly.  It calls a :class:`Notifier`,
which is a two-method interface, so the same escalation logic runs against SMS,
push, the console, or a test double that records calls.  ``RetryingNotifier``
wraps any notifier with bounded retries so that retry policy is written once
rather than once per transport.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Protocol

from .model import Alert, Channel, Contact, DeliveryStatus

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    """A way of reaching a person."""

    def send(self, contact: Contact, alert: Alert, message: str) -> bool:
        """Deliver ``message``; return True on success.

        Implementations must not raise for ordinary delivery failure -- a
        network error is a ``False``, not an exception.  An exception here is
        treated by the engine as a failed attempt and logged, but it means the
        transport is broken rather than unavailable.
        """
        ...


def compose_message(alert: Alert, channel: Channel, owner_name: str) -> str:
    """Human-readable alert text.

    Written to be legible on a lock screen: what happened, to whom, how
    confident the collar is, how long ago, and where.  The caregiver and
    emergency variants say explicitly that the owner did *not* respond, because
    that -- not the dog's behaviour -- is the reason they are being contacted.
    """
    confidence = f"{alert.confidence * 100:.0f}%"
    if channel is Channel.OWNER:
        head = (
            f"Alert: your assistance dog has signalled a seizure alert "
            f"(confidence {confidence}). Tap to confirm you are OK."
        )
    elif channel is Channel.CAREGIVER:
        head = (
            f"{owner_name}'s assistance dog signalled a seizure alert "
            f"(confidence {confidence}) and {owner_name} did not respond. "
            f"Please check on them."
        )
    else:
        head = (
            f"EMERGENCY: {owner_name}'s seizure-alert dog signalled an alert "
            f"(confidence {confidence}). Neither {owner_name} nor their "
            f"caregiver responded. Medical assistance may be required."
        )

    if alert.location is not None:
        head += (
            f"\nLast known location: {alert.location.latitude:.5f}, "
            f"{alert.location.longitude:.5f} "
            f"(+/-{alert.location.accuracy_m:.0f} m, "
            f"{alert.location.age_seconds:.0f} s old)\n{alert.location.map_url()}"
        )
    else:
        head += "\nNo recent location fix is available."
    return head


@dataclass
class ConsoleNotifier:
    """Prints to a sink.  The default for the demo and for dry runs."""

    sink: Callable[[str], None] = print

    def send(self, contact: Contact, alert: Alert, message: str) -> bool:
        self.sink(
            f"\n--- notify {contact.channel.value} -> {contact.name} "
            f"<{contact.redacted_address()}> [{alert.alert_id}]\n{message}\n"
        )
        return True


@dataclass
class RecordingNotifier:
    """Records every call.  Used by the tests and by the replay harness."""

    delivered: list[tuple[Channel, str, str]] = field(default_factory=list)
    #: Channels that should fail, to exercise the retry and fallback paths.
    failing_channels: set[Channel] = field(default_factory=set)
    #: If set, fail this many times per channel before succeeding.
    fail_first_n: int = 0
    _attempts: dict[Channel, int] = field(default_factory=dict)

    def send(self, contact: Contact, alert: Alert, message: str) -> bool:
        count = self._attempts.get(contact.channel, 0) + 1
        self._attempts[contact.channel] = count
        if contact.channel in self.failing_channels:
            return False
        if count <= self.fail_first_n:
            return False
        self.delivered.append((contact.channel, contact.contact_id, message))
        return True

    def channels(self) -> list[Channel]:
        return [channel for channel, _, _ in self.delivered]


@dataclass
class RetryingNotifier:
    """Bounded retries around any notifier.

    Sleeping is injected rather than imported so that tests -- and the
    simulated-clock replay harness -- do not spend real time in backoff.
    """

    inner: Notifier
    max_attempts: int = 3
    backoff_seconds: float = 5.0
    sleep: Callable[[float], None] = lambda _seconds: None

    def send(self, contact: Contact, alert: Alert, message: str) -> bool:
        for attempt in range(1, self.max_attempts + 1):
            try:
                if self.inner.send(contact, alert, message):
                    return True
            except Exception:  # a broken transport must not abort an escalation
                logger.exception(
                    "notifier raised for %s on attempt %d/%d",
                    contact.channel.value,
                    attempt,
                    self.max_attempts,
                )
            if attempt < self.max_attempts:
                self.sleep(self.backoff_seconds * attempt)
        return False


@dataclass
class FanOutNotifier:
    """Sends through several notifiers, succeeding if any one does.

    An emergency page should go out over SMS *and* push rather than picking one
    and hoping.  Every transport is attempted even after one succeeds, because
    partial delivery is not a reason to skip a redundant path.
    """

    notifiers: list[Notifier]

    def send(self, contact: Contact, alert: Alert, message: str) -> bool:
        succeeded = False
        for notifier in self.notifiers:
            try:
                succeeded = notifier.send(contact, alert, message) or succeeded
            except Exception:
                logger.exception("fan-out notifier failed for %s", contact.channel.value)
        return succeeded
