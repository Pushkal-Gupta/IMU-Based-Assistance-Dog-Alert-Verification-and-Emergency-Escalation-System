"""One alert episode, end to end, on a simulated clock.

The relay side is the real :class:`EscalationEngine`; nothing about the ladder
is re-implemented here.  Around it the simulation supplies what the engine
cannot see: when the dog alerts and whether the collar catches it, when (and
whether) each human answers, whether pages are delivered, whether the phone
dies or loses its connection, and the backend watchdog -- a port of
``backend/.../EscalationWatchdog.java`` plus the ladder-aware variant checked
in ``formal/Escalation.tla``.

Time advances in one-second steps, which is the relay's own tick rate, so the
simulated lateness of every timer matches the deployed driver.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from ..engine import EscalationEngine, EscalationPolicy
from ..model import AlertState, Channel, Contact, DetectionEvent
from .scenario import Responder, Scenario

OWNER = Contact("owner", "Owner", Channel.OWNER, "+10000000000")
CAREGIVER = Contact("care", "Caregiver", Channel.CAREGIVER, "+10000000001")
EMERGENCY = Contact("monitor", "Monitoring centre", Channel.EMERGENCY, "+10000000002")

_PENDING = (AlertState.PENDING_OWNER, AlertState.PENDING_CAREGIVER)


@dataclass
class EpisodeResult:
    detected: bool
    detect_s: float | None = None
    #: First time any human acknowledged or answered, seconds from the dog's
    #: first alert behaviour.
    first_ack_s: float | None = None
    first_ack_by: str | None = None
    #: (channel, source, time) for every page that was attempted.
    pages: list[tuple[str, str, float]] = field(default_factory=list)
    caregiver_skipped: bool = False
    duplicate_emergency: bool = False
    page_after_owner_response: bool = False
    lost: bool = False
    relay_died_s: float | None = None
    partition: tuple[float, float] | None = None

    def pages_on(self, channel: str) -> list[tuple[str, str, float]]:
        return [p for p in self.pages if p[0] == channel]


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _HumanSide:
    """Decides, once per episode, whether and when each human will answer."""

    def __init__(self, sc: Scenario, rng: random.Random) -> None:
        self.rng = rng
        self.sc = sc
        self.owner_delay = _draw(sc.owner, rng)
        self.care_delay = _draw(sc.caregiver, rng)
        self.emerg_delay = _draw(sc.emergency, rng)
        #: When each human will act, set once their first delivered page lands.
        self.care_at: float | None = None
        self.emerg_at: float | None = None

    def delivered(self) -> bool:
        return self.rng.random() >= self.sc.p_page_lost


def _draw(responder: Responder, rng: random.Random) -> float | None:
    if rng.random() >= responder.p_responds:
        return None
    return rng.lognormvariate(math.log(responder.median_s), responder.sigma)


class _SimNotifier:
    """Routes the engine's pages into the simulated humans."""

    def __init__(self, clock: _Clock, humans: _HumanSide, result: EpisodeResult, offset: float) -> None:
        self.clock = clock
        self.humans = humans
        self.result = result
        self.offset = offset

    def send(self, contact, alert, message) -> bool:  # noqa: ARG002
        return page(contact.channel, "relay", self.clock.now, self.humans, self.result, self.offset)


def page(channel: Channel, source: str, now: float, humans: _HumanSide, result: EpisodeResult, offset: float) -> bool:
    result.pages.append((channel.value, source, now - offset))
    if channel is Channel.OWNER:
        return True  # a local notification on the relay itself
    if not humans.delivered():
        return False
    if channel is Channel.CAREGIVER and humans.care_delay is not None and humans.care_at is None:
        humans.care_at = now + humans.care_delay
    if channel is Channel.EMERGENCY and humans.emerg_delay is not None and humans.emerg_at is None:
        humans.emerg_at = now + humans.emerg_delay
    return True


