"""Monte-Carlo discrete-event simulation of whole alert episodes.

The unit tests prove that each transition is right and the TLA+ model proves
which properties hold under every interleaving.  Neither says how *likely* a
good or bad outcome is.  This package answers that: it samples the dog, the
detector, the owner, the caregiver, the network and the phone from explicit,
documented distributions and runs each episode through the real
:class:`~escalation.engine.EscalationEngine`, with a port of the backend
watchdog alongside it.

Every behavioural parameter is an *assumption*, not a measurement; the
parameters live in :mod:`escalation.sim.scenario` with the reason for each
value, and the report shows how results move when they move.
"""

from .scenario import Scenario, SCENARIOS
from .simulate import EpisodeResult, simulate_episode, run_scenario, false_alarm_burden

__all__ = [
    "EpisodeResult",
    "SCENARIOS",
    "Scenario",
    "false_alarm_burden",
    "run_scenario",
    "simulate_episode",
]
