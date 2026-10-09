# The escalation protocol

The contribution of this project. Reference implementation:
`escalation/engine.py`. Mirrored in Java by `backend/.../EscalationWatchdog.java`.
Specified by `escalation/tests/test_engine.py` — 39 tests, each named after a
real failure mode.

---

## 1. The problem

A trained seizure-alert dog performs a specific signal — here, two rapid
clockwise spins — when it senses an oncoming seizure. That signal is only useful
if a human perceives it.

The situation the dog is trained for is one in which the owner may be about to
lose consciousness, may be asleep, or may already be seizing. The failure mode is
therefore not "the dog did not alert" but **"the dog alerted and no one was
there"** — and no amount of improvement to the detector addresses it.

Brady et al. detect the behaviour and stop. Their discussion names transmitting
alerts "to owners, caregivers or emergency services" as future work. This
document specifies that layer.

---

## 2. Time

**Every deadline is evaluated against a monotonic clock**, injected at
construction, never `time.time()`.

Two reasons, both load-bearing:

1. **A wall clock can jump.** NTP correction, a timezone change, or the user
   editing the date can move it backwards or forwards mid-alert. Against a wall
   clock that jumps forward, an escalation fires early; backwards, it may never
   fire at all. Neither is acceptable in a safety path.
2. **Testability.** The entire ladder — including a three-minute escalation — is
   exercised in microseconds by advancing a fake clock. Timing logic that can
   only be tested by waiting does not get tested.

Consequence: `raised_at_seconds` has **no epoch**. It is not a timestamp and must
not be rendered as one. The backend stores a separate wall-clock `received_at`
for retention and cross-relay ordering. The two are never subtracted from each
other. The dashboard renders monotonic times as `t+NNN s`.

Time advances only when something calls `tick()`. The engine has no background
thread and takes no locks — the relay drives it at 1 Hz, the backend at 5 s
intervals, and neither needs to be precise. A state machine that fires timers
from a thread you do not control is one you cannot reason about during an
incident review.

---

## 3. The state machine

```
                        collar verification gate fires
                                     │
                                     ▼
                          ┌────────────────────┐
       owner acks         │   PENDING_OWNER    │      owner dismisses
     ┌────────────────────┤   deadline: T1     ├────────────────────┐
     │                    └─────────┬──────────┘                    │
     │                              │ T1 elapses                    │
     │                              │ → page caregiver              │
     │                              ▼                               │
     │                    ┌────────────────────┐                    │
     │   owner or         │ PENDING_CAREGIVER  │                    │
     │   caregiver acks   │   deadline: T2     │                    │
     │  ┌─────────────────┤                    │                    │
     │  │                 └─────────┬──────────┘                    │
     │  │                           │ T2 elapses                    │
     ▼  ▼                           │ → page emergency              ▼
┌──────────────────────┐            ▼                  ┌──────────────────────────┐
│ ACKNOWLEDGED_BY_     │  ┌──────────────────────┐     │ DISMISSED_FALSE_POSITIVE │
│ OWNER / CAREGIVER    │  │ ESCALATED_EMERGENCY  │     └──────────────────────────┘
└──────────────────────┘  └──────────────────────┘
```

`CANCELLED` is reachable from `PENDING_OWNER` only, and only while no one beyond
the owner has been paged.

### 3.1 Timers

| Timer | Default | Meaning |
|---|---|---|
| **T1** `owner_ack_seconds` | 60 s | How long the owner has to respond before the caregiver is paged |
| **T2** `caregiver_ack_seconds` | 120 s | How long the caregiver has before the emergency contact is paged |
| Relay heartbeat | 15 s | Liveness report to the backend |
| Watchdog tolerance | 60 s | Silence after which the backend escalates on the relay's behalf |
| Alert ceiling | 600 s | No alert may stay open longer, whatever the reason |

**T1 is the safety-critical value and is deliberately per-owner configurable.**
Too short and the owner is paged while they are simply in another room; too long
and a genuine emergency waits. 60 s is a starting point, not a recommendation —
the right value depends on the person's seizure profile and living arrangement,
and should be set with them and their clinician.