def simulate_episode(sc: Scenario, rng: random.Random, sequence: int = 0) -> EpisodeResult:
    """Simulate one genuine alert.  Time zero is the dog's first alert."""
    # ---- detection ---------------------------------------------------------
    t_submit = None
    for attempt in range(sc.max_repeats + 1):
        if rng.random() < sc.p_detect:
            t_submit = attempt * sc.repeat_interval_s + rng.choice(sc.latencies_s)
            break
    result = EpisodeResult(detected=t_submit is not None)

    relay_dies = rng.uniform(0.0, sc.fault_window_s) if rng.random() < sc.p_relay_dies else math.inf
    if rng.random() < sc.p_partition:
        start = rng.uniform(0.0, sc.fault_window_s)
        partition = (start, start + rng.expovariate(1.0 / sc.partition_mean_s))
        result.partition = partition
    else:
        partition = (math.inf, math.inf)
    if math.isfinite(relay_dies):
        result.relay_died_s = relay_dies
    if t_submit is None or t_submit >= relay_dies:
        # Never detected, or the phone was already dead when the collar fired:
        # there is no relay to receive it and the backend never hears of it.
        result.lost = result.detected
        if result.detected:
            result.detect_s = t_submit
        return result
    result.detect_s = t_submit

    # ---- the relay ---------------------------------------------------------
    clock = _Clock()
    clock.now = t_submit
    humans = _HumanSide(sc, rng)
    policy = EscalationPolicy(
        owner=OWNER,
        caregivers=(CAREGIVER,),
        emergency=(EMERGENCY,),
        owner_ack_seconds=sc.t1_s,
        caregiver_ack_seconds=sc.t2_s,
    )
    engine = EscalationEngine(policy=policy, notifier=_SimNotifier(clock, humans, result, 0.0), clock=clock)
    detection = DetectionEvent(dog_id="dog", sequence=sequence, device_uptime_ms=int(t_submit * 1000),
                               confidence=0.7, votes=3, window_count=3)
    alert = engine.submit(detection)
    owner_at = None if humans.owner_delay is None else t_submit + humans.owner_delay
    owner_responded_at: float | None = None

    # ---- the backend -------------------------------------------------------
    synced = False
    backend_state: AlertState | None = None
    backend_received = None
    last_hb = None
    last_hb_sent = -math.inf
    next_sweep = sc.watchdog_sweep_s * math.ceil(t_submit / sc.watchdog_sweep_s)
    backend_paged = {Channel.CAREGIVER: False, Channel.EMERGENCY: False}

    def human_ack(t: float, who: str) -> None:
        if result.first_ack_s is None or t < result.first_ack_s:
            result.first_ack_s, result.first_ack_by = t, who

    t = t_submit
    while t <= sc.horizon_s:
        clock.now = t
        relay_up = t < relay_dies
        net_up = relay_up and not (partition[0] <= t < partition[1])

        if relay_up:
            if owner_at is not None and t >= owner_at and owner_responded_at is None:
                owner_responded_at = t
                # A late tap is still a conscious owner; the engine records it
                # without unwinding the escalation.
                engine.acknowledge(alert.alert_id, Channel.OWNER)
                human_ack(t, "owner")
            if humans.care_at is not None and t >= humans.care_at and alert.state.is_open:
                engine.acknowledge(alert.alert_id, Channel.CAREGIVER)
            engine.tick()
        # Humans act whether or not the phone that paged them is still alive.
        if humans.care_at is not None and t >= humans.care_at:
            human_ack(humans.care_at, "caregiver")
        if humans.emerg_at is not None and t >= humans.emerg_at:
            human_ack(humans.emerg_at, "emergency")

        # Relay -> backend: transitions mirrored (queued while offline) and
        # heartbeats every heartbeat_s.
        if net_up:
            if not synced:
                synced, backend_received = True, t
            if backend_state is None or backend_state in _PENDING:
                backend_state = alert.state
            if t - last_hb_sent >= sc.heartbeat_s:
                last_hb_sent = last_hb = t

        # Watchdog sweep.
        if synced and t >= next_sweep:
            next_sweep += sc.watchdog_sweep_s
            if backend_state in _PENDING:
                silent = last_hb is not None and t - last_hb > sc.watchdog_timeout_s
                ceiling = t - backend_received > sc.watchdog_max_open_s
                if sc.watchdog_mode == "direct":
                    if silent or ceiling:
                        page(Channel.EMERGENCY, "backend", t, humans, result, 0.0)
                        backend_state = AlertState.ESCALATED_EMERGENCY
                else:  # ladder
                    raised = alert.raised_at_seconds
                    if ceiling or (silent and backend_state is AlertState.PENDING_CAREGIVER
                                   and t >= raised + sc.t1_s + sc.t2_s):
                        page(Channel.EMERGENCY, "backend", t, humans, result, 0.0)
                        backend_state = AlertState.ESCALATED_EMERGENCY
                    elif silent and backend_state is AlertState.PENDING_OWNER and t >= raised + sc.t1_s:
                        page(Channel.CAREGIVER, "backend", t, humans, result, 0.0)
                        backend_state = AlertState.PENDING_CAREGIVER

        # Stop once nothing further can happen.
        relay_done = (not relay_up) or alert.state.is_terminal
        backend_done = (not synced) or backend_state not in _PENDING
        humans_done = all(x is None or x <= t for x in (humans.care_at, humans.emerg_at))
        if relay_done and backend_done and humans_done:
            break
        t += 1.0

    # ---- outcome classification -------------------------------------------
    emerg = result.pages_on("EMERGENCY")
    care = result.pages_on("CAREGIVER")
    if emerg:
        first_emerg = min(p[2] for p in emerg)
        result.caregiver_skipped = not any(p[2] <= first_emerg for p in care)
    result.duplicate_emergency = len(emerg) > 1
    if owner_responded_at is not None:
        result.page_after_owner_response = any(
            p[0] != "OWNER" and p[2] > owner_responded_at for p in result.pages
        )
    result.lost = result.first_ack_s is None and owner_responded_at is None
    return result


