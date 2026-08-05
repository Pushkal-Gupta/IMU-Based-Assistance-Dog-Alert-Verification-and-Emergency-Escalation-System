"""The escalation ladder.

Each test names a real failure mode.  The suite is the specification: the Java
implementation in ``backend/`` mirrors these transitions, and
``docs/04-escalation-protocol.md`` is written from them.
"""

from __future__ import annotations

import pytest

from escalation import (
    AlertState,
    Channel,
    Contact,
    DetectionEvent,
    EscalationEngine,
    EscalationPolicy,
    Location,
    RecordingNotifier,
    summarise,
)


# --------------------------------------------------------------------------- #
# the happy path: the owner is fine and says so
# --------------------------------------------------------------------------- #
def test_detection_opens_an_alert_and_pages_only_the_owner(engine, detection, notifier):
    alert = engine.submit(detection)
    assert alert.state is AlertState.PENDING_OWNER
    assert notifier.channels() == [Channel.OWNER]


def test_owner_acknowledgement_closes_the_alert(engine, detection, notifier, clock):
    alert = engine.submit(detection)
    clock.advance(12)
    engine.acknowledge(alert.alert_id, Channel.OWNER)

    assert alert.state is AlertState.ACKNOWLEDGED_BY_OWNER
    assert alert.owner_response_seconds() == pytest.approx(12)
    assert alert.deadline_seconds is None


def test_no_caregiver_is_paged_when_the_owner_responds(engine, detection, notifier, clock):
    alert = engine.submit(detection)
    clock.advance(30)
    engine.acknowledge(alert.alert_id, Channel.OWNER)

    clock.advance(10_000)
    assert engine.tick() == []
    assert notifier.channels() == [Channel.OWNER]


def test_acknowledgement_at_the_very_last_moment_still_counts(engine, detection, notifier, clock):
    """Boundary: T1 is a deadline, so acknowledging *at* T1 must be in time."""
    alert = engine.submit(detection)
    clock.advance(60.0)
    engine.acknowledge(alert.alert_id, Channel.OWNER)
    assert alert.state is AlertState.ACKNOWLEDGED_BY_OWNER

    engine.tick()
    assert Channel.CAREGIVER not in notifier.channels()


# --------------------------------------------------------------------------- #
# the path the whole project exists for: the owner cannot respond
# --------------------------------------------------------------------------- #
def test_silence_pages_the_caregiver_after_t1(engine, detection, notifier, clock):
    alert = engine.submit(detection)
    clock.advance(60.0)
    changed = engine.tick()

    assert changed == [alert]
    assert alert.state is AlertState.PENDING_CAREGIVER
    assert notifier.channels() == [Channel.OWNER, Channel.CAREGIVER]


def test_caregiver_is_not_paged_before_t1(engine, detection, notifier, clock):
    engine.submit(detection)
    clock.advance(59.9)
    assert engine.tick() == []
    assert notifier.channels() == [Channel.OWNER]


def test_continued_silence_reaches_the_emergency_contact(engine, detection, notifier, clock):
    alert = engine.submit(detection)
    clock.advance(60.0)
    engine.tick()
    clock.advance(120.0)
    engine.tick()

    assert alert.state is AlertState.ESCALATED_EMERGENCY
    assert notifier.channels() == [Channel.OWNER, Channel.CAREGIVER, Channel.EMERGENCY]


def test_caregiver_acknowledgement_stops_the_ladder(engine, detection, notifier, clock):
    alert = engine.submit(detection)
    clock.advance(60.0)
    engine.tick()
    clock.advance(30.0)
    engine.acknowledge(alert.alert_id, Channel.CAREGIVER)

    clock.advance(10_000)
    engine.tick()
    assert alert.state is AlertState.ACKNOWLEDGED_BY_CAREGIVER
    assert Channel.EMERGENCY not in notifier.channels()


def test_full_ladder_takes_exactly_t1_plus_t2(engine, detection, clock):
    alert = engine.submit(detection)
    raised_at = alert.raised_at_seconds
    clock.advance(60.0)
    engine.tick()
    clock.advance(120.0)
    engine.tick()

    escalated = next(
        t for t in alert.transitions if t.to_state is AlertState.ESCALATED_EMERGENCY
    )
    assert escalated.at_seconds - raised_at == pytest.approx(180.0)


# --------------------------------------------------------------------------- #
# at-most-once paging
# --------------------------------------------------------------------------- #
def test_repeated_ticks_do_not_repage(engine, detection, notifier, clock):
    """A caregiver paged once per second would learn to ignore the app."""
    engine.submit(detection)
    clock.advance(60.0)
    for _ in range(50):
        engine.tick()
    assert notifier.channels().count(Channel.CAREGIVER) == 1


