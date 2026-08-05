"""Domain types and notification transports."""

from __future__ import annotations

import pytest

from escalation import (
    Alert,
    AlertState,
    Channel,
    Contact,
    DetectionEvent,
    FanOutNotifier,
    Location,
    RecordingNotifier,
    RetryingNotifier,
    compose_message,
)


# --------------------------------------------------------------------------- #
# alert identity
# --------------------------------------------------------------------------- #
def test_alert_id_is_stable_across_deliveries():
    a = DetectionEvent("stuart", 3, 55_000, 0.9, 2, 4)
    b = DetectionEvent("stuart", 3, 55_000, 0.9, 2, 4)
    assert a.alert_id() == b.alert_id()


def test_alert_id_changes_with_the_episode():
    base = DetectionEvent("stuart", 3, 55_000, 0.9, 2, 4)
    assert base.alert_id() != DetectionEvent("stuart", 4, 55_000, 0.9, 2, 4).alert_id()
    assert base.alert_id() != DetectionEvent("rosie", 3, 55_000, 0.9, 2, 4).alert_id()
    assert base.alert_id() != DetectionEvent("stuart", 3, 55_001, 0.9, 2, 4).alert_id()


def test_alert_id_ignores_fields_that_may_differ_between_retransmits():
    """Confidence is a float that a retransmit could round differently."""
    a = DetectionEvent("stuart", 3, 55_000, 0.90, 2, 4)
    b = DetectionEvent("stuart", 3, 55_000, 0.91, 3, 4)
    assert a.alert_id() == b.alert_id()


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_detection_rejects_out_of_range_confidence(confidence):
    with pytest.raises(ValueError, match="confidence"):
        DetectionEvent("stuart", 1, 1000, confidence, 2, 4)


def test_detection_rejects_a_dog_id_that_would_break_a_url():
    with pytest.raises(ValueError, match="dog_id"):
        DetectionEvent("../../etc/passwd", 1, 1000, 0.9, 2, 4)


def test_detection_rejects_a_negative_sequence():
    with pytest.raises(ValueError, match="sequence"):
        DetectionEvent("stuart", -1, 1000, 0.9, 2, 4)


# --------------------------------------------------------------------------- #
# state classification
# --------------------------------------------------------------------------- #
def test_pending_states_are_open_and_the_rest_are_terminal():
    open_states = {AlertState.PENDING_OWNER, AlertState.PENDING_CAREGIVER}
    for state in AlertState:
        assert state.is_open is (state in open_states), state
        assert state.is_terminal is not state.is_open


# --------------------------------------------------------------------------- #
# location
# --------------------------------------------------------------------------- #
def test_location_validates_its_coordinates():
    with pytest.raises(ValueError, match="latitude"):
        Location(91.0, 0.0, 5.0, 1.0)
    with pytest.raises(ValueError, match="longitude"):
        Location(0.0, 181.0, 5.0, 1.0)
    with pytest.raises(ValueError, match="non-negative"):
        Location(0.0, 0.0, -1.0, 1.0)


def test_freshness_boundary_is_inclusive():
    assert Location(0.0, 0.0, 5.0, 300.0).is_fresh(300.0)
    assert not Location(0.0, 0.0, 5.0, 300.1).is_fresh(300.0)


def test_map_url_carries_both_coordinates():
    url = Location(53.3862, -6.2568, 5.0, 1.0).map_url()
    assert "53.386200" in url and "-6.256800" in url


# --------------------------------------------------------------------------- #
# contact privacy
# --------------------------------------------------------------------------- #
def test_addresses_are_redacted_for_the_shared_log():
    """Vets and trainers read the alert history; they don't need phone numbers."""
    contact = Contact("c1", "Sam", Channel.CAREGIVER, "+15550111")
    assert contact.redacted_address() == "******111"
    assert "5550" not in contact.redacted_address()


def test_redaction_handles_a_very_short_address():
    assert Contact("c1", "S", Channel.EMERGENCY, "112").redacted_address() == "***"


