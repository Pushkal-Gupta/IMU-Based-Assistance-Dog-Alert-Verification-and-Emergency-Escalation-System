"""Property-based conformance tests: the real engine against the TLA+ invariants.

``formal/Escalation.tla`` proves properties of a *model* of the ladder.  These
tests close the gap between that model and ``escalation/engine.py``: Hypothesis
generates random interleavings of clock advances, ticks, acknowledgements,
dismissals, cancellations and duplicate submissions -- against random policies
and random delivery failures -- and every invariant is checked after every
step.  A counterexample here is a place where the code and the specification
disagree.

Run the thorough profile used for the paper with::

    HYPOTHESIS_PROFILE=thorough python -m pytest escalation/tests/test_properties.py
"""

from __future__ import annotations

import os

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings, strategies as st  # noqa: E402

from escalation import (  # noqa: E402
    AlertState,
    Channel,
    Contact,
    DetectionEvent,
    EscalationEngine,
    EscalationPolicy,
    RecordingNotifier,
)

settings.register_profile("default", max_examples=1500, deadline=None)
settings.register_profile("thorough", max_examples=10_000, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))


class Clock:
    def __init__(self) -> None:
        self.now = 5000.0

    def __call__(self) -> float:
        return self.now


OWNER = Contact("o", "Owner", Channel.OWNER, "+10000000001")
CARE = (Contact("c1", "Carer 1", Channel.CAREGIVER, "+10000000002"),
        Contact("c2", "Carer 2", Channel.CAREGIVER, "+10000000003"))
EMERG = (Contact("e1", "Monitoring", Channel.EMERGENCY, "+10000000004"),)

operations = st.lists(
    st.one_of(
        st.tuples(st.just("advance"), st.floats(min_value=0.0, max_value=90.0, allow_nan=False)),
        st.just(("tick",)),
        st.just(("owner_ack",)),
        st.just(("owner_dismiss",)),
        st.just(("care_ack",)),
        st.just(("resubmit",)),
        st.just(("cancel",)),
    ),
    min_size=1,
    max_size=40,
)

policies = st.fixed_dictionaries(
    {
        "t1": st.sampled_from([10.0, 30.0, 60.0, 90.0]),
        "t2": st.sampled_from([20.0, 60.0, 120.0]),
        "n_care": st.integers(0, 2),
        "n_emerg": st.integers(0, 1),
        "failing": st.sets(st.sampled_from(list(Channel))),
    }
)


def _build(cfg):
    clock = Clock()
    policy = EscalationPolicy(
        owner=OWNER,
        caregivers=CARE[: cfg["n_care"]],
        emergency=EMERG[: cfg["n_emerg"]],
        owner_ack_seconds=cfg["t1"],
        caregiver_ack_seconds=cfg["t2"],
    )
    notifier = RecordingNotifier(failing_channels=set(cfg["failing"]))
    engine = EscalationEngine(policy=policy, notifier=notifier, clock=clock)
    return clock, policy, engine


DETECTION = DetectionEvent(dog_id="dog", sequence=7, device_uptime_ms=99, confidence=0.7, votes=2, window_count=4)


def _attempts(alert, channel):
    return [n for n in alert.notifications if n.channel == channel]


@given(cfg=policies, ops=operations)
def test_engine_satisfies_the_specification_invariants(cfg, ops):
    clock, policy, engine = _build(cfg)
    alert = engine.submit(DETECTION)
    raised = clock.now
    owner_response_at = None
    terminal_state = None
    seen_transitions = 1

    for op in ops:
        kind = op[0]
        before_pages = len(alert.notifications)
        if kind == "advance":
            clock.now += op[1]
        elif kind == "tick":
            engine.tick()
            # No missed timer: after a tick, no open stage is past its deadline.
            if alert.state.is_open:
                assert alert.deadline_seconds is not None and alert.deadline_seconds > clock.now
        elif kind == "owner_ack":
            was_open = alert.state.is_open
            engine.acknowledge(alert.alert_id, Channel.OWNER)
            if was_open and owner_response_at is None:
                owner_response_at = clock.now
        elif kind == "owner_dismiss":
            was_open = alert.state.is_open
            engine.dismiss(alert.alert_id)
            if was_open and owner_response_at is None:
                owner_response_at = clock.now
        elif kind == "care_ack":
            engine.acknowledge(alert.alert_id, Channel.CAREGIVER)
        elif kind == "resubmit":
            again = engine.submit(DETECTION)
            # Idempotent ingestion: same alert object, nobody paged again.
            assert again is alert
            assert len(alert.notifications) == before_pages
        elif kind == "cancel":
            reached = alert.reached_channel(Channel.CAREGIVER) or alert.reached_channel(Channel.EMERGENCY)
            if reached and alert.state.is_open:
                with pytest.raises(ValueError):
                    engine.cancel(alert.alert_id, "test")
            else:
                engine.cancel(alert.alert_id, "test")

        # P1 at-most-once per channel: one attempt per configured contact, ever.
        assert len(_attempts(alert, Channel.OWNER)) == 1
        assert len(_attempts(alert, Channel.CAREGIVER)) in (0, len(policy.caregivers))
        assert len(_attempts(alert, Channel.EMERGENCY)) in (0, len(policy.emergency))

        # P2 the emergency contact is paged only after the windows elapsed.
        for n in _attempts(alert, Channel.EMERGENCY):
            floor = policy.owner_ack_seconds + (policy.caregiver_ack_seconds if policy.caregivers else 0.0)
            assert n.at_seconds - raised >= floor - 1e-9

        # P3 nobody beyond the owner is paged after the owner responded.
        if owner_response_at is not None:
            for n in alert.notifications:
                if n.channel is not Channel.OWNER:
                    assert n.at_seconds <= owner_response_at

        # Terminal states absorb.
        if terminal_state is not None:
            assert alert.state is terminal_state
        elif alert.state.is_terminal:
            terminal_state = alert.state

        # The audit trail only grows and is time-ordered.
        assert len(alert.transitions) >= seen_transitions
        seen_transitions = len(alert.transitions)
        times = [t.at_seconds for t in alert.transitions]
        assert times == sorted(times)

    # P4 bounded response: drive the clock well past every deadline with
    # prompt ticks, and the alert must be closed.
    for _ in range(3):
        clock.now += policy.owner_ack_seconds + policy.caregiver_ack_seconds
        engine.tick()
    assert alert.state.is_terminal


@given(cfg=policies, gaps=st.lists(st.floats(0.25, 5.0, allow_nan=False), min_size=1, max_size=60))
def test_prompt_ticks_escalate_on_time(cfg, gaps):
    """With ticks at most 5 s apart and no human response, every stage fires
    within one tick interval of its nominal deadline (the bounded-lateness
    assumption the TLA+ model's urgent Tick encodes)."""
    clock, policy, engine = _build(cfg)
    alert = engine.submit(DETECTION)
    raised = clock.now
    total = 0.0
    while total < policy.owner_ack_seconds + policy.caregiver_ack_seconds + 10:
        step = gaps[int(total) % len(gaps)]
        clock.now += step
        total += step
        engine.tick()
    if policy.caregivers:
        care = _attempts(alert, Channel.CAREGIVER)[0].at_seconds - raised
        assert policy.owner_ack_seconds <= care <= policy.owner_ack_seconds + 5.0
    assert alert.state is AlertState.ESCALATED_EMERGENCY