def test_duplicate_detections_do_not_open_a_second_alert(engine, detection, notifier):
    """BLE retransmits; the same episode must not page twice."""
    first = engine.submit(detection)
    second = engine.submit(detection)

    assert first is second
    assert len(engine.alerts) == 1
    assert notifier.channels() == [Channel.OWNER]


def test_a_genuinely_new_episode_does_open_a_second_alert(engine, detection, notifier):
    engine.submit(detection)
    later = DetectionEvent(
        dog_id=detection.dog_id,
        sequence=detection.sequence + 1,
        device_uptime_ms=detection.device_uptime_ms + 90_000,
        confidence=0.77,
        votes=2,
        window_count=4,
    )
    engine.submit(later)
    assert len(engine.alerts) == 2
    assert notifier.channels().count(Channel.OWNER) == 2


# --------------------------------------------------------------------------- #
# late and out-of-order human responses
# --------------------------------------------------------------------------- #
def test_late_owner_acknowledgement_does_not_unring_the_bell(engine, detection, clock):
    """Once a caregiver has been paged, a late tap cannot rewrite history."""
    alert = engine.submit(detection)
    clock.advance(60.0)
    engine.tick()
    clock.advance(200.0)
    engine.tick()  # emergency

    clock.advance(5)
    engine.acknowledge(alert.alert_id, Channel.OWNER)

    assert alert.state is AlertState.ESCALATED_EMERGENCY
    assert any("late owner acknowledgement" in t.reason for t in alert.transitions)


def test_owner_acknowledgement_during_the_caregiver_window_closes_the_alert(
    engine, detection, notifier, clock
):
    """The owner came round after the caregiver was paged: stop at the caregiver."""
    alert = engine.submit(detection)
    clock.advance(60.0)
    engine.tick()
    clock.advance(20.0)
    engine.acknowledge(alert.alert_id, Channel.OWNER)

    clock.advance(10_000)
    engine.tick()
    assert alert.state is AlertState.ACKNOWLEDGED_BY_OWNER
    assert Channel.EMERGENCY not in notifier.channels()


def test_caregiver_may_acknowledge_before_being_formally_paged(engine, detection, clock):
    """They were in the room. Unusual, not an error."""
    alert = engine.submit(detection)
    clock.advance(10)
    engine.acknowledge(alert.alert_id, Channel.CAREGIVER)
    assert alert.state is AlertState.ACKNOWLEDGED_BY_CAREGIVER


def test_emergency_contacts_cannot_acknowledge(engine, detection):
    alert = engine.submit(detection)
    with pytest.raises(ValueError, match="cannot acknowledge"):
        engine.acknowledge(alert.alert_id, Channel.EMERGENCY)


def test_unknown_alert_is_an_error(engine):
    with pytest.raises(KeyError):
        engine.acknowledge("alert_does_not_exist", Channel.OWNER)


# --------------------------------------------------------------------------- #
# dismissal and cancellation
# --------------------------------------------------------------------------- #
def test_dismissal_is_recorded_separately_from_acknowledgement(engine, detection, notifier, clock):
    """False positives must stay countable, or the training report lies."""
    alert = engine.submit(detection)
    engine.dismiss(alert.alert_id)
    assert alert.state is AlertState.DISMISSED_FALSE_POSITIVE

    clock.advance(10_000)
    engine.tick()
    assert notifier.channels() == [Channel.OWNER]


def test_cancel_before_anyone_else_was_paged(engine, detection):
    alert = engine.submit(detection)
    engine.cancel(alert.alert_id, "collar retracted the detection")
    assert alert.state is AlertState.CANCELLED


def test_cannot_cancel_once_a_caregiver_has_been_paged(engine, detection, clock):
    alert = engine.submit(detection)
    clock.advance(60.0)
    engine.tick()
    with pytest.raises(ValueError, match="already been paged"):
        engine.cancel(alert.alert_id, "too late")


def test_dismissing_a_closed_alert_is_a_no_op(engine, detection, clock):
    alert = engine.submit(detection)
    engine.acknowledge(alert.alert_id, Channel.OWNER)
    before = len(alert.transitions)
    engine.dismiss(alert.alert_id)
    assert alert.state is AlertState.ACKNOWLEDGED_BY_OWNER
    assert len(alert.transitions) == before