# --------------------------------------------------------------------------- #
# message composition
# --------------------------------------------------------------------------- #
def _alert(location=None):
    return Alert(
        alert_id="alert_test",
        dog_id="stuart",
        raised_at_seconds=0.0,
        confidence=0.82,
        location=location,
    )


def test_owner_message_asks_for_confirmation():
    message = compose_message(_alert(), Channel.OWNER, "Alex")
    assert "confirm you are OK" in message
    assert "82%" in message


def test_caregiver_message_explains_why_they_were_contacted():
    message = compose_message(_alert(), Channel.CAREGIVER, "Alex")
    assert "did not respond" in message


def test_emergency_message_states_that_nobody_responded():
    message = compose_message(_alert(), Channel.EMERGENCY, "Alex")
    assert "EMERGENCY" in message
    assert "Neither Alex nor their caregiver responded" in message


def test_message_includes_the_fix_age_so_a_responder_can_judge_it():
    message = compose_message(
        _alert(Location(53.3862, -6.2568, 8.0, 42.0)), Channel.EMERGENCY, "Alex"
    )
    assert "42 s old" in message
    assert "+/-8 m" in message


# --------------------------------------------------------------------------- #
# retry and fan-out
# --------------------------------------------------------------------------- #
def test_retrying_notifier_recovers_from_a_transient_failure():
    slept: list[float] = []
    inner = RecordingNotifier(fail_first_n=2)
    notifier = RetryingNotifier(inner, max_attempts=3, backoff_seconds=5.0, sleep=slept.append)
    contact = Contact("c", "Sam", Channel.CAREGIVER, "+1")

    assert notifier.send(contact, _alert(), "hello") is True
    assert slept == [5.0, 10.0], "backoff must increase between attempts"


def test_retrying_notifier_gives_up_after_max_attempts():
    inner = RecordingNotifier(failing_channels={Channel.CAREGIVER})
    notifier = RetryingNotifier(inner, max_attempts=3, sleep=lambda _s: None)
    assert notifier.send(Contact("c", "S", Channel.CAREGIVER, "+1"), _alert(), "x") is False


def test_retrying_notifier_never_sleeps_after_the_final_attempt():
    slept: list[float] = []
    inner = RecordingNotifier(failing_channels={Channel.CAREGIVER})
    RetryingNotifier(inner, max_attempts=3, sleep=slept.append).send(
        Contact("c", "S", Channel.CAREGIVER, "+1"), _alert(), "x"
    )
    assert len(slept) == 2, "3 attempts means 2 gaps"


def test_retrying_notifier_survives_a_raising_transport():
    class Exploding:
        def send(self, contact, alert, message):
            raise ConnectionError("no route to host")

    notifier = RetryingNotifier(Exploding(), max_attempts=2, sleep=lambda _s: None)
    assert notifier.send(Contact("c", "S", Channel.EMERGENCY, "112"), _alert(), "x") is False


def test_fan_out_tries_every_transport_even_after_one_succeeds():
    """Redundant paths are the point; a success on SMS is no reason to skip push."""
    push = RecordingNotifier()
    sms = RecordingNotifier()
    notifier = FanOutNotifier([push, sms])
    contact = Contact("c", "S", Channel.EMERGENCY, "112")

    assert notifier.send(contact, _alert(), "x") is True
    assert len(push.delivered) == 1
    assert len(sms.delivered) == 1


def test_fan_out_succeeds_when_only_one_transport_works():
    broken = RecordingNotifier(failing_channels={Channel.EMERGENCY})
    working = RecordingNotifier()
    notifier = FanOutNotifier([broken, working])
    assert notifier.send(Contact("c", "S", Channel.EMERGENCY, "112"), _alert(), "x") is True


def test_fan_out_reports_total_failure():
    broken = RecordingNotifier(failing_channels={Channel.EMERGENCY})
    notifier = FanOutNotifier([broken])
    assert notifier.send(Contact("c", "S", Channel.EMERGENCY, "112"), _alert(), "x") is False
