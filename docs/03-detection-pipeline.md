# The detection pipeline

Reproduces Brady et al.'s detection method and adds the verification gate.
Code: `ml/canine_alert/`. Results: [07-evaluation.md](07-evaluation.md).

---

## 1. From raw signal to a decision

```
 IMU stream           6 channels @ 51.2 Hz  (accel m/s², gyro deg/s)
      │
      ▼ curate                              dataset.py
 events               401 samples = 7.83 s, behaviourally pure
      │
      ▼ segment                             segmentation.py
 windows              133 samples = 2.6 s, 67-sample stride (50%)
      │
      ▼ extract                             features.py
 159 features         8 signals × (13 time + 5 freq) + 15 correlations
      │
      ▼ select                              selection.py
 20 features          variance → collinearity → ANOVA F-test
      │
      ▼ classify                            models.py
 p(spin)              random forest
      │
      ▼ verify                              verification.py   ← ours
 ALERT                2 of the last 4 windows at p ≥ 0.45, then 60 s refractory
```

---

## 2. Channels

Six of the fifteen columns in the dataset: `Accel_LN_{X,Y,Z}` and
`Gyro_{X,Y,Z}`.

Excluded, and why:

- **`Accel_WR_*`** (wide-range accelerometer) — the target MPU6050 has one
  accelerometer, not two. Using a channel the hardware cannot supply would make
  the model unportable.
- **`Mag_*`** (magnetometer) — same reason.
- **`Battery`** — not a motion signal.

The paper makes the same choice. It also deliberately does **not** separate
gravity from body acceleration, because the collar's orientation is not fixed and
any such decomposition would be unreliable. We follow that.

---

## 3. Event curation

Windows are cut from *events*, and events are the atomic unit for every
train/test split. This is what prevents a single behavioural occurrence from
appearing on both sides of a split.

**Positive events** are centred on an annotated spin and padded outwards to 401
samples, shifted rather than truncated at recording edges so every one yields the
full five windows.

**Negative events** tile the spin-free regions, keeping a **1 s guard** from any
annotated spin. Without the guard, a negative event abutting a spin would teach
the model that the run-up to a spin is 'not spin' — which is both false and
exactly the region a real detector must get right.

342 events result: 134 positive, 208 negative.

### 3.1 Why 401 samples and not 7.8 s

The paper describes 7.8 s events with "five constituent 2.6 s segments". At
51.2 Hz, 7.8 s is 399 samples, which yields only **four** windows at a 67-sample
stride. We derive the event length from the window geometry instead —
`width + 4 × stride = 133 + 268 = 401` samples = 7.83 s — which gives exactly the
five the paper describes. `test_event_yields_exactly_the_configured_window_count`
pins this.

---

## 4. Features

Eight signals are derived from the six channels: the six raw axes plus two
rotation-invariant magnitudes, `|a|` and `|g|`.

