"""The simulator must agree with the closed forms and with the formal model."""

from __future__ import annotations

import logging
import random

import pytest

from escalation.sim import SCENARIOS, run_scenario, simulate_episode
from escalation.sim.scenario import OWNER_AWAKE, Responder
from escalation.sim.simulate import false_alarm_burden, summarise

logging.getLogger("escalation").setLevel(logging.CRITICAL)


def test_responder_cdf_is_a_scaled_lognormal():
    r = Responder(p_responds=0.5, median_s=30.0)
    assert r.cdf(30.0) == pytest.approx(0.25)
    assert r.cdf(1e9) == pytest.approx(0.5)
    assert r.cdf(0.0) == 0.0


def test_closed_form_burden_matches_monte_carlo():
    # A false alarm is an "alert" the collar always raises; the share of them
    # that reach the caregiver must match the closed form for an awake owner.
    sc = SCENARIOS["owner_awake"].with_(p_detect=1.0, latencies_s=(0.0,))
    results = run_scenario(sc, 6000, seed=3)
    simulated = sum(1 for r in results if r.pages_on("CAREGIVER")) / len(results)
    expected = false_alarm_burden(1.0, 60.0, 120.0, hours_awake=24.0, hours_asleep=0.0)["p_reaches_caregiver"]
    assert simulated == pytest.approx(expected, abs=0.012)


def test_incapacitated_owner_never_closes_by_owner_and_caregiver_first_paged_at_t1():
    sc = SCENARIOS["owner_incapacitated"].with_(p_detect=1.0, latencies_s=(4.0,))
    for r in run_scenario(sc, 500, seed=1):
        assert r.first_ack_by in ("caregiver", "emergency", None)
        care = r.pages_on("CAREGIVER")
        assert care and care[0][2] == pytest.approx(4.0 + 60.0, abs=1.0)


def test_direct_watchdog_can_skip_the_caregiver_and_ladder_watchdog_never_does():
    # The simulation counterpart of NoPrematureEmergency in formal/Escalation.tla.
    sc = SCENARIOS["incapacitated_relay_dies"].with_(p_detect=1.0, latencies_s=(4.0,))
    direct = summarise(run_scenario(sc, 2000, seed=5))
    ladder = summarise(run_scenario(sc.with_(watchdog_mode="ladder"), 2000, seed=5))
    assert direct["p_caregiver_skipped"] > 0.05
    assert ladder["p_caregiver_skipped"] == 0.0


def test_reliable_infrastructure_never_duplicates_or_pages_after_owner_response():
    # The simulation counterpart of the SpecReliable checks.
    for name in ("owner_awake", "owner_asleep", "owner_incapacitated"):
        s = summarise(run_scenario(SCENARIOS[name].with_(p_detect=1.0), 2000, seed=7))
        assert s["p_duplicate_emergency"] == 0.0
        assert s["p_page_after_owner_response"] == 0.0
        assert s["p_caregiver_skipped"] == 0.0


def test_phone_dead_before_detection_is_counted_as_lost():
    sc = SCENARIOS["owner_awake"].with_(p_detect=1.0, latencies_s=(100.0,), p_relay_dies=1.0, fault_window_s=50.0)
    r = simulate_episode(sc, random.Random(0))
    assert r.detected and r.lost and not r.pages
