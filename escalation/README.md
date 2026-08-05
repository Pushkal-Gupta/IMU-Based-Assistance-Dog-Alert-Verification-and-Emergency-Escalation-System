# `escalation` — the escalation state machine

The project's core contribution: what happens after a seizure-alert dog signals,
if the owner cannot respond.

Pure domain logic. No I/O, no network, no ambient clock — the clock and the
notifier are constructor arguments. That is what lets a three-minute escalation
ladder be tested in microseconds, and what lets the same code run under a BLE
relay, a replay harness, or a test double unchanged.

## Modules

| Module | Contains |
|---|---|
| `model.py` | `Alert`, `AlertState`, `DetectionEvent`, `Location`, `Contact` — the types shared by relay, backend and dashboard |
| `engine.py` | `EscalationEngine`, `EscalationPolicy` — the state machine |
| `notify.py` | `Notifier` protocol, plus retry and fan-out wrappers |

## Use

```python
from escalation import *
import time

policy = EscalationPolicy(
    owner=Contact("owner-1", "Alex", Channel.OWNER, "+353850000001"),
    caregivers=(Contact("care-1", "Sam", Channel.CAREGIVER, "+353850000002"),),
    emergency=(Contact("emerg-1", "Emergency Services", Channel.EMERGENCY, "112"),),
    owner_name="Alex",
    owner_ack_seconds=60.0,
    caregiver_ack_seconds=120.0,
)

engine = EscalationEngine(policy, ConsoleNotifier(), clock=time.monotonic)

alert = engine.submit(
    DetectionEvent("stuart", sequence=1, device_uptime_ms=123456,
                   confidence=0.82, votes=2, window_count=4),
    Location(53.3862, -6.2568, accuracy_m=8.0, age_seconds=12.0),
)

engine.tick()                                   # drive from your own loop
engine.acknowledge(alert.alert_id, Channel.OWNER)
```

## Tests

```bash
python -m pytest escalation/tests -q     # 63 tests
```

Each is named after a real failure mode: `test_late_owner_acknowledgement_does_not_unring_the_bell`,
`test_unreachable_caregiver_still_escalates`,
`test_duplicate_detections_do_not_open_a_second_alert`,
`test_stale_location_is_dropped_rather_than_sent`.

The suite **is** the specification — `backend/`'s Java mirrors these transitions,
and [../docs/04-escalation-protocol.md](../docs/04-escalation-protocol.md) is
written from them.