### 3.2 Why the terminal states are distinct

Not one `CLOSED` state, but five. A caregiver reviewing the log needs to see
*who* closed each alert. "The owner said they were fine" and "nobody answered and
we called the emergency contact" are the two outcomes the whole system exists to
distinguish.

`DISMISSED_FALSE_POSITIVE` is kept separate from `ACKNOWLEDGED_BY_OWNER` for the
same reason: a dismissal is training-quality data (the collar or the dog got it
wrong), an acknowledgement means the alert was real and handled. Conflating them
would make the false-positive trend — one of the system's stated secondary
contributions — meaningless.

---

## 4. Guarantees

Each is enforced by a named test.

### 4.1 At-most-once paging per channel

A channel already notified is never notified again — not on a repeated `tick()`,
not on a duplicate detection, not after a restart that replays the log. A
caregiver paged twice for one episode learns to ignore the app.

> `test_repeated_ticks_do_not_repage`

### 4.2 Idempotent ingestion

An alert's id is a hash of `(dog_id, sequence, device_uptime_ms)` — derived from
the *episode*, not from arrival time. BLE notifications are not de-duplicated by
the link layer and the collar retransmits until acknowledged, so the same packet
arrives repeatedly. Every delivery maps to the same alert.

Deliberately excluded from the hash: `confidence`, `votes`, `window_count`. A
retransmission could round a float differently; identity must not depend on that.

> `test_duplicate_detections_do_not_open_a_second_alert`,
> `test_alert_id_ignores_fields_that_may_differ_between_retransmits`

### 4.3 Failure escalates, it does not stall

If the caregiver cannot be reached at all — carrier down, wrong number, phone off
— the alert does **not** sit in `PENDING_CAREGIVER` waiting for an
acknowledgement that can never arrive. T2 still runs and the emergency contact is
still paged.

Likewise, an engine with no caregiver configured escalates straight to the
emergency contact rather than parking in a state that has no exit; and one with
no emergency contact closes the alert with an explicit "escalation exhausted"
reason rather than implying help is on the way.

> `test_unreachable_caregiver_still_escalates`,
> `test_missing_caregiver_escalates_straight_to_emergency`,
> `test_no_emergency_contact_closes_honestly`

### 4.4 A late acknowledgement does not unring the bell

Once a caregiver has been paged, a late tap from the owner cannot rewrite
history. The acknowledgement is *recorded* — the audit trail must show the owner
eventually replied — but the escalation stands. The caregiver's phone already
rang; the episode is part of their day.

> `test_late_owner_acknowledgement_does_not_unring_the_bell`

### 4.5 Nothing in the periphery can break the ladder

A notifier that raises, a persistence hook that throws, a backend that is down:
all are caught, logged, and the escalation continues. Losing a log line is
survivable; losing a page is not.

> `test_a_raising_notifier_does_not_abort_the_escalation`,
> `test_a_failing_persistence_hook_does_not_abort_the_escalation`

### 4.6 Stale locations are dropped, not sent

A GPS fix older than `max_location_age_seconds` (default 300 s) is discarded and
the message says "No recent location fix is available."

A coordinate reads as authoritative. Sending a responder to where the owner was
an hour ago is worse than sending them no position at all, because they will act
on it.

> `test_stale_location_is_dropped_rather_than_sent`

---

## 5. The watchdog: when the phone itself dies

The ladder runs on the owner's phone. That is the right place for it — the alert
matters most where connectivity is worst, and a cloud-arbitrated escalation would
add a network dependency to a path that does not need one.

It has one hole. **If the phone dies while an alert is open, the ladder stops.**
The dog signalled, the owner did not respond, and the system quietly does
nothing.

The backend closes it. While any alert is open the relay heartbeats every 15 s.
If heartbeats stop for longer than the tolerance *and* an alert is still open,
the backend escalates directly to the emergency contact and marks the alert
`escalated_by_watchdog`.

