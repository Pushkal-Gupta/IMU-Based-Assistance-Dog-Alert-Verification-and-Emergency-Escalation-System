# Literature and the novelty claim

---

## 1. Prior art

### 1.1 The study this project builds on

**Brady, S.; Smeaton, A.F.; Song, H.; Ward, T.; Smeaton, A.; Dowler, J.**
*Development and Validation of an IMU Sensor-Based Behaviour-Alert Detection
Collar for Assistance Dogs: A Proof-of-Concept Study.* Animals **2025**, 15,
3081. [doi:10.3390/ani15213081](https://doi.org/10.3390/ani15213081)

| | |
|---|---|
| **Contribution** | A Shimmer3-based collar detects a trained two-spin seizure-alert behaviour in six assistance dogs. Random Forest reaches LODO accuracy 0.92, F1 0.65; event-level aggregation cuts missed detections from 121 to 4. Dataset released publicly. |
| **Limitation** | Stops at detection. Offline analysis, not real-time. Their own discussion names transmitting alerts "to owners, caregivers or emergency services" as future work. |
| **What we take** | The feasibility result, the segmentation and feature-selection method, and the dataset. |
| **What we add** | Real-time on-device inference, the verification gate, and the entire escalation layer. |

### 1.2 Earlier behaviour recognition in assistance dogs

**Raju et al.** — accelerometer-only recognition of trained signalling behaviours
(spin, jump, sit) in assistance dogs, using per-dog models and within-dog
cross-validation.

*Limitation:* per-dog models do not generalise, accelerometer-only data is
sensitive to sensor orientation drift, and evaluation is at whole-event level.
Brady et al. address all three (adding a gyroscope, a generalised LODO model, and
finer temporal resolution). Neither addresses what happens after detection.

### 1.3 Seizure-alerting behaviour in dogs

**Powell et al.** exposed 19 untrained pet dogs to sweat samples from people with
epilepsy and observed reliable affiliative behaviour towards pre-seizure and
seizure-phase odours — evidence that dogs can detect seizure-related volatile
organic compounds.

**Martos et al.** found alerting dogs had stronger owner bonds and distinct
personality traits.

*Limitation:* both study *spontaneous* behaviour, which is inconsistent between
animals and hard to validate objectively. This is precisely why Brady et al.
standardise on a *trained* signal — and why a trained signal is what a detector
can be built on at all.

### 1.4 Human-worn seizure monitoring

A large literature applies ML (Logistic Regression, SVM, LSTM) to EEG,
accelerometry and ECG for seizure detection and forecasting.

*Limitation:* these devices are worn by the person and rely on bodily biosignals.
Most detect seizures **post-onset**, and reviews report false positives, poor
usability in assisted-living contexts, and weak generalisation. They also do not
help with the specific problem here: an alert that nobody perceives.

### 1.5 Animal wearables generally

Commercial and research wearables for dogs focus on activity, welfare, stress and
fatigue monitoring — continuous physiological or behavioural *state* estimation.

*Limitation:* none of these detect a **trained, intentional signal**, and none
treat the dog as a sensor in a human-safety loop.

---

## 2. The gap

| Capability | Raju et al. | Brady et al. | Human seizure wearables | Dog activity trackers | **This work** |
|---|---|---|---|---|---|
| Detects a trained alert behaviour | ✓ | ✓ | — | — | ✓ |
| Cross-subject generalisation | — | ✓ | partial | ✓ | ✓ (with caveats) |
| Real-time on-device inference | — | — | ✓ | ✓ | ✓ |
| Explicit alert verification gate | — | — | — | — | **✓** |
| **Escalation when the owner cannot respond** | — | — | — | — | **✓** |
| Longitudinal alert-reliability record | — | — | — | partial | **✓** |

Every row above the double rule exists somewhere in the literature. **No system
we could find closes the last two.**

---

## 3. The claim, precisely

> Existing wearable research on service and assistance dogs addresses either
> general state monitoring (activity, stress, fatigue) or the detection of
> trained signalling behaviour. We are not aware of a system that detects and
> verifies a dog's trained alert behaviour **and provides an automatic
> escalation path for when the owner cannot respond** — which is the failure
> scenario the alert-dog training exists to cover in the first place.

Two secondary contributions:

1. **A deployable detection layer.** The published work is offline analysis in
   Python. We transpile the trained forest to 39 KiB of C, verify the port
   numerically against scikit-learn on real data, and run it on a microcontroller
   under a streaming verification policy.
2. **A longitudinal record of alert reliability.** The backend logs every alert,
   dismissal and escalation over time, giving a caregiver, vet or trainer the
   first objective measure of whether a dog's trained alert is holding up — and
   whether the owner is still responding to it.

### 3.1 What we do not claim

- **Not** that the detection method is novel. It is Brady et al.'s, re-implemented.
- **Not** that our cross-subject numbers are comparable to theirs on equal terms.
  The public dataset carries no dog identities, so we use recording groups
  instead ([07-evaluation.md §1.2](07-evaluation.md#12-what-we-could-not-reconstruct)).
- **Not** that the system is clinically validated, deployable, or safe to rely on
  ([09-limitations.md](09-limitations.md)).
- **Not** that a literature search proves absence. "We are not aware of" is the
  honest form of the claim.

---

## 4. Positioning

The system sits at the intersection of animal-assisted intervention and the
Internet of Medical Things. Brady et al. frame their collar in the same terms;
this work extends the framing from *sensing* to *response*, which is where an
IoMT system earns its name — a sensor that detects an emergency and tells nobody
is not a medical thing, just a thing.

---

## 5. References

1. Brady, S. et al. *Animals* **2025**, 15, 3081. doi:10.3390/ani15213081
2. Brady, S. et al. *Package of motion sensor data of spin alert behaviour.*
   figshare. doi:10.6084/m9.figshare.30022441
3. Raju, S. et al. Wearable accelerometer-based behaviour recognition in
   assistance dogs. (as cited in [1], ref. 19)
4. Powell, L. et al. Seizure-related odour discrimination by untrained pet dogs.
   (as cited in [1], ref. 16)
5. Martos Martinez-Caja, A. et al. Behaviour and personality of seizure-alerting
   dogs. (as cited in [1], ref. 14)
6. World Health Organization. *Epilepsy fact sheet.*

References 3–5 are cited as they appear in [1]; full bibliographic details are in
that paper's reference list. We have not independently obtained them, and say so
rather than presenting a reference list that implies otherwise.
