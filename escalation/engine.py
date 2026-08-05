"""The escalation state machine.

This is the part the source paper does not address.  Brady et al. establish that
a collar can detect a trained spin alert; they stop there.  But an alert dog's
signal only helps if a human notices it, and the scenario the dog is trained
for -- the owner is about to have a seizure -- is precisely the scenario in which
the owner may be unable to notice anything.  This module is the answer to
"and then what?".

    detection --> PENDING_OWNER --(T1 elapses)--> PENDING_CAREGIVER
                       |                                 |
                  owner acks                     (T2 elapses)
                       v                                 v
             ACKNOWLEDGED_BY_OWNER              ESCALATED_EMERGENCY

Design commitments
------------------
*The clock is injected.*  Every deadline is evaluated against a monotonic clock
passed in at construction, never against ``time.time()``.  This makes the whole
escalation path testable in microseconds, and it means a device whose wall clock
jumps (NTP sync, timezone change, user edit) cannot skip or extend an
escalation window.

*Time only moves when someone tells it to.*  ``tick()`` is explicit.  The engine
has no background thread and takes no locks of its own; the relay app and the
backend each drive it from their own loop.  A state machine that fires timers
from a thread you do not control is a state machine you cannot reason about
during an incident review.

*Notification is at-most-once per stage.*  A stage that has already been
notified is never notified again, even if ``tick()`` is called repeatedly, the
process restarts, or the same detection packet arrives twice.  Paging a
caregiver twice teaches them to ignore the page.

*Failure escalates, it does not stall.*  If the caregiver cannot be reached at
all, the alert does not sit in ``PENDING_CAREGIVER`` forever waiting for an
acknowledgement that can never come -- the T2 deadline still runs and the
emergency contact is still paged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from .model import (
    Alert,
    AlertState,
    Channel,
    Contact,
    DeliveryStatus,
    DetectionEvent,
    Location,
    NotificationAttempt,
)
from .notify import Notifier, compose_message

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EscalationPolicy:
    """Timing and addressing for one owner.

    Defaults come from ``docs/04-escalation-protocol.md``.  ``owner_ack_seconds``
    is the safety-critical one: too short and the owner is paged while they are
    simply in another room; too long and a genuine emergency waits.  60 s is the
    starting point, and it is per-owner configurable because the right value
    depends on the person's seizure profile and living arrangement.
    """

    owner: Contact
    caregivers: tuple[Contact, ...] = ()
    emergency: tuple[Contact, ...] = ()
    owner_name: str = "the owner"
    owner_ack_seconds: float = 60.0
    caregiver_ack_seconds: float = 120.0
    max_location_age_seconds: float = 300.0
    #: Minimum collar confidence that may open an alert at all.  Detections
    #: below this are logged for the training record but never page anyone.
    min_confidence: float = 0.0

    def __post_init__(self) -> None:
        if self.owner_ack_seconds <= 0 or self.caregiver_ack_seconds <= 0:
            raise ValueError("acknowledgement windows must be positive")
        if self.owner.channel is not Channel.OWNER:
            raise ValueError("policy.owner must be an OWNER contact")
        for contact in self.caregivers:
            if contact.channel is not Channel.CAREGIVER:
                raise ValueError(f"{contact.contact_id} is not a CAREGIVER contact")
        for contact in self.emergency:
            if contact.channel is not Channel.EMERGENCY:
                raise ValueError(f"{contact.contact_id} is not an EMERGENCY contact")


@dataclass
class EscalationEngine:
    """Drives alerts through the escalation ladder.

    Not thread-safe by design: give each owner's alert stream one engine and one
    driving loop.
    """

    policy: EscalationPolicy
    notifier: Notifier
    clock: Callable[[], float]
    #: Called after every state change, for persistence and for the dashboard.
    on_transition: Callable[[Alert], None] | None = None
    #: Detections below ``policy.min_confidence`` land here instead of paging.
    on_suppressed: Callable[[DetectionEvent, str], None] | None = None

    alerts: dict[str, Alert] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # ingestion
    # ------------------------------------------------------------------ #
    def submit(
        self,
        detection: DetectionEvent,
        location: Location | None = None,
    ) -> Alert | None:
        """Accept a verified detection from the collar.

        Returns the alert, or ``None`` when the detection was suppressed.
        Re-submitting an identical detection returns the existing alert and
        changes nothing -- see :meth:`DetectionEvent.alert_id`.
        """
        alert_id = detection.alert_id()
        existing = self.alerts.get(alert_id)
        if existing is not None:
            logger.info("duplicate detection %s ignored", alert_id)
            return existing

        if detection.confidence < self.policy.min_confidence:
            reason = (
                f"confidence {detection.confidence:.2f} below "
                f"threshold {self.policy.min_confidence:.2f}"
            )
            logger.info("suppressed detection for %s: %s", detection.dog_id, reason)
            if self.on_suppressed is not None:
                self.on_suppressed(detection, reason)
            return None

        now = self.clock()
        alert = Alert(
            alert_id=alert_id,
            dog_id=detection.dog_id,
            raised_at_seconds=now,
            confidence=detection.confidence,
            state=AlertState.PENDING_OWNER,
            location=self._usable_location(location),
            detection=detection,
            deadline_seconds=now + self.policy.owner_ack_seconds,
        )
        alert.transitions.append(
            _initial_transition(now, AlertState.PENDING_OWNER, "collar verification gate fired")
        )
        self.alerts[alert_id] = alert

        self._notify(alert, Channel.OWNER, (self.policy.owner,))
        self._emit(alert)
        return alert

    def _usable_location(self, location: Location | None) -> Location | None:
        """Drop a fix too old to be worth acting on.

        Sending a responder to a stale position is worse than sending them no
        position at all, because a coordinate reads as authoritative.
        """
        if location is None:
            return None
        if not location.is_fresh(self.policy.max_location_age_seconds):
            logger.warning(
                "discarding location fix aged %.0fs (limit %.0fs)",
                location.age_seconds,
                self.policy.max_location_age_seconds,
            )
            return None
        return location

    # ------------------------------------------------------------------ #
    # human responses
    # ------------------------------------------------------------------ #
    def acknowledge(self, alert_id: str, by: Channel) -> Alert:
        """Record that a human responded.

        An acknowledgement that arrives after the stage has already advanced is
        still recorded -- it just does not undo the escalation.  A caregiver who
        has already been paged should not be told "never mind" by a late tap,
        and the audit trail must show that the owner did eventually reply.
        """
        alert = self._require(alert_id)
        now = self.clock()

        if alert.state.is_terminal:
            logger.info("late %s acknowledgement for closed alert %s", by.value, alert_id)
            alert.transitions.append(
                _initial_transition(
                    now, alert.state, f"late {by.value.lower()} acknowledgement, alert already closed"
                )
            )
            self._emit(alert)
            return alert

        if by is Channel.OWNER:
            alert.record(now, AlertState.ACKNOWLEDGED_BY_OWNER, "owner acknowledged")
        elif by is Channel.CAREGIVER:
            if alert.state is AlertState.PENDING_OWNER:
                # The caregiver got there first -- unusual but not an error, and
                # it still means a human is with the owner.
                alert.record(
                    now,
                    AlertState.ACKNOWLEDGED_BY_CAREGIVER,
                    "caregiver acknowledged before the owner window elapsed",
                )
            else:
                alert.record(now, AlertState.ACKNOWLEDGED_BY_CAREGIVER, "caregiver acknowledged")
        else:
            raise ValueError(f"{by.value} contacts cannot acknowledge an alert")

        alert.deadline_seconds = None
        self._emit(alert)
        return alert

    def dismiss(self, alert_id: str, reason: str = "owner marked false positive") -> Alert:
        """Owner says the dog did not really alert.

        Distinct from an acknowledgement: a dismissal is training-quality data
        (the collar or the dog got it wrong), while an acknowledgement means the
        alert was real and handled.  Conflating them would make the caregiver's
        false-positive trend meaningless.
        """
        alert = self._require(alert_id)
        now = self.clock()
        if alert.state.is_terminal:
            return alert
        alert.record(now, AlertState.DISMISSED_FALSE_POSITIVE, reason)
        alert.deadline_seconds = None
        self._emit(alert)
        return alert

    def cancel(self, alert_id: str, reason: str) -> Alert:
        """Withdraw an alert before any human acted on it.

        Only legal while nobody beyond the owner has been paged: once a
        caregiver's phone has rung, the episode is part of their day and the log
        has to say so.
        """
        alert = self._require(alert_id)
        now = self.clock()
        if alert.state.is_terminal:
            return alert
        if alert.reached_channel(Channel.CAREGIVER) or alert.reached_channel(Channel.EMERGENCY):
            raise ValueError(
                f"cannot cancel {alert_id}: a caregiver or emergency contact has already been paged"
            )
        alert.record(now, AlertState.CANCELLED, reason)
        alert.deadline_seconds = None
        self._emit(alert)
        return alert

    # ------------------------------------------------------------------ #
    # the clock
    # ------------------------------------------------------------------ #
    def tick(self) -> list[Alert]:
        """Advance every open alert whose deadline has passed.

        Returns the alerts that changed state.  Calling this more often than
        necessary is free and calling it late only delays an escalation by the
        call interval -- so the relay drives it at 1 Hz and the backend at 5 s,
        and neither needs to be precise.
        """
        now = self.clock()
        changed: list[Alert] = []
        for alert in list(self.alerts.values()):
            if alert.state.is_terminal or alert.deadline_seconds is None:
                continue
            if now < alert.deadline_seconds:
                continue

            if alert.state is AlertState.PENDING_OWNER:
                self._escalate_to_caregiver(alert, now)
                changed.append(alert)
            elif alert.state is AlertState.PENDING_CAREGIVER:
                self._escalate_to_emergency(alert, now)
                changed.append(alert)
        return changed

    def _escalate_to_caregiver(self, alert: Alert, now: float) -> None:
        elapsed = now - alert.raised_at_seconds
        if not self.policy.caregivers:
            # No caregiver configured: do not park the alert in a state nobody
            # can leave -- go straight to the emergency contact.
            logger.warning("no caregiver configured; escalating %s directly", alert.alert_id)
            self._escalate_to_emergency(alert, now, direct=True)
            return

        alert.record(
            now,
            AlertState.PENDING_CAREGIVER,
            f"owner did not respond within {elapsed:.0f}s; caregiver notified",
        )
        alert.deadline_seconds = now + self.policy.caregiver_ack_seconds
        self._notify(alert, Channel.CAREGIVER, self.policy.caregivers)
        self._emit(alert)

    def _escalate_to_emergency(self, alert: Alert, now: float, direct: bool = False) -> None:
        if not self.policy.emergency:
            # Nothing further to escalate to.  Close the alert honestly rather
            # than leaving it open forever pretending help is on the way.
            logger.error("no emergency contact configured for %s", alert.alert_id)
            alert.record(
                now,
                AlertState.ESCALATED_EMERGENCY,
                "escalation exhausted: no emergency contact is configured",
            )
            alert.deadline_seconds = None
            self._emit(alert)
            return

        reason = (
            "no caregiver configured; escalated directly to emergency contact"
            if direct
            else f"caregiver did not respond within {self.policy.caregiver_ack_seconds:.0f}s"
        )
        alert.record(now, AlertState.ESCALATED_EMERGENCY, reason)
        alert.deadline_seconds = None
        self._notify(alert, Channel.EMERGENCY, self.policy.emergency)
        self._emit(alert)

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _notify(self, alert: Alert, channel: Channel, contacts: Sequence[Contact]) -> None:
        """Page every contact on a channel, at most once per alert per channel."""
        if any(n.channel == channel for n in alert.notifications):
            logger.debug("channel %s already notified for %s", channel.value, alert.alert_id)
            return

        now = self.clock()
        message = compose_message(alert, channel, self.policy.owner_name)
        for index, contact in enumerate(contacts, start=1):
            try:
                delivered = self.notifier.send(contact, alert, message)
                detail = ""
            except Exception as error:  # transport is broken, not merely down
                logger.exception("notifier raised for %s", contact.contact_id)
                delivered, detail = False, f"{type(error).__name__}: {error}"

            alert.notifications.append(
                NotificationAttempt(
                    channel=channel,
                    contact_id=contact.contact_id,
                    attempt=index,
                    at_seconds=now,
                    status=DeliveryStatus.DELIVERED if delivered else DeliveryStatus.FAILED,
                    detail=detail,
                )
            )
            if not delivered:
                logger.error(
                    "could not reach %s on %s for %s",
                    contact.contact_id,
                    channel.value,
                    alert.alert_id,
                )

    def _require(self, alert_id: str) -> Alert:
        alert = self.alerts.get(alert_id)
        if alert is None:
            raise KeyError(f"unknown alert {alert_id!r}")
        return alert

    def _emit(self, alert: Alert) -> None:
        if self.on_transition is not None:
            try:
                self.on_transition(alert)
            except Exception:
                # Persistence must never be able to break an in-flight
                # escalation; a lost log line is survivable, a lost page is not.
                logger.exception("on_transition handler failed for %s", alert.alert_id)

    # ------------------------------------------------------------------ #
    # queries
    # ------------------------------------------------------------------ #
    def open_alerts(self) -> list[Alert]:
        return [a for a in self.alerts.values() if a.state.is_open]

    def history(self) -> list[Alert]:
        return sorted(self.alerts.values(), key=lambda a: a.raised_at_seconds)

    def next_deadline(self) -> float | None:
        """Earliest pending deadline, so a driver can sleep instead of spin."""
        deadlines = [a.deadline_seconds for a in self.open_alerts() if a.deadline_seconds]
        return min(deadlines) if deadlines else None


def _initial_transition(at_seconds: float, to_state: AlertState, reason: str):
    from .model import Transition

    return Transition(at_seconds=at_seconds, from_state=None, to_state=to_state, reason=reason)


def summarise(alerts: Iterable[Alert]) -> dict:
    """Aggregate statistics for the caregiver dashboard.

    The secondary contribution of the system: over months, this table says
    whether the dog's trained alert is still reliable and whether the owner is
    still responding to it.
    """
    alerts = list(alerts)
    by_state: dict[str, int] = {}
    for alert in alerts:
        by_state[alert.state.value] = by_state.get(alert.state.value, 0) + 1

    response_times = [
        seconds
        for seconds in (a.owner_response_seconds() for a in alerts)
        if seconds is not None
    ]
    escalated = sum(
        1
        for a in alerts
        if a.state in {AlertState.ACKNOWLEDGED_BY_CAREGIVER, AlertState.ESCALATED_EMERGENCY}
    )
    dismissed = by_state.get(AlertState.DISMISSED_FALSE_POSITIVE.value, 0)

    return {
        "total_alerts": len(alerts),
        "by_state": by_state,
        "escalated": escalated,
        "escalation_rate": escalated / len(alerts) if alerts else 0.0,
        "dismissed_false_positive": dismissed,
        "false_positive_rate": dismissed / len(alerts) if alerts else 0.0,
        "owner_response": {
            "n": len(response_times),
            "mean_seconds": sum(response_times) / len(response_times) if response_times else None,
            "max_seconds": max(response_times) if response_times else None,
        },
    }