**The magnitudes are not decoration.** A collar rotates freely around a dog's
neck and sits differently every time it is fitted. Per-axis features shift with
the mounting; magnitudes do not.
`test_magnitude_features_are_rotation_invariant` asserts this against a synthetic
rotation, and the selector picks three magnitude features unprompted
([07-evaluation.md §6](07-evaluation.md#6-feature-stability)).

### 4.1 Time domain (13 per signal)

`mean`, `std`, `min`, `max`, `range`, `median`, `iqr`, `rms`, `mad`, `skew`,
`kurtosis`, `mcr` (mean-crossing rate), `energy`.

### 4.2 Frequency domain (5 per signal)

`dom_freq`, `spec_energy`, `spec_entropy`, `spec_centroid`, `peak_power`.

The window is mean-centred before the transform and the DC bin is dropped, so
gravity on the accelerometer and gyro bias cannot influence any spectral feature.
`test_dc_offset_does_not_change_frequency_features` asserts it.

### 4.3 Correlations (15)

Pairwise Pearson between the six raw channels. A spin couples the axes in a
characteristic way that per-channel statistics cannot express.

### 4.4 The embedded constraint

Every feature must be computable on an ESP32 from a 133-sample buffer in a few
milliseconds. That rules out anything needing the whole recording — no global
normalisation, no long-window context. It is why the feature set is what it is,
and it is checked by the fact that `ca_features.c` computes all 159 and agrees
with NumPy to 3 × 10⁻³.

---

## 5. Three-stage selection

Per the paper:

| Stage | Rule | Effect on the full dataset |
|---|---|---|
| 1. Low variance | drop variance < 0.1 | 159 → 159 (none dropped) |
| 2. Collinearity | of any pair with \|r\| > 0.95, keep one | 159 → 125 |
| 3. Univariate | ANOVA F-test, top 20 | 125 → **20** |

**One deviation.** The paper applies the variance threshold to raw features. On
raw features a fixed 0.1 is scale-dependent — it would delete correlations (which
live in [−1, 1]) while keeping every gyro feature (deg/s, variance in the
thousands), making the stage meaningless for most of the vector. We standardise
first, so the threshold means the same thing for every feature. The consequence
is that stage 1 drops nothing here: after standardisation, a feature has unit
variance unless it was constant.

**The selector is fitted inside each CV fold.** Fitting on the full dataset before
splitting would leak test-set label information into feature *choice*. The paper
does not state which it did; we take the conservative route and
`test_selection_depends_only_on_training_data` enforces it.

---

## 6. Models

Four supervised models, matching the paper, plus the heuristic baseline:

| Model | Notes |
|---|---|
| Random Forest | 200 trees, depth 12, balanced subsample. **Deployed.** |
| Random Forest (embedded) | 32 trees, depth 8 — what the collar runs |
| SVM | RBF, balanced, Platt-scaled probabilities |
| Gaussian Naive Bayes | |
| Logistic Regression | balanced, `max_iter=2000` |
| Heuristic baseline | threshold on mean \|gyro\|, tuned per fold on the training half |

The baseline threshold is tuned on the *training* fold only. A fixed threshold
would be a straw man; this makes the comparison fair, and it is why our baseline
scores higher than the paper's.

### 6.1 Why 32 trees on the collar

A 200-tree, depth-12 forest transpiles to roughly 100 KiB of node tables. That
fits in 4 MB of flash but is wasteful for the accuracy it buys: 32 trees at depth
8 is **39.2 KiB** and costs 0.005 LOGO F1 (0.657 → 0.652). Both are evaluated
side by side so the trade is visible rather than assumed.

---

## 7. The verification gate (ours)

```
every 1.3 s:
    p ← classify(last 133 samples)
    vote ← (p ≥ 0.45)
    push vote into a 4-slot circular buffer

    if votes_in_buffer ≥ 2:
        if time_since_last_alert ≥ 60 s:
            emit ALERT(confidence = mean p of the voting windows)
            clear the buffer
```

Three properties, each deliberate:

**K of the last N, not K consecutive.** A dog's spin is not perfectly uniform;
requiring consecutive positives would fail on a single low-confidence window in
the middle of a genuine alert.

**The buffer is cleared after firing.** Without this the gate re-fires on the
same stale evidence the instant the refractory period ends, turning one episode
into a repeating page. `test_evidence_is_cleared_after_firing` pins it.

**The refractory period uses unsigned arithmetic in C**, which stays correct
across the 49.7-day `millis()` wrap. Tested explicitly in
`firmware/test/test_native.c`.

Confidence is the mean probability of the *voting* windows only — a
non-contributing window must not drag it down.

Operating point selection and the full sweep:
[07-evaluation.md §4](07-evaluation.md#4-the-verification-gate-ours).

---

## 8. Python → C export

`ml/scripts/export_firmware_model.py` emits `firmware/collar/src/model.h`:

- `ca_feature_index[20]` — indices into the full 159-vector
- `ca_feature_mean[20]`, `ca_feature_scale[20]` — the fitted `StandardScaler`
- flattened forest: `ca_node_{feature,left,right,threshold,value}`,
  `ca_tree_offset`
- the gate's policy, read back from `results.json` so the firmware ships the
  configuration the evaluation actually selected

**Trees are flattened into arrays, not emitted as nested `if` statements.** At a
few thousand nodes, nested conditionals blow up instruction cache and compile
time; a flat table is `const` data in flash walked by a three-line loop.

**The firmware computes all 159 features and gathers 20**, rather than computing
only the survivors. Gathering is a cheap loop, and it makes the C impossible to
desynchronise from `features.py` when retraining selects different features.

The exporter refuses to write the header if the transpiled forest disagrees with
scikit-learn by more than 10⁻⁶ on the whole dataset. Measured: **8.1 × 10⁻⁹**.

---

## 9. Reproducing

```bash
python ml/scripts/run_experiments.py        # train + evaluate → results.json
python ml/scripts/export_firmware_model.py  # → firmware/collar/src/model.h
python ml/scripts/make_firmware_vectors.py  # → firmware/test/vectors.bin
python ml/scripts/make_figures.py           # → docs/figures/
make -C firmware/test run                   # verify the C against the Python
```

Or `make artifacts`. Everything is seeded (`random_state=42`) and deterministic.