# --------------------------------------------------------------------------- #
# location handling
# --------------------------------------------------------------------------- #
def test_fresh_location_is_attached_and_sent(engine, detection, fresh_location, notifier):
    alert = engine.submit(detection, fresh_location)
    assert alert.location == fresh_location
    _, _, message = notifier.delivered[0]
    assert "53.38620" in message


def test_stale_location_is_dropped_rather_than_sent(engine, detection, notifier):
    """A coordinate reads as authoritative; a wrong one sends help to the wrong place."""
    stale = Location(latitude=53.3862, longitude=-6.2568, accuracy_m=8.0, age_seconds=3600.0)
    alert = engine.submit(detection, stale)
    assert alert.location is None
    _, _, message = notifier.delivered[0]
    assert "No recent location fix" in message


def test_missing_location_says_so_explicitly(engine, detection, notifier):
    engine.submit(detection, None)
    _, _, message = notifier.delivered[0]
    assert "No recent location fix" in message


def test_escalation_message_names_the_non_response(engine, detection, notifier, clock):
    """The caregiver is being contacted because the owner went quiet -- say it."""
    engine.submit(detection)
    clock.advance(60.0)
    engine.tick()
    caregiver_message = next(m for c, _, m in notifier.delivered if c is Channel.CAREGIVER)
    assert "did not respond" in caregiver_message
    assert "Alex" in caregiver_message


# --------------------------------------------------------------------------- #
# degraded configurations and delivery failures
# --------------------------------------------------------------------------- #
def test_missing_caregiver_escalates_straight_to_emergency(owner, emergency, clock, detection):
    """Never park an alert in a state that has no exit."""
    notifier = RecordingNotifier()
    engine = EscalationEngine(
        policy=EscalationPolicy(
            owner=owner, caregivers=(), emergency=(emergency,), owner_ack_seconds=60.0
        ),
        notifier=notifier,
        clock=clock,
    )
    alert = engine.submit(detection)
    clock.advance(60.0)
    engine.tick()

    assert alert.state is AlertState.ESCALATED_EMERGENCY
    assert notifier.channels() == [Channel.OWNER, Channel.EMERGENCY]


def test_no_emergency_contact_closes_honestly(owner, caregiver, clock, detection):
    """With nowhere left to escalate, say so rather than implying help is coming."""
    notifier = RecordingNotifier()
    engine = EscalationEngine(
        policy=EscalationPolicy(
            owner=owner,
            caregivers=(caregiver,),
            emergency=(),
            owner_ack_seconds=60.0,
            caregiver_ack_seconds=120.0,
        ),
        notifier=notifier,
        clock=clock,
    )
    alert = engine.submit(detection)
    clock.advance(60.0)
    engine.tick()
    clock.advance(120.0)
    engine.tick()

    assert alert.state is AlertState.ESCALATED_EMERGENCY
    assert any("no emergency contact" in t.reason for t in alert.transitions)


def test_unreachable_caregiver_still_escalates(policy, clock, detection):
    """An undelivered page must not become an infinite wait for a reply."""
    notifier = RecordingNotifier(failing_channels={Channel.CAREGIVER})
    engine = EscalationEngine(policy=policy, notifier=notifier, clock=clock)
    alert = engine.submit(detection)
    clock.advance(60.0)
    engine.tick()
    assert not alert.reached_channel(Channel.CAREGIVER)

    clock.advance(120.0)
    engine.tick()
    assert alert.state is AlertState.ESCALATED_EMERGENCY
    assert alert.reached_channel(Channel.EMERGENCY)


def test_failed_delivery_is_recorded(policy, clock, detection):
    notifier = RecordingNotifier(failing_channels={Channel.OWNER})
    engine = EscalationEngine(policy=policy, notifier=notifier, clock=clock)
    alert = engine.submit(detection)
    assert alert.notifications[0].status.value == "FAILED"


def test_a_raising_notifier_does_not_abort_the_escalation(policy, clock, detection):
    class BrokenNotifier:
        def send(self, contact, alert, message):
            raise RuntimeError("carrier gateway is down")

    engine = EscalationEngine(policy=policy, notifier=BrokenNotifier(), clock=clock)
    alert = engine.submit(detection)
    clock.advance(60.0)
    engine.tick()
    clock.advance(120.0)
    engine.tick()

    assert alert.state is AlertState.ESCALATED_EMERGENCY
    assert all(n.status.value == "FAILED" for n in alert.notifications)
    assert "RuntimeError" in alert.notifications[0].detail


