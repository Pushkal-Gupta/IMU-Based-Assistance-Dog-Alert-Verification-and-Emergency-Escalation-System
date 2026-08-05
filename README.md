# IMU-Based Assistance Dog Alert Verification and Emergency Escalation System

A wearable collar for trained seizure-alert assistance dogs that detects the
dog's trained alert behaviour, verifies it across several seconds of motion, and
**escalates to a caregiver or emergency contact if the owner cannot respond**.

> A trained alert dog only helps if a human notices the signal. The situation the
> dog is trained for — the owner is about to have a seizure — is exactly the
> situation in which the owner may be unable to notice anything. Detection
> without escalation solves the easy half of the problem.

---

## What is ours and what is not

This project builds on a published proof-of-concept and says so explicitly.

| Layer | Origin |
|---|---|
| Feasibility of IMU spin-alert detection | Brady et al., *Animals* **2025**, 15, 3081 ([DOI](https://doi.org/10.3390/ani15213081)) |
| The dataset (135 labelled spins, 6 dogs) | [figshare 30022441](https://doi.org/10.6084/m9.figshare.30022441), released by the same authors |
| Our detection pipeline | Re-implemented and re-trained from scratch on that data |
| **Multi-stage verification gate** | **Ours** |
| **Owner → caregiver → emergency escalation** | **Ours** |
| **Relay node, backend, caregiver dashboard** | **Ours** |
| **ESP32 firmware and the Python→C model export** | **Ours** |

The source study ends at detection. Its own discussion identifies transmitting
alerts "to owners, caregivers or emergency services" as future work. That gap is
this project.

## Headline results

All figures are produced by `ml/scripts/run_experiments.py` and land in
`ml/artifacts/results.json`. Nothing in the docs is typed by hand.

| | Random Forest | Heuristic baseline |
|---|---|---|
| Segment F1, pooled random split | 0.70 | 0.61 |
| Segment F1, leave-one-group-out | **0.66** | 0.58 |
| Event F1, leave-one-group-out | **0.87** | 0.83 |
| Event recall (alerts caught) | **0.88** | 0.88 |

Shipped operating point (2-of-4 windows at p ≥ 0.45): **77% of alert episodes
detected, 3.2 s median latency from the dog starting to spin, and 19.9 false
alarms per hour of spin-free training-session motion.** That last number is high
and is discussed honestly in [docs/07-evaluation.md](docs/07-evaluation.md) —
it is the main reason the architecture requires an owner acknowledgement before
anyone else is contacted.

![Verification gate trade-off](docs/figures/fig5_operating_curve.png)

## Try it in three commands

```bash
pip install -r requirements.txt

# 1. Train and evaluate the detection layer (~20 s)
python ml/scripts/run_experiments.py

# 2. Watch a real recording escalate because the owner never responded
python gateway/replay.py --scenario asleep
```

```
   111.2  collar: verification gate fired (2/4 windows, confidence 0.67)
   111.2  alert e5c328 -> PENDING_OWNER
   111.2  notified OWNER (owner-1) -- delivered
   171.4  alert e5c328 -> PENDING_CAREGIVER
   171.4  notified CAREGIVER (care-1) -- delivered
   292.3  alert e5c328 -> ESCALATED_EMERGENCY
   292.3  notified EMERGENCY (emerg-1) -- delivered
```

```bash
# 3. Bring up the caregiver dashboard with a seeded history
python tools/devserver.py &
python tools/seed_demo.py --backend http://localhost:8080
open http://localhost:8080/
```

## Architecture

```
   ┌────────────────────┐        ┌──────────────────────┐       ┌────────────────────┐
   │  COLLAR (ESP32)    │  BLE   │  RELAY (owner phone) │ HTTPS │  BACKEND (Jakarta) │
   │                    │ ─────▶ │                      │ ────▶ │                    │
   │ MPU6050 @ 51.2 Hz  │        │ owner ack window T1  │       │ audit log          │
   │ 133-sample windows │        │ caregiver window T2  │       │ relay watchdog     │
   │ 20 features        │        │ SMS / push           │       │ caregiver dashboard│
   │ 32-tree forest     │        │ GPS fix              │       │                    │
   │ 2-of-4 gate        │        │                      │       │                    │
   └────────────────────┘        └──────────────────────┘       └────────────────────┘
        detection                  escalation ladder                 the record
```

The escalation ladder runs **on the phone**, not in the cloud: the alert matters
most where connectivity is worst. The backend runs an independent watchdog for
the case where the phone itself dies. Full rationale in
[docs/02-architecture.md](docs/02-architecture.md).

## Repository layout

| Path | What it is |
|---|---|
| `ml/` | Detection layer: dataset, features, models, evaluation, model export |
| `escalation/` | The escalation state machine — the project's core contribution |
| `firmware/collar/` | ESP32 firmware; the algorithmic core is portable C |
| `firmware/test/` | Host test of that core against golden vectors from the real data |
| `gateway/` | Relay node (phone) and the end-to-end replay harness |
| `backend/` | Jakarta EE 10 / MicroProfile caregiver backend |
| `tools/` | Dev server (stand-in for the Java backend) and demo seeder |
| `dashboard/` | Caregiver-facing alert history |
| `docs/` | Full documentation set — start with `00-index.md` |
| `spinning_dataset/` | The figshare dataset (78 `.pkl` files) |

## Documentation

| Document | Covers |
|---|---|
| [00-index.md](docs/00-index.md) | Reading order and document map |
| [01-project-report.md](docs/01-project-report.md) | The full academic report |
| [02-architecture.md](docs/02-architecture.md) | System design and the decisions behind it |
| [03-detection-pipeline.md](docs/03-detection-pipeline.md) | Signal processing and machine learning |
| [04-escalation-protocol.md](docs/04-escalation-protocol.md) | The state machine, formally |
| [05-hardware.md](docs/05-hardware.md) | Bill of materials, wiring, power budget |
| [06-api.md](docs/06-api.md) | REST contract |
| [07-evaluation.md](docs/07-evaluation.md) | Results, with the caveats stated plainly |
| [08-literature.md](docs/08-literature.md) | Prior art and the novelty claim |
| [09-limitations.md](docs/09-limitations.md) | What this is not, and what would have to change |

## Verification status

| Component | Status |
|---|---|
| `ml/` (90 tests) | Passing |
| `escalation/` (63 tests) | Passing |
| `firmware/` core (240 checks) | Passing — C verified against Python on 64 real windows |
| Replay, 4 scenarios | Passing on real recordings |
| Dev server + dashboard | Verified in-browser |
| `backend/` (Java) | **Not built** — no Maven in this environment; syntax-checked only |

Run everything with `make test`.

## Course-module mapping

| Module | Where it appears |
|---|---|
| M2 — BLE and building blocks | Collar → phone GATT service (`firmware/collar/collar.ino`) |
| M3 — BSN architecture | Two-node body sensor network (`docs/02-architecture.md`) |
| M5 — Cloud-assisted BSN | Backend, watchdog, dashboard (`backend/`, `dashboard/`) |
| M6 — SPINE-style activity recognition | Windowing, features, classification (`ml/canine_alert/`) |

## Ethics and scope

No animals were involved in this project. All data comes from the published
figshare release, collected under Dublin City University REC approval
(DCUREC/2025/065) and Beaumont Hospital REC 25/16.

**This is a student proof-of-concept, not a medical device.** It has not been
clinically validated, has a measured false-alarm rate too high for unsupervised
use, and must not be relied upon for medical decisions. See
[docs/09-limitations.md](docs/09-limitations.md).

## Citation

```bibtex
@article{brady2025collar,
  title   = {Development and Validation of an IMU Sensor-Based Behaviour-Alert
             Detection Collar for Assistance Dogs: A Proof-of-Concept Study},
  author  = {Brady, Shelley and Smeaton, Alan F. and Song, Hailin and
             Ward, Tom{\'a}s and Smeaton, Aoife and Dowler, Jennifer},
  journal = {Animals},
  volume  = {15}, number = {21}, pages = {3081}, year = {2025},
  doi     = {10.3390/ani15213081}
}
```