def run_scenario(sc: Scenario, n: int, seed: int = 0) -> list[EpisodeResult]:
    rng = random.Random(seed)
    return [simulate_episode(sc, rng, sequence=i) for i in range(n)]


def summarise(results: list[EpisodeResult], checkpoints=(60, 120, 180, 300, 600)) -> dict:
    n = len(results)
    acked = [r.first_ack_s for r in results if r.first_ack_s is not None]
    by: dict[str, int] = {}
    for r in results:
        key = r.first_ack_by or ("undetected" if not r.detected else "nobody")
        by[key] = by.get(key, 0) + 1
    out = {
        "n": n,
        "p_detected": sum(r.detected for r in results) / n,
        "p_human_within": {str(c): sum(1 for a in acked if a <= c) / n for c in checkpoints},
        "median_time_to_human_s": _quantile(acked, 0.5),
        "p90_time_to_human_s": _quantile(acked, 0.9),
        "first_responder": {k: v / n for k, v in sorted(by.items())},
        "p_caregiver_paged": sum(1 for r in results if r.pages_on("CAREGIVER")) / n,
        "p_emergency_paged": sum(1 for r in results if r.pages_on("EMERGENCY")) / n,
        "p_caregiver_skipped": sum(r.caregiver_skipped for r in results) / n,
        "p_duplicate_emergency": sum(r.duplicate_emergency for r in results) / n,
        "p_page_after_owner_response": sum(r.page_after_owner_response for r in results) / n,
        "p_detected_but_lost": sum(1 for r in results if r.detected and r.lost) / n,
        "time_to_human_s": sorted(acked),
    }
    return out


def _quantile(values, q):
    if not values:
        return None
    values = sorted(values)
    pos = q * (len(values) - 1)
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


# --------------------------------------------------------------------------- #
# false-alarm burden (closed form)
# --------------------------------------------------------------------------- #
def false_alarm_burden(
    false_alarms_per_hour: float,
    t1_s: float,
    t2_s: float,
    hours_awake: float = 16.0,
    hours_asleep: float = 8.0,
    owner_awake: Responder | None = None,
    owner_asleep: Responder | None = None,
    caregiver: Responder | None = None,
    p_page_lost: float = 0.02,
) -> dict:
    """Expected pages per day caused by false alarms alone.

    A false alarm reaches the caregiver only if the owner does not dismiss it
    within T1, and the emergency tier only if the caregiver then does not
    answer within T2.  The owner is assumed to dismiss a false alarm on the
    same response-time distribution as they would acknowledge a real one.
    """
    from .scenario import CAREGIVER as _C, OWNER_ASLEEP as _A, OWNER_AWAKE as _W

    owner_awake = owner_awake or _W
    owner_asleep = owner_asleep or _A
    caregiver = caregiver or _C
    per_day = false_alarms_per_hour * (hours_awake + hours_asleep)
    p_care = (
        hours_awake * (1.0 - owner_awake.cdf(t1_s)) + hours_asleep * (1.0 - owner_asleep.cdf(t1_s))
    ) / (hours_awake + hours_asleep)
    p_care_answers = (1.0 - p_page_lost) * caregiver.cdf(t2_s)
    return {
        "false_alarms_per_day": per_day,
        "p_reaches_caregiver": p_care,
        "caregiver_pages_per_day": per_day * p_care,
        "emergency_pages_per_day": per_day * p_care * (1.0 - p_care_answers),
    }
