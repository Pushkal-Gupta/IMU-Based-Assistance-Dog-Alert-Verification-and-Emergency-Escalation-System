"""Simulation parameters, each with the reason for its value.

None of the human-behaviour numbers below is a measurement of this system's
users -- there are no users.  They are deliberately round, deliberately
documented assumptions, chosen to bracket plausible behaviour, and
``ml``-derived detector parameters are overwritten at run time from the
measured artifacts.  The paper reports a sensitivity analysis over the
assumptions that drive the conclusions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class Responder:
    """A human who may answer a page.

    ``p_responds`` is the probability they respond at all within the horizon;
    if they do, the delay from the page is log-normal with the given median
    and log-scale spread (a right-skewed delay is the usual shape for human
    reaction to a phone alert: most people are quick, a few are very slow).
    """

    p_responds: float
    median_s: float
    sigma: float = 0.8

    def cdf(self, t: float) -> float:
        """P(responded within ``t`` seconds of the page)."""
        if t <= 0 or self.p_responds <= 0:
            return 0.0
        z = (math.log(t) - math.log(self.median_s)) / (self.sigma * math.sqrt(2.0))
        return self.p_responds * 0.5 * (1.0 + math.erf(z))


#: Owner states.  "awake": a phone alert with sound and vibration is usually
#: answered within tens of seconds.  "asleep": many people sleep through a
#: single alert -- we assume 60% wake and answer, more slowly.
#: "incapacitated": the scenario the system exists for -- the owner is
#: seizing or post-ictal and does not respond at all.
OWNER_AWAKE = Responder(p_responds=0.95, median_s=15.0)
OWNER_ASLEEP = Responder(p_responds=0.60, median_s=40.0)
OWNER_INCAPACITATED = Responder(p_responds=0.0, median_s=1.0)

#: A caregiver is a person with their own life: assume 80% are reachable and
#: willing to act at any given moment, answering in about 45 s when they are.
CAREGIVER = Responder(p_responds=0.80, median_s=45.0)

#: The emergency tier should be an accredited monitoring provider, not a
#: direct emergency-services dial (docs/04-escalation-protocol.md §8); such
#: services answer almost always and quickly.
EMERGENCY = Responder(p_responds=0.99, median_s=30.0, sigma=0.5)


@dataclass(frozen=True)
class Scenario:
    name: str
    owner: Responder = OWNER_INCAPACITATED

    # --- detector (overwritten from ml/artifacts/research.json) ------------
    #: Probability one performance of the alert behaviour is detected.
    p_detect: float = 0.64
    #: Detection latency samples, seconds from the dog starting to spin.
    latencies_s: tuple[float, ...] = (4.0,)
    #: A trained dog that is not acknowledged repeats its signal.  Zero by
    #: default: the dataset does not show it, so the conservative case is that
    #: one missed alert is the only alert.
    max_repeats: int = 0
    repeat_interval_s: float = 30.0

    # --- humans ------------------------------------------------------------
    caregiver: Responder = CAREGIVER
    emergency: Responder = EMERGENCY
    #: Per-contact probability that a page is not delivered (SMS/push loss,
    #: phone off).  Applied independently to each page.
    p_page_lost: float = 0.02

    # --- ladder ------------------------------------------------------------
    t1_s: float = 60.0
    t2_s: float = 120.0

    # --- infrastructure ----------------------------------------------------
    #: Probability the relay phone dies during the episode (battery, crash).
    p_relay_dies: float = 0.0
    #: Probability the relay loses its data connection during the episode.
    p_partition: float = 0.0
    partition_mean_s: float = 120.0
    heartbeat_s: float = 15.0
    watchdog_timeout_s: float = 60.0
    watchdog_sweep_s: float = 5.0
    watchdog_max_open_s: float = 600.0
    #: "direct" is the watchdog as built; "ladder" is the proposed variant that
    #: continues the ladder on the relay's behalf (formal/Escalation.tla).
    watchdog_mode: str = "direct"
    #: Window in which faults are drawn, seconds after the dog first alerts.
    fault_window_s: float = 240.0

    horizon_s: float = 900.0

    def with_(self, **changes) -> "Scenario":
        return replace(self, **changes)


SCENARIOS: dict[str, Scenario] = {
    "owner_awake": Scenario("owner_awake", owner=OWNER_AWAKE),
    "owner_asleep": Scenario("owner_asleep", owner=OWNER_ASLEEP),
    "owner_incapacitated": Scenario("owner_incapacitated", owner=OWNER_INCAPACITATED),
    "incapacitated_dog_repeats": Scenario(
        "incapacitated_dog_repeats", owner=OWNER_INCAPACITATED, max_repeats=3
    ),
    # Stress tests: faults far more frequent than real handsets, to exercise
    # the backend path enough to measure it.
    "incapacitated_relay_dies": Scenario(
        "incapacitated_relay_dies", owner=OWNER_INCAPACITATED, p_relay_dies=1.0
    ),
    "incapacitated_partition": Scenario(
        "incapacitated_partition", owner=OWNER_INCAPACITATED, p_partition=1.0
    ),
    "awake_partition": Scenario("awake_partition", owner=OWNER_AWAKE, p_partition=1.0),
    "awake_relay_dies": Scenario("awake_relay_dies", owner=OWNER_AWAKE, p_relay_dies=1.0),
}
