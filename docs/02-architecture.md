# Architecture

---

## 1. Three nodes

```
┌──────────────────────────────┐
│  COLLAR — sensing node       │   ESP32-WROOM-32 + MPU6050
│                              │
│  sample 51.2 Hz ─┐           │   Core 0: hardware-timer sampling only
│                  ▼           │   Core 1: everything else
│  ring buffer (200 samples)   │
│         │                    │
│         ▼ every 1.3 s        │
│  133-sample window           │
│         │                    │
│         ▼                    │
│  159 features → 20 selected  │   ca_features.c
│         │                    │
│         ▼                    │
│  32-tree random forest       │   ca_forest.c, 39 KiB flash
│         │  p(spin)           │
│         ▼                    │
│  2-of-4 verification gate    │   ca_verify.c
│         │  + 60 s refractory │
└─────────┼────────────────────┘
          │  BLE GATT notify, retransmitted until acked
          ▼
┌──────────────────────────────┐
│  RELAY — owner's phone       │
│                              │
│  T1 = 60 s  owner ack window │   escalation/engine.py
│  T2 = 120 s caregiver window │
│  SMS / push · GPS fix        │
│  15 s heartbeat ─────────────┼──┐
└─────────┬────────────────────┘  │
          │  HTTPS, best-effort   │
          ▼                       ▼
┌──────────────────────────────────────┐
│  BACKEND — Jakarta EE / MicroProfile │
│                                      │
│  audit log · relay watchdog          │
│  caregiver dashboard                 │
└──────────────────────────────────────┘
```

---

## 2. The load-bearing decision: the ladder runs on the phone

**The escalation state machine lives on the owner's handset, not in the cloud.**

The alert matters most in exactly the conditions where connectivity is worst — at
home at night, in a rural area, in a basement. A cloud-arbitrated escalation adds
a network dependency to a safety path that does not need one: the owner's
acknowledgement is a local interaction (a tap on a phone that is already in the
room) and the caregiver page goes out over SMS, which does not need data.

