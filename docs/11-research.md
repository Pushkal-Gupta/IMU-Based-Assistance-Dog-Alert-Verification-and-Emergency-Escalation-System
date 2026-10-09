# Research programme and paper

The project's research write-up is the manuscript in [`paper/`](../paper/),
prepared for MDPI *Sensors*. This page maps each claim in it to the code that
produces it, and records what changed in the system as a result of the
research.

The paper supersedes the single-level numbers in
[07-evaluation.md](07-evaluation.md) wherever the two differ. That page
documents the original curated-event protocol, which the paper keeps as a
baseline and then improves on.

## 1. One command

```bash
make all-research    # ~25 min on 8+ cores; then paper/build/main.pdf
```

| Step | Script | Artifact |
|---|---|---|
| Detection, single-level gate sweep | `ml/scripts/run_experiments.py` | `ml/artifacts/results.json` |
| Cluster-bootstrap intervals, paired tests, session/device shift, nested gate selection, continuous streams, sensor range | `ml/scripts/run_research.py` | `ml/artifacts/research.json` |
| CNN/ROCKET/boosting baselines, ablations, embedded size/accuracy front, sensor-transfer robustness | `ml/scripts/run_ablations.py` | `ml/artifacts/ablations.json` |
| Monte-Carlo escalation outcomes, false-alarm burden, T1/T2 grid | `escalation/sim/run_sim.py` | `escalation/artifacts/simulation.json` |
| TLA⁺ model checking (26 checks) | `formal/run_tlc.py` | `formal/results.json` |
| Property-based conformance tests (10,000 examples per property) | `escalation/tests/test_properties.py` | test pass/fail |
| Host benchmark of the C core | `firmware/test/bench.c` | `firmware/test/bench*.json` |
| C vs Python parity | `firmware/test/test_native.c` | `firmware/test/parity.log` |
| Numbers, figures, supplementary files, PDF | `paper/scripts/*` | `paper/generated/`, `paper/figures/`, `paper/supplementary/`, `paper/build/main.pdf` |

The manuscript contains no typed results. Every number is `\R{key}`, generated
into `paper/generated/numbers.tex`, and `paper/scripts/check_numbers.py` fails
the build on an undefined key or on a bare literal that equals a generated
value.

## 2. New methods, by module

| Module | What it adds |
|---|---|
| `ml/canine_alert/stats.py` | Cluster bootstrap over recording groups, Garwood and Wilson intervals, McNemar, Wilcoxon, Holm |
| `ml/canine_alert/nested.py` | Nested leave-one-group-out selection of the gate policy |
| `ml/canine_alert/streaming.py` | End-to-end replay of whole recordings, any-overlap scoring, exposure-normalised false alarms, alert episodes |
| `ml/canine_alert/robustness.py` | Collar rotations, the MPU6050 datasheet error model, range clipping and quantisation, jitter, rate mismatch |
| `ml/canine_alert/raw_models.py` | 1-D CNN and ROCKET baselines on raw windows |
| `formal/Escalation.tla` | The ladder, relay–backend link, partitions, relay death and the watchdog (Direct and Ladder variants) |
| `escalation/sim/` | Discrete-event simulation that drives the real `EscalationEngine` |

## 3. What the research changed in the system

1. **The heartbeat bug was fixed.** Heartbeats carried the owner's contact id,
   but the backend watchdog matches heartbeats to alerts by dog id, so the
   watchdog never saw a heartbeat. The relay now sends `dog_id`.
   `gateway/tests/test_relay.py` is the regression test.
2. **The gate is tuned on the model that ships.** The operating point used to be
   tuned on the 200-tree forest while the firmware ran the 32-tree forest.
   `run_experiments.py` now tunes it on the deployed model.
3. **The firmware DFT uses a twiddle table.** The old code made 140k
   `sinf`/`cosf` calls per window; the table halves the host cost and is more
   accurate. Parity with Python is unchanged.
4. **Found, but not yet built:**
   - the ladder-aware watchdog (verified in `Escalation.tla`, simulated in
     `escalation/sim/`) for `backend/.../EscalationWatchdog.java`;
   - idempotent paging at a shared provider;
   - rotation augmentation or magnitude-only features for the deployed model;
   - an explicit IMU full-scale range check in firmware.

## 4. Headline findings

See the paper's Abstract and Discussion. In short:

- Escalation is verifiably correct, but outcomes are bounded by detection.
- Continuous-stream false alarms are several times what the curated protocol
  implies.
- The false-alarm rate needed for an acceptable caregiver burden is three
  orders of magnitude below the rate measured on training-session motion.
- Collar rotation, not sensor noise, is the main risk in moving from the
  Shimmer3 to the MPU6050.