The watchdog **errs towards escalating**. A spurious escalation caused by a
dropped network costs a caregiver a phone call; a missed one costs considerably
more. The flag lets a caregiver see the page came from the backend rather than
from a confirmed non-response, and lets the rate be monitored — a high rate means
the relay's connectivity needs fixing, not that the owner is unresponsive.

Two independent triggers:

| Trigger | Condition |
|---|---|
| Relay silent | No heartbeat for `relay.timeout.seconds` (60 s) while an alert is open |
| Ceiling exceeded | Alert open longer than `alert.max.open.seconds` (600 s), regardless of heartbeats |

The second covers a relay that is alive and heartbeating but has somehow stalled.

### 5.1 What model checking found (see `formal/` and the paper)

The TLA⁺ model in `formal/Escalation.tla` checks this design under arbitrary
phone deaths and network partitions. The watchdog as built:

- **skips the caregiver tier.** A phone that dies shortly after mirroring an
  alert gets the emergency contact paged at about 75 s, and the caregiver is
  never paged. A partition does the same while the relay is alive, and the
  relay then pages the emergency contact a second time.
- **can page after an acknowledgement.** If the owner acknowledges and the phone
  dies before that reaches the backend, the watchdog still escalates. This is
  the designed "err towards escalating" behaviour, now with its cost stated.
- **cannot prevent silent loss.** If the network is down when the gate fires
  and the phone dies before reconnecting, the backend never hears of the alert.
  Only a second path from the collar can fix this.

The proposed **ladder-aware watchdog** continues the ladder on the relay's
behalf instead of jumping to the emergency contact. It pages the caregiver once
T1 has elapsed and the emergency contact once T1 + T2 has elapsed, both measured
from the alert. It is verified never to skip the caregiver tier. It is not yet
implemented in `EscalationWatchdog.java`.

Writing the model also exposed a real bug: the relay heartbeated with the
owner's contact id while the watchdog matched heartbeats by dog id, so the
watchdog never saw a heartbeat. This is fixed in `gateway/relay.py`, and
`gateway/tests/test_relay.py` is the regression test.

> `backend/src/test/java/.../EscalationWatchdogTest.java` — 9 tests

---

## 6. What the backend deliberately cannot do

There is **no** endpoint to acknowledge, escalate or resolve an alert. The relay
owns the ladder; the backend records what happened.

Adding a "resolve this alert" endpoint would create a second authority over the
same state machine and a race between them — one where the losing writer is a
page that does or does not go out. The watchdog is the single exception, and it
only ever moves an alert *forwards* into a terminal state.

---

## 7. Configuration

`gateway/relay_config.json` (see `relay_config.example.json`). Gitignored: it
holds the real phone numbers of the people who get paged.

```json
{
  "dog_id": "stuart",
  "min_confidence": 0.45,
  "owner":      { "id": "owner-1", "name": "Alex",  "address": "+353850000001" },
  "caregivers": [{ "id": "care-1",  "name": "Sam",   "address": "+353850000002" }],
  "emergency":  [{ "id": "emerg-1", "name": "Emergency Services", "address": "112" }],
  "timing": {
    "owner_ack_seconds": 60,
    "caregiver_ack_seconds": 120,
    "max_location_age_seconds": 300
  }
}
```

`min_confidence` gates which detections open an alert at all. Detections below it
are logged for the training record but page no one — useful for tightening the
system without changing the on-collar model.

---

## 8. Deployment caveats

Two things in this specification are **not** production-ready and are recorded
here rather than discovered later:

- **The notification transport is a console printer.** `ConsoleNotifier` prints;
  a real deployment needs an SMS gateway with delivery receipts, and the retry
  policy in `RetryingNotifier` has never been exercised against a real carrier.
- **The emergency channel should not dial emergency services directly.** The
  `112` in the example configuration is illustrative. Automated calls to
  emergency services are regulated, generate false-dispatch liability, and in
  most jurisdictions require an accredited monitoring provider in between. The
  emergency channel should point at a named human or a monitoring service.

See [09-limitations.md](09-limitations.md).
