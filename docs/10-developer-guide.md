# Developer guide

Everything you need to run, understand, modify and extend this system.

---

## Contents

1. [Quick start](#1-quick-start)
2. [What you get, and why it is built this way](#2-what-you-get-and-why-it-is-built-this-way)
3. [Environment and dependencies](#3-environment-and-dependencies)
4. [Repository tour](#4-repository-tour)
5. [The generated-file chain](#5-the-generated-file-chain)
6. [Using `escalation` as a library](#6-using-escalation-as-a-library)
7. [Recipes](#7-recipes)
8. [Extension points](#8-extension-points)
9. [Testing](#9-testing)
10. [Debugging and troubleshooting](#10-debugging-and-troubleshooting)
11. [Performance characteristics](#11-performance-characteristics)
12. [Invariants you must not break](#12-invariants-you-must-not-break)
13. [Code conventions](#13-code-conventions)

---

## 1. Quick start

```bash
git clone <repo> && cd <repo>
pip install -r requirements.txt

# Fetch the dataset (78 .pkl files) into spinning_dataset/
# https://doi.org/10.6084/m9.figshare.30022441

make artifacts      # ~30 s: train, evaluate, export the model, build figures
make test           # 90 + 63 Python tests, 240 firmware checks
```

Three things to run next, in increasing order of "shows the whole system":

```bash
# One classifier evaluation, printed
python ml/scripts/run_experiments.py

# A real recording escalating end to end because nobody answered
python gateway/replay.py --scenario asleep

# The caregiver dashboard with a seeded history
make demo && open http://localhost:8080/
```

`make help` lists every target.

---

## 2. What you get, and why it is built this way

The architectural choices are documented in
[02-architecture.md](02-architecture.md). This section covers what they buy *you*,
as someone working on the code.

### 2.1 The escalation engine has no I/O

`escalation/` takes its clock and its notifier as constructor arguments and
performs no I/O of its own.

**What this buys you.** The full escalation ladder — a three-minute sequence with
two timers — is exercised in **microseconds**. The 63-test suite runs in 0.02 s.
You can write a test for "the owner acknowledges 95 seconds in, after the
caregiver was already paged" and it costs nothing.

```python
clock = FakeClock()
engine.submit(detection)
clock.advance(60.0); engine.tick()      # caregiver paged
clock.advance(120.0); engine.tick()     # emergency paged
```

Timing logic that can only be tested by waiting does not get tested. That is the
whole argument.

### 2.2 The firmware's core has no Arduino dependency

`ca_features.c`, `ca_forest.c`, `ca_verify.c` and `ca_ring.c` include only
`<math.h>`, `<string.h>` and `<stdint.h>`.

**What this buys you.** You can compile the collar's actual signal-processing
code on your laptop and check it numerically against the Python it must match:

```bash
make -C firmware/test run     # 240 checks against 64 real dataset windows
```

Without this, "the C computes the same features as the Python" would be an
assumption. It is instead a measurement — and it caught a real float32 precision
defect in the variance calculation that would otherwise have shipped silently
([07-evaluation.md §7](07-evaluation.md#7-on-device-parity)).

### 2.3 Config lives in one place

Every tunable that appears in the documentation is in
`ml/canine_alert/config.py`. Window sizes, thresholds, the K-of-N policy, the
escalation timers.

**What this buys you.** Docs and code cannot drift. Change
`window_seconds` and the window length, the event length, the firmware header and
the figures all follow from one edit.

### 2.4 Nothing in the docs is typed by hand

Every number in the documentation traces to `ml/artifacts/results.json` or
`firmware_export.json`.

**What this buys you.** `make artifacts` regenerates everything, and a changed
result shows up in the report rather than quietly disagreeing with it.

### 2.5 The safety path has zero third-party dependencies

`escalation/`, `gateway/` and `tools/` use only the Python standard library.

**What this buys you.** The relay runs on a handset with nothing installed, there
is no supply chain in the code path that pages an emergency contact, and the
system does not break when a library changes its API.

### 2.6 Two backends, one contract

`backend/` (Jakarta EE) and `tools/devserver.py` (stdlib) implement the same REST
contract.

**What this buys you.** Demos, CI and integration tests need only Python. The
production backend is a separate concern you can build when you have a container.

---

## 3. Environment and dependencies

| Requirement | Version | Needed for |
|---|---|---|
| Python | ≥ 3.10 | everything |
| NumPy, pandas, scikit-learn, SciPy | see `requirements.txt` | detection layer only |
| matplotlib | ≥ 3.7 | figures only |
| A C99 compiler | any | firmware host tests |
| Maven + JDK 17 | optional | building `backend/` |
| Arduino IDE 2.3.x + esp32 core 2.0.x | optional | flashing a collar |
| `bleak` | optional | `relay.py --source ble` |

Python ≥ 3.10 is required for the `X | None` type syntax used throughout.

### 3.1 The NumPy 2 pickle shim

The published dataset was pickled with NumPy 2.x, whose array reconstructors live
in `numpy._core`. Under NumPy 1.x, `dataset.py` aliases the module names so the
pickles load. No array data is reinterpreted.

Note that NumPy 1.26 ships a *stub* `numpy._core` with no submodules, so probing
for the parent package is not a sufficient version test — the shim probes for
`numpy._core.numeric` specifically. If you see
`ModuleNotFoundError: No module named 'numpy._core.numeric'`, that check has been
broken.

### 3.2 The dataset

Not vendored. Download the figshare package and unpack to `spinning_dataset/`:

```
spinning_dataset/
├── 1st_A22C/Shimmer_A22C-004-1.pkl
├── 2nd_0098/...
└── 3rd_A22C/...
```

Tests that need it skip cleanly when it is absent, so `pytest` still runs on a
fresh clone.

---

## 4. Repository tour

```
ml/canine_alert/          the detection layer
  config.py               every tunable, in one place
  dataset.py              pickle loading, event curation, the NumPy shim
  segmentation.py         2.6 s windows, 1.3 s stride
  features.py             159 features — the reference the C must match
  selection.py            variance → collinearity → ANOVA, fitted per fold
  models.py               4 classifiers + heuristic baseline + embedded variant
  verification.py         the K-of-N gate
  evaluate.py             within-subject / LOGO / event-level protocols
  export.py               forest → C transpiler
  plotting.py             shared figure style

escalation/               the state machine — no I/O, no clock, no network
  model.py                Alert, AlertState, DetectionEvent, Location, Contact
  engine.py               EscalationEngine, EscalationPolicy
  notify.py               Notifier protocol + retry/fan-out wrappers

firmware/collar/
  collar.ino              hardware glue only: sampling, BLE, LEDs, SD
  src/ca_*.{c,h}          portable C — compiles and runs on a host
  src/model.h             GENERATED. Never edit

gateway/
  relay.py                the phone: BLE/stdin transport, config, heartbeats
  replay.py               end-to-end harness on real data
  backend_client.py       best-effort HTTP with a bounded offline queue

backend/                  Jakarta EE 10 + MicroProfile (needs Maven)
tools/devserver.py        stdlib stand-in for the above
dashboard/index.html      caregiver alert history, no build step
```

### 4.1 Reading order for a newcomer

1. `gateway/replay.py` — the whole system in one file, top to bottom.
2. `escalation/engine.py` — the contribution.
3. `escalation/tests/test_engine.py` — the specification, in test names.
4. `ml/canine_alert/verification.py` — the bridge between detection and escalation.
5. `firmware/collar/src/ca_verify.c` — the same logic in C.

---

## 5. The generated-file chain

Four files are generated, and **order matters**. `make artifacts` gets it right;
doing it by hand in the wrong order produces firmware that disagrees with the
evaluation.

```
run_experiments.py ─────▶ ml/artifacts/results.json
                                │  (contains the selected operating point)
                                ▼
export_firmware_model.py ─▶ firmware/collar/src/model.h
                                   forest tables + the K-of-N policy

make_firmware_vectors.py ─▶ firmware/test/vectors.bin     (golden I/O)
make_figures.py ──────────▶ docs/figures/*.png
```

The exporter reads the operating point back from `results.json`, so the firmware
always ships the configuration the evaluation actually selected — you cannot
hand-copy a stale constant into the header.

It also refuses to write the header if the transpiled forest disagrees with
scikit-learn by more than `1e-6` on the whole dataset.

Committed on purpose: `docs/figures/`, `ml/artifacts/*.json`, `model.h` (so the
firmware builds without a Python toolchain). Not committed: `*.joblib`,
`vectors.bin`.

---

## 6. Using `escalation` as a library

The package is usable on its own, independent of the dog, the collar and the
detection layer. Anything that can produce a `DetectionEvent` can drive it.

```python
import time
from escalation import (
    Channel, Contact, DetectionEvent, EscalationEngine,
    EscalationPolicy, Location, ConsoleNotifier,
)

policy = EscalationPolicy(
    owner=Contact("owner-1", "Alex", Channel.OWNER, "+353850000001"),
    caregivers=(Contact("care-1", "Sam", Channel.CAREGIVER, "+353850000002"),),
    emergency=(Contact("emerg-1", "Monitoring Centre", Channel.EMERGENCY, "+353850000003"),),
    owner_name="Alex",
    owner_ack_seconds=60.0,
    caregiver_ack_seconds=120.0,
    min_confidence=0.45,
)

engine = EscalationEngine(
    policy=policy,
    notifier=ConsoleNotifier(),
    clock=time.monotonic,
    on_transition=lambda alert: print(alert.state),
)

alert = engine.submit(
    DetectionEvent("stuart", sequence=1, device_uptime_ms=123_456,
                   confidence=0.82, votes=2, window_count=4),
    Location(53.3862, -6.2568, accuracy_m=8.0, age_seconds=12.0),
)

while engine.open_alerts():          # drive from your own loop
    engine.tick()
    time.sleep(1)
```

### 6.1 The API

| Call | Effect |
|---|---|
| `submit(detection, location)` | Opens an alert and pages the owner. Returns `None` if suppressed below `min_confidence`; returns the existing alert on a duplicate |
| `tick()` | Advances every open alert whose deadline has passed. Returns those that changed |
| `acknowledge(alert_id, by)` | Records a human response. Late responses are recorded but do not roll back an escalation |
| `dismiss(alert_id)` | Owner marks a false positive — counted separately from an acknowledgement |
| `cancel(alert_id, reason)` | Withdraw, legal only before anyone beyond the owner was paged |
| `open_alerts()` / `history()` | Queries |
| `next_deadline()` | Earliest pending deadline, so a driver can sleep instead of spin |

`tick()` is explicit and idempotent. Calling it more often than necessary is free;
calling it late only delays an escalation by the call interval. There is no
background thread, so you own the concurrency.

### 6.2 Time

`clock` must be **monotonic**. `time.monotonic` in production, a fake in tests.

Alert timestamps therefore have **no epoch** — they are not Unix timestamps and
must not be rendered as dates. If you need wall-clock time for storage, record it
separately alongside; never subtract one from the other.

---

## 7. Recipes

### Change the escalation timings

```bash
cp gateway/relay_config.example.json gateway/relay_config.json
# edit timing.owner_ack_seconds / caregiver_ack_seconds
python gateway/replay.py --scenario asleep     # watch the effect
```

`relay_config.json` is gitignored — it holds real phone numbers.

### Retrain and redeploy the model

```bash
# edit ml/canine_alert/config.py or models.py
make artifacts
make test           # confirms the C still agrees with the new model
```

### Add a feature

Edit **both** `ml/canine_alert/features.py` and
`firmware/collar/src/ca_features.c`, keeping the ordering identical, then bump
the counts in `ca_features.h`. `make test` fails loudly if they disagree.

Use two-pass moment calculations in the C. The one-pass form (`E[x²] − mean²`)
loses too much precision in float32 on a gyro channel sitting at several hundred
deg/s.

### Try a different classifier

Add a branch to `build_model()` in `models.py` and its name to `MODEL_ORDER`.
It is then evaluated under every protocol automatically. Only tree ensembles can
be transpiled to C by `export.py`.

### Change the REST contract

Three files, together: `tools/devserver.py`, `backend/.../AlertResource.java`,
and `docs/06-api.md`. A difference between the two implementations is a bug.

### Run the relay against real hardware

```bash
pip install bleak
python gateway/relay.py --source ble --backend http://localhost:8080
```

Without a collar, drive it from stdin:

```bash
echo '{"dog_id":"stuart","sequence":1,"device_uptime_ms":1000,"confidence":0.8,"votes":2,"window_count":4}' \
  | python gateway/relay.py --source stdin
```

### Inspect a single recording

```python
import sys; sys.path.insert(0, "ml")
from canine_alert.dataset import load_recordings, spin_events

for r in load_recordings():
    if spin_events(r):
        print(r.source_id, r.fs_hz, len(spin_events(r)))
```

---

## 8. Extension points

| To add | Implement | Contract |
|---|---|---|
| A notification transport | `Notifier.send(contact, alert, message) -> bool` | Return `False` on delivery failure; do not raise. Wrap with `RetryingNotifier` or `FanOutNotifier` — retry policy is written once, not per transport |
| A durable alert store | The `on_transition` hook (Python) or `AlertRepository` (Java) | Must not raise. Append-only; a state change is a new row, never a rewrite |
| A detection source | Anything producing a `DetectionEvent` | `alert_id()` must be stable across retransmissions of the same episode |
| A verification policy | `VerificationGate` params, or a new gate | Must emit a discrete moment. The ladder starts a timer on it and cannot consume a continuous score |
| Another dog | A second engine, keyed by `dog_id` | One engine per owner |
| A different MCU | Reuse `ca_*.c` unchanged; rewrite `collar.ino` | The core is portable C by design |

---

## 9. Testing

```bash
make test                                  # everything
python -m pytest ml/tests -q               # 90 tests, ~100 s
python -m pytest escalation/tests -q       # 63 tests, ~0.02 s
make -C firmware/test run                  # 240 checks
python -m pytest escalation/tests -q -k ack   # focused
```

### 9.1 What each suite guards

| Suite | Guards |
|---|---|
| `ml/tests/test_dataset.py` | The release really contains the 135 spins the paper reports; the 51.2 Hz vs 50 Hz discrepancy cannot be silently reintroduced; negative events keep their guard from any spin |
| `ml/tests/test_features.py` | Feature maths against NumPy; DC-offset invariance; rotation invariance of the magnitude features; no NaN on a constant window |
| `ml/tests/test_selection.py` | **The leakage guarantee** — selection depends only on training data |
| `ml/tests/test_verification.py` | The gate's exact semantics. This file is the specification the C port must satisfy |
| `ml/tests/test_export.py` | The transpiled forest is the same function as scikit-learn's |
| `escalation/tests/` | Every escalation failure mode, one test each |
| `firmware/test/test_native.c` | C/Python parity on real data; the gate in C; ring-buffer tear detection; `millis()` wrap |

### 9.2 Test naming

Tests are named after the failure they prevent, so a failing test name is a bug
report:

```
test_late_owner_acknowledgement_does_not_unring_the_bell
test_unreachable_caregiver_still_escalates
test_duplicate_detections_do_not_open_a_second_alert
test_stale_location_is_dropped_rather_than_sent
test_selection_depends_only_on_training_data
```

Prefer this to `test_acknowledge_2`.

---

## 10. Debugging and troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: numpy._core.numeric` | The NumPy 2 pickle shim's version probe broke | See §3.1 |
| `no .pkl files under spinning_dataset` | Dataset not downloaded | See §3.2 |
| `model_deployed.joblib not found` | Ran `replay.py` before training | `make experiments` |
| `vectors.bin is missing` | Firmware test run before generating vectors | `make vectors` |
| Firmware test: feature mismatches | `features.py` and `ca_features.c` have diverged | Check ordering and offsets; use two-pass moments |
| Firmware test: `CA_N_NODES` mismatch | `model.h` is stale | `make export` |
| Replay produces no alert | Vote threshold too high for that recording | `--scenario` is unrelated; check `results.json` operating point |
| Dashboard shows "cannot reach the backend" | Dev server not running | `python tools/devserver.py` |
| Seeded demo shows one alert | The same recording replayed repeatedly — idempotence collapses it | Use `tools/seed_demo.py`, which replays *different* recordings |
| Relay silently drops a detection | Malformed packet, or below `min_confidence` | Run with `--verbose` |

### 10.1 Useful invocations

```bash
python gateway/replay.py --scenario asleep --json      # machine-readable timeline
python -m pytest ml/tests -q -x --tb=short             # stop at first failure
python tools/devserver.py --port 9000                  # avoid a port clash
curl -s localhost:8080/api/v1/summary | python3 -m json.tool
```

---

## 11. Performance characteristics

### 11.1 On the collar

| Quantity | Value |
|---|---|
| Sample rate | 51.2 Hz |
| Classification cadence | every 1.3 s |
| Feature vector | 159 computed, 20 used |
| Model | 32 trees, 2862 nodes, **39.2 KiB** flash |
| Working RAM | ~12 KiB scratch + 4.8 KiB ring |
| Detection latency | ~3.1 s median from spin onset |
| Estimated draw | ~50 mA steady, ≈24 h on 1200 mAh |

The dominant compute cost is eight 133-point DFTs per window. A direct DFT is
used rather than an FFT because 133 is not a power of two, and zero-padding to
256 would change the spectrum — so the device would no longer compute the
features the model was trained on.

**Timings on real silicon are unmeasured**; no board was available. See
[09-limitations.md](09-limitations.md) §3.

### 11.2 On a laptop

| Task | Time |
|---|---|
| `make artifacts` | ~30 s |
| `run_experiments.py` | ~20 s |
| `ml/tests` | ~100 s |
| `escalation/tests` | 0.02 s |
| `firmware/test` | < 1 s |
| One `replay.py` scenario | ~5 s |

---

## 12. Invariants you must not break

Each is enforced by a test. Each was chosen because breaking it *silently* would
be worse than breaking it loudly.

1. **`features.py` and `ca_features.c` compute the same thing.** The model's
   thresholds were learned on the Python features.
2. **Feature selection is fitted inside each CV fold**, never globally. Fitting
   globally leaks test labels into feature *choice*.
3. **Escalation timers use an injected monotonic clock.** Never call
   `time.time()` in `escalation/`.
4. **Alert ids derive from the episode**, not from arrival time. This is what
   makes a BLE retransmission idempotent rather than a second page.
5. **`escalation/` performs no I/O.**
6. **The relay owns the ladder; the backend only records it.** Adding a "resolve
   this alert" endpoint creates a race whose losing writer is a page that does or
   does not go out.
7. **Notification is at-most-once per channel per alert.** A caregiver paged
   twice learns to ignore the app.
8. **Failure escalates, it does not stall.** An unreachable caregiver must not
   park an alert waiting for an acknowledgement that can never arrive.

---

## 13. Code conventions

**Comments explain why, not what.** Especially where the obvious implementation
is wrong: two-pass moments instead of one-pass, a DFT instead of an FFT, unsigned
arithmetic for the `millis()` wrap, dropping stale GPS fixes rather than sending
them.

**Tests are named after the failure they prevent.** See §9.2.

**Numbers are generated, never typed.** Anything appearing in the documentation
comes from `ml/artifacts/` and is cited from there.

**Naming.** Python is `snake_case`; C is `ca_`-prefixed; Java mirrors the Python
domain types field for field. When you rename a domain concept, rename it in all
three.

**Docstrings state the decision and its reason**, not a restatement of the
signature. If a function exists because a simpler approach failed, say which and
why — that is the comment that stops someone re-introducing the simpler approach.