The cost is that the phone becomes a single point of failure. If it dies
mid-alert, the ladder stops and nobody is paged — the exact silent failure the
project exists to prevent. That hole is closed by the backend watchdog
([04-escalation-protocol.md §5](04-escalation-protocol.md#5-the-watchdog-when-the-phone-itself-dies)),
which escalates when a relay stops heartbeating with an alert open. The two are
**redundant, not sequential**: normal operation needs neither the backend nor the
network.

A cloud-first design would trade this network dependency for a hardware one. That
is a legitimate alternative; we chose against it because a dead phone is a
visible, recoverable failure and a dead network in a rural bedroom at 3am is not.

---

## 3. Why detection is on the collar, not the phone

The collar could stream raw IMU to the phone and let it classify. It does not,
for three reasons:

1. **Power.** Streaming 6 channels at 51.2 Hz over BLE continuously costs far
   more than transmitting one 180-byte packet per alert. The collar's job is to
   be worn all day.
2. **The BLE link is not always up.** A dog in the garden while the phone is
   indoors is out of range. On-collar detection means the alert is *raised*
   regardless; the collar retransmits until the phone acknowledges, and logs to
   SD if it never does.
3. **The classifier is small.** 20 features and a 39 KiB forest — the whole model
   fits in flash with room to spare, and inference is a few thousand comparisons.
   There is nothing to gain by moving it.

---

## 4. Why the verification gate is on the collar too

A single 2.6 s window that the classifier calls 'spin' is not an alert.

The source paper demonstrates why: at segment level under cross-subject
validation the model misses 28% of spin windows, and it recovers usable
performance only by aggregating predictions across a longer span. The paper does
that aggregation *offline*, as an analysis step.

We make it an explicit streaming policy on the device, because the escalation
layer downstream needs **a single well-defined moment at which an alert exists**.
"The model was mostly positive over the last eight seconds" is not something a
state machine can start a timer on.

Putting it on the collar rather than the phone also means the phone never sees a
detection that did not pass verification — so a flapping classifier cannot become
a flapping notification.

---

## 5. Data flow, and what each hop guarantees

| Hop | Transport | Guarantee | Failure behaviour |
|---|---|---|---|
| IMU → ring buffer | I²C, 400 kHz | Uniform 51.2 Hz from a hardware timer on a dedicated core | Failed reads counted and logged; a sustained failure is reported |
| Ring → window | In-memory | Tear-free: a window overwritten mid-copy is rejected, not spliced | Skipped; the next stride brings another |
| Collar → relay | BLE GATT notify | At-least-once. Retransmitted every 3 s, up to 10 times, until the phone writes back `ACK:<id>` | After 10 attempts: red LED stays lit, `relay_unreachable` logged to SD |
| Relay → backend | HTTPS POST | Best-effort. Bounded queue (500), replayed in order on reconnect | **Never blocks a page.** A 4xx is dropped rather than retried forever |
| Backend → emergency | SMS/push | Watchdog path only | Attempt recorded whether or not it succeeds |

The BLE link is at-least-once, not exactly-once, which is why the alert id is
derived from the episode rather than from arrival time
([04-escalation-protocol.md §4.2](04-escalation-protocol.md#42-idempotent-ingestion)).

---

## 6. Concurrency on the collar

Two cores, deliberately asymmetric:

- **Core 0** does nothing but service a hardware timer and read the IMU. Nothing
  else is pinned there.
- **Core 1** runs feature extraction, inference, BLE and SD.

The reason is the frequency features. `dom_freq`, `spec_centroid` and friends all
assume a uniform sample interval; jitter in the sampling loop distorts them
directly. Feature extraction includes eight 133-point DFTs, which is the most
expensive thing the collar does — so it is kept off the core that must not be
late.

The ring buffer between them is single-producer/single-consumer with no lock. The
producer publishes a sample only after writing it, and the consumer re-checks the
write index after copying a window: if the producer wrapped past the region
mid-copy, the window is reported torn and discarded rather than returned spliced.
Dropping one window costs 1.3 s of latency; a spliced window would feed the
classifier a discontinuity that looks like a spike.

---

## 7. Software layering

```
escalation/           pure domain logic — no I/O, no clock, no network
   ├── model.py       types shared by relay, backend and dashboard
   ├── engine.py      the state machine
   └── notify.py      Notifier protocol + retry/fan-out wrappers
        ▲
        │ used by
        │
gateway/              the relay: transports, config, backend client
tools/devserver.py    dev stand-in for the Java backend
backend/              production backend (Jakarta EE)
```

`escalation/` takes its clock and its notifier as constructor arguments and
performs no I/O of its own. That is what makes a three-minute escalation testable
in microseconds, and what lets the same logic run under a BLE relay, a replay
harness, or a test double without modification.

The Java backend mirrors `escalation/model.py` field for field. The two are kept
in step by the shared REST contract in [06-api.md](06-api.md) and by the fact
that both are exercised by the same dashboard.

---

## 8. Two backend implementations

| | `backend/` | `tools/devserver.py` |
|---|---|---|
| Stack | Jakarta EE 10 + MicroProfile, Open Liberty | Python standard library |
| Storage | In-memory (see [09-limitations.md](09-limitations.md)) | Append-only JSONL |
| Needs | Maven, a container | Python |
| Role | Production, and the course's stack | Demos, CI, integration tests |

They implement the **same REST contract**. Anything one does that the other does
not is a bug in one of them. The dev server exists so the relay, dashboard and
replay harness can be exercised on any machine with Python and nothing else — the
Java backend was not buildable in this environment.

---

## 9. Module mapping

| Course module | Component |
|---|---|
| M2 — BLE, building blocks | `firmware/collar/collar.ino` GATT service; `gateway/relay.py` BLE central |
| M3 — BSN architecture | This document; collar + phone as a two-node body sensor network |
| M5 — Cloud-assisted BSN | `backend/`, `dashboard/`, the relay watchdog |
| M6 — SPINE-style activity recognition | `ml/canine_alert/` — windowing, features, classification, multi-stage validation |