def test_a_failing_persistence_hook_does_not_abort_the_escalation(policy, clock, detection):
    """Losing a log line is survivable; losing a page is not."""
    notifier = RecordingNotifier()

    def broken_hook(_alert):
        raise IOError("database unreachable")

    engine = EscalationEngine(
        policy=policy, notifier=notifier, clock=clock, on_transition=broken_hook
    )
    alert = engine.submit(detection)
    clock.advance(60.0)
    engine.tick()
    clock.advance(120.0)
    engine.tick()
    assert alert.state is AlertState.ESCALATED_EMERGENCY


# --------------------------------------------------------------------------- #
# confidence gating
# --------------------------------------------------------------------------- #
def test_low_confidence_detections_are_suppressed(owner, caregiver, emergency, clock):
    suppressed = []
    notifier = RecordingNotifier()
    engine = EscalationEngine(
        policy=EscalationPolicy(
            owner=owner,
            caregivers=(caregiver,),
            emergency=(emergency,),
            min_confidence=0.6,
        ),
        notifier=notifier,
        clock=clock,
        on_suppressed=lambda detection, reason: suppressed.append(reason),
    )
    weak = DetectionEvent("stuart", 9, 1000, confidence=0.4, votes=2, window_count=4)
    assert engine.submit(weak) is None
    assert notifier.delivered == []
    assert len(suppressed) == 1


# --------------------------------------------------------------------------- #
# policy validation
# --------------------------------------------------------------------------- #
def test_policy_rejects_a_non_positive_window(owner):
    with pytest.raises(ValueError, match="must be positive"):
        EscalationPolicy(owner=owner, owner_ack_seconds=0)


def test_policy_rejects_mislabelled_contacts(owner):
    wrong = Contact("x", "X", Channel.OWNER, "1")
    with pytest.raises(ValueError, match="not a CAREGIVER"):
        EscalationPolicy(owner=owner, caregivers=(wrong,))


# --------------------------------------------------------------------------- #
# queries and reporting
# --------------------------------------------------------------------------- #
def test_next_deadline_lets_a_driver_sleep(engine, detection, clock):
    alert = engine.submit(detection)
    assert engine.next_deadline() == pytest.approx(alert.raised_at_seconds + 60.0)
    engine.acknowledge(alert.alert_id, Channel.OWNER)
    assert engine.next_deadline() is None


def test_open_alerts_excludes_closed_ones(engine, detection, clock):
    alert = engine.submit(detection)
    assert engine.open_alerts() == [alert]
    engine.acknowledge(alert.alert_id, Channel.OWNER)
    assert engine.open_alerts() == []


def test_transitions_form_a_complete_audit_trail(engine, detection, clock):
    alert = engine.submit(detection)
    clock.advance(60.0)
    engine.tick()
    clock.advance(120.0)
    engine.tick()

    states = [t.to_state for t in alert.transitions]
    assert states == [
        AlertState.PENDING_OWNER,
        AlertState.PENDING_CAREGIVER,
        AlertState.ESCALATED_EMERGENCY,
    ]
    assert all(t.reason for t in alert.transitions), "every transition must say why"
    timestamps = [t.at_seconds for t in alert.transitions]
    assert timestamps == sorted(timestamps)


def test_summary_separates_escalations_from_false_positives(engine, clock):
    """The caregiver's monthly view: is the dog still reliable, is the owner
    still answering?"""
    for index in range(4):
        alert = engine.submit(
            DetectionEvent("stuart", index, 1000 * (index + 1), 0.8, 2, 4)
        )
        if index == 0:
            engine.acknowledge(alert.alert_id, Channel.OWNER)
        elif index == 1:
            engine.dismiss(alert.alert_id)
        else:
            clock.advance(60.0)
            engine.tick()
            clock.advance(120.0)
            engine.tick()

    stats = summarise(engine.history())
    assert stats["total_alerts"] == 4
    assert stats["escalated"] == 2
    assert stats["dismissed_false_positive"] == 1
    assert stats["escalation_rate"] == pytest.approx(0.5)
    assert stats["owner_response"]["n"] == 1


def test_alert_serialises_for_the_backend(engine, detection, fresh_location, clock):
    alert = engine.submit(detection, fresh_location)
    clock.advance(60.0)
    engine.tick()
    payload = alert.as_dict()

    assert payload["state"] == AlertState.PENDING_CAREGIVER.value
    assert payload["location"]["latitude"] == pytest.approx(53.3862)
    assert len(payload["transitions"]) == 2
    assert payload["notifications"][0]["channel"] == Channel.OWNER.value
    import json

    json.dumps(payload)  # must be JSON-serialisable for the REST layer
