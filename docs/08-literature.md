# Related work

A survey of the five research areas this system sits between, and a precise
statement of what is and is not new here.

**On citation practice.** Where we have read the full text, the entry is
detailed. Where we are working from an abstract or a database record, the entry
says so and reports only what that record states. We do not reconstruct results
we have not seen. Every reference in §7 carries a resolvable identifier.

---

## 1. Do dogs detect seizures at all?

The premise underneath everything here is that some dogs perceive an oncoming
seizure. The evidence is real but weaker than the popular account suggests.

### 1.1 The behavioural evidence

A scoping review of dogs alerting to or responding to epileptic seizures
[[R1](#r1)] surveys the field and reaches a blunt methodological conclusion: the
level of rigour in existing studies is generally poor. Reported alert lead times
range from **10 seconds to 5 hours**, with accuracies of **70–85%** — but those
accuracies are *owner-reported*, not measured against instrumented ground truth.
The review notes that establishing sensitivity and specificity would require a
prospective study documenting every seizure *and* every alert, which has not been
done.

An evaluation of a formal seizure-response-dog training programme
[[R2](#r2)] found spontaneous alerting behaviour developed in **59%** of dogs —
i.e. it is common but far from universal, and it emerges rather than being
reliably trainable. The most frequent behaviours were barking or whining (95% of
dogs), licking (50%), and anxious behaviour (41%). A more recent treatment of
trained versus untrained dogs in seizure detection and warning [[R3](#r3)]
revisits the same distinction.

### 1.2 The biochemical mechanism

The proposed mechanism is olfactory: humans emit volatile organic compounds
(VOCs), some of which are altered in the pre-ictal state. Brady et al.
[[R4](#r4)] summarise this literature, citing work identifying menthone as a
possible pre-ictal marker, canine identification of pre-clinical seizure VOCs at
~82% accuracy, and controlled exposure of untrained pet dogs to sweat samples
that produced reliable affiliative responses to pre-seizure and seizure-phase
odours.

### 1.3 What this establishes, and what it does not

**Establishes:** some dogs perceive something that precedes a seizure, and the
mechanism is plausibly olfactory.

**Does not establish:** that this is reliable, reproducible across animals, or
measurable. This is the reason Brady et al. — and this work — build on a
**trained, standardised signal** rather than on spontaneous behaviour. A
spontaneous alert cannot be validated; a cued two-spin rotation can.

**Consequence for this system.** Everything downstream inherits this uncertainty.
We detect *the dog's signal*, not the seizure. If the dog is wrong, the system is
confidently and promptly wrong. No amount of engineering below this layer repairs
it, and this is the reason the escalation ladder requires a human acknowledgement
rather than dispatching help autonomously.

---

## 2. Instrumenting the dog

### 2.1 The immediate predecessor

**Raju, Sharma, Smeaton and Smeaton (2023)** [[R5](#r5)], ACM SAC '23, collected
collar-mounted **accelerometer** data from **11 trained assistance dogs over 107
days** and applied machine learning to distinguish trained signalling behaviour
from routine activity. They describe the work as "a step towards automatic
alerting of the likely onset of an epileptic seizure."

*Limitations*, as characterised by [[R4](#r4)]: reliance on per-dog models,
susceptibility to sensor-orientation drift (accelerometer only), and evaluation
at whole-event granularity.

*The alerting step named in their own framing is not implemented.*

### 2.2 The work this system builds on

**Brady et al. (2025)** [[R4](#r4)], *Animals* 15, 3081 — the study we
re-implement, and the only one we have read in full.

| | |
|---|---|
| Platform | Shimmer3 IMU (3-axis accelerometer + 3-axis gyroscope) at 50 Hz nominal |
| Subjects | 6 trained assistance dogs (2 Golden Retrievers, 2 Chocolate Labradors, 2 Standard Poodles), aged 1.5–2 years |
| Behaviour | A standardised alert: two rapid clockwise 360° spins in immediate succession, each ~2 s |
| Data | 412.6 h of motion collected; 3078 s annotated against synchronised video; **135 labelled spin events** totalling 349 s |
| Method | 2.6 s sliding windows at 50% overlap; statistical + spectral features; three-stage selection to 20 features; RF / SVM / Naive Bayes / Logistic Regression, against a gyroscope-magnitude threshold baseline |
| Protocol | Within-subject (pooled) and **Leave-One-Dog-Out** |
| Results | RF best: within-subject accuracy 0.95 / F1 0.87; LODO accuracy 0.924 / F1 0.65 / ROC-AUC 0.70. Event-level aggregation cut false negatives from 121 to 4 |
| Released | The annotated sensor package, publicly [[R6](#r6)] |

Their advances over [[R5](#r5)] are explicit: adding a gyroscope for orientation
robustness, a *generalised* model tested under LODO rather than per-dog models,
and finer temporal resolution.

**Their stated limitation, and this project's scope.** Their Materials and Methods
describes the collar as one "which in the future could be further evaluated for
transmitting real-time alerts to owners, caregivers or emergency services." Data
was recorded to SD and analysed offline. There is no transmission, no
acknowledgement, and no escalation.

### 2.3 Sensor placement

Comparative work on movement-sensor placement in dogs [[R7](#r7)] reports up to
**91%** activity-classification accuracy from a back/harness-mounted sensor
against **75% at best** from a collar-mounted one. Collar mounting is
substantially harder.

This is a direct constraint on any collar-based system, including this one, and
it motivates the rotation-invariant magnitude features described in
[03-detection-pipeline.md](03-detection-pipeline.md) §4 — a collar rotates freely
around the neck and sits differently at each fitting, so per-axis features are
not stable across mountings.

### 2.4 Canine behaviour recognition more broadly

Wearable behaviour recognition in dogs is an established area within
Animal-Computer Interaction. Collar-mounted movement sensors have been used for
activity classification [[R8](#r8)], deep learning has been applied to
wearable-based behaviour recognition in search-and-rescue dogs [[R9](#r9)], and
commercial products (FitBark, PetPace, PitPat) monitor activity and welfare.
Sensors are typically 3-axis accelerometers and gyroscopes at the collar, back,
withers or tail, sometimes with biometric channels.

**What is uniformly absent:** these systems estimate a continuous *state*
(activity, stress, fatigue, welfare). None detect a **trained, intentional
signal**, and none place the animal inside a human-safety loop where the output
must reach a person within a bounded time.

---

## 3. Instrumenting the human instead

The alternative approach: skip the dog and monitor the person.

### 3.1 Performance

A systematic review and meta-analysis of automated seizure detection with
non-invasive wearables [[R10](#r10)] found that for **accelerometry-based
detection of tonic-clonic seizures**, pooled sensitivity was **93% (95% CI
85–99%)** with a false-alarm rate of **2.5 per 24 hours (95% CI 1.95–3.1)**. A
survey of non-EEG seizure detection devices [[R11](#r11)] reports sensitivities of
**79.4–96%** with false-alarm rates of **0.20–1.92 per 24 hours**. An updated
review [[R12](#r12)] revisits both figures. A phase-3 clinical validation of
smartphone-connected wearable ECG [[R13](#r13)] represents the current standard of
evidence in the field.

### 3.2 The limits

Three recur across [[R10](#r10)]–[[R12](#r12)]:

1. **Focal seizures remain poorly detected**, especially in ambulatory settings.
   Generalised and focal-to-bilateral tonic-clonic seizures are the solved case.
2. **Most validation is inpatient**, in epilepsy monitoring units, which limits
   transferability to home and workplace.
3. **Detection is largely post-onset.** These devices report that a seizure *is
   happening*, not that one is coming.

Point 3 is the structural difference. A dog's alert — if genuine — is
**pre-ictal**. That is a different and more valuable signal, and it is the reason
the animal-mediated approach remains interesting despite the human-worn
alternative being better validated.

### 3.3 The benchmark that matters most to this work

**The false-alarm figures above are the honest yardstick for our own.**
Clinically-validated wearables achieve roughly **2.5 false alarms per day**. Our
shipped operating point produces **19.9 per hour** on spin-free training-session
motion ([07-evaluation.md §5](07-evaluation.md#5-the-false-alarm-rate-stated-plainly))
— roughly two orders of magnitude worse.

The comparison is not like-for-like: our negatives are the hardest available
(an actively-cued dog seconds from spinning on command), not a representative
day, and the true all-day rate is unmeasured. But the gap is large enough that it
cannot be explained away by the mismatch, and it is the single clearest statement
of how far this prototype is from deployable.

The clinical field also has something this one lacks: **ILAE/IFCN clinical
practice guidelines for automated seizure detection using wearables, and proposed
standards for clinical validation studies adapted from QUADAS-2** [[R12](#r12)].
No equivalent exists for animal-mediated alerting. Any serious deployment of this
class of system would need one.

---

## 4. What happens after detection

This is the layer this project contributes, so the prior art matters most here —
and it is the section where an inflated novelty claim would be easiest to make
and hardest to defend.

### 4.1 Escalation is a solved problem — elsewhere

**Automatic escalation to caregivers and emergency contacts is well established
in human-worn safety devices.** Commercial medical alert systems with fall
detection route an unacknowledged alarm to a 24/7 monitoring centre with defined
escalation protocols to caregivers and emergency services. IoT fall-detection
research [[R14](#r14)] surveys the sensors, methods and architectures; concrete
systems transmit notifications with GPS coordinates to caregivers via messaging
APIs.

**We do not claim to have invented alert escalation.** The ladder in
[04-escalation-protocol.md](04-escalation-protocol.md) — acknowledge, wait,
escalate, attach location — is a recognisable pattern from this literature,
deliberately so.

### 4.2 One finding that shaped our design

Work on ambient fall detection for people with cognitive changes [[R15](#r15)]
reports that families **preferred escalation to a "circle of friends" rather than
automatic emergency dispatch**.

This is direct empirical support for a design decision we would otherwise have
had to defend on intuition: the caregiver tier between owner and emergency
services is not a convenience, it is what the people who live with these systems
actually want. It is also why
[04-escalation-protocol.md §8](04-escalation-protocol.md#8-deployment-caveats)
states that the emergency channel should point at a named human or an accredited
monitoring provider rather than dialling emergency services directly.

### 4.3 Why the false-alarm rate makes the ladder necessary

The clinical alarm literature quantifies the cost of getting this wrong.
**80–99% of ECG monitor alarms are false or clinically insignificant**
[[R16](#r16)], producing *alarm fatigue*: clinicians become desensitised, and
missed or delayed responses follow [[R17](#r17)]. The Joint Commission set a 2021
target for mitigating alarm-fatigue-related fatalities.

A system with our measured false-alarm rate that paged a caregiver directly would
manufacture alarm fatigue by design. Requiring an owner acknowledgement first
means a false positive costs one dismissal tap, and a caregiver is disturbed only
when a false positive *coincides* with an unresponsive owner — a conjunction far
rarer than either event. **The escalation architecture is the mitigation for the
detector's imprecision, not an independent feature.**

---

## 5. Deploying the model on the collar

Running inference on a microcontroller rather than streaming raw signal is
established practice. Random forests are specifically noted as suited to
extreme-edge TinyML deployment under tight memory constraints, with work on
optimising RF inference on microcontroller-class hardware [[R18](#r18)] and on
energy-adaptive forests with early-stopping [[R19](#r19)]. Deep alternatives for
activity recognition on MCUs have been examined too [[R20](#r20)], including the
question of whether microcontrollers are ready for them at all.

Our contribution here is engineering rather than novel method: a direct
Python→C transpilation of a fitted forest into 39.2 KiB of flash tables, whose
numerical agreement with scikit-learn is *measured on real data* rather than
assumed ([07-evaluation.md §7](07-evaluation.md#7-on-device-parity)). That
verification step caught a genuine float32 precision defect that would otherwise
have shipped silently.

---

## 6. The gap, and the claim

### 6.1 Capability matrix

| | [R5] Raju '23 | [R4] Brady '25 | Human wearables [R10–R13] | Fall/medical alert [R14] | Dog activity [R7–R9] | **This work** |
|---|---|---|---|---|---|---|
| Detects a *trained* alert behaviour | ✓ | ✓ | — | — | — | ✓ |
| Cross-subject generalisation | — | ✓ | partial | n/a | ✓ | ✓ ¹ |
| Pre-ictal (not post-onset) | ✓ ² | ✓ ² | — | n/a | — | ✓ ² |
| Real-time on-device inference | — | — | ✓ | ✓ | ✓ | ✓ |
| Explicit alert verification gate | — | — | partial | partial | — | **✓** |
| Escalation on owner non-response | — | — | — | ✓ | — | **✓** |
| Longitudinal alert-reliability record | — | — | — | — | partial | **✓** |
| Clinically validated | — | — | ✓ | ✓ | n/a | **—** |

¹ Under a weaker protocol than LODO; see [07-evaluation.md §1.2](07-evaluation.md#12-what-we-could-not-reconstruct).
² Inherited from the dog's alert, not independently established — see §1.3.

### 6.2 The claim

> Alert escalation is well established in human-worn safety devices, and the
> detection of trained canine signalling behaviour has been demonstrated. **We are
> not aware of a system that combines them** — that detects and verifies a
> service dog's trained alert and provides an automatic escalation path for when
> the owner cannot respond, which is the failure scenario the alert-dog training
> exists to cover.

The novelty is in the **composition and in closing a specific, named gap**, not
in either component. The clearest evidence that the gap is real is that the
authors of the detection work named the missing piece themselves and did not
build it.

### 6.3 Secondary contributions

1. **A deployable detection layer.** The published work is offline Python
   analysis. We transpile the forest to 39.2 KiB of C and verify the port
   numerically against scikit-learn on real dataset windows.
2. **A longitudinal record of alert reliability.** Given the scoping review's
   finding [[R1](#r1)] that existing accuracy figures are owner-reported and
   methodologically weak, an instrumented log of every alert, dismissal,
   acknowledgement and escalation is a route to the prospective data that review
   calls for.
3. **A negative result worth reporting.** The false-alarm rate at a usable
   sensitivity is roughly two orders of magnitude worse than
   clinically-validated human-worn devices. The source study does not report a
   comparable figure; we do.

### 6.4 What we explicitly do not claim

- **Not** that the detection method is novel. It is [[R4](#r4)]'s,
  re-implemented and re-trained.
- **Not** that alert escalation is novel. See §4.1.
- **Not** that our cross-subject results are comparable to [[R4](#r4)]'s on equal
  terms — the public release carries no dog identities.
- **Not** clinical validity, deployability, or safety.
  See [09-limitations.md](09-limitations.md).
- **Not** that a literature search proves absence. "We are not aware of" is the
  honest form.

---

## 7. References

<a id="r1"></a>**[R1]** Dog alerting and/or responding to epileptic seizures: A
scoping review. *Epilepsy & Behavior*, 2018.
[PMID 30513112](https://pubmed.ncbi.nlm.nih.gov/30513112/) ·
[PMC6279040](https://pmc.ncbi.nlm.nih.gov/articles/PMC6279040/) — *abstract and
summary only.*

<a id="r2"></a>**[R2]** Seizure response dogs: Evaluation of a formal training
program. *Epilepsy & Behavior*, 2008.
[doi:10.1016/j.yebeh.2008.09.019](https://www.sciencedirect.com/science/article/abs/pii/S1525505008001406)
— *abstract only.*

<a id="r3"></a>**[R3]** The role of trained and untrained dogs in the detection
and warning of seizures. *Epilepsy & Behavior*, 2023.
[ScienceDirect S1525505023004821](https://www.sciencedirect.com/science/article/pii/S1525505023004821)
— *abstract only.*

<a id="r4"></a>**[R4]** Brady, S.; Smeaton, A.F.; Song, H.; Ward, T.; Smeaton, A.;
Dowler, J. Development and Validation of an IMU Sensor-Based Behaviour-Alert
Detection Collar for Assistance Dogs: A Proof-of-Concept Study. *Animals* **2025**,
15(21), 3081. [doi:10.3390/ani15213081](https://doi.org/10.3390/ani15213081) ·
[PMC12607429](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12607429/) — **read in
full.**

<a id="r5"></a>**[R5]** Raju, H.; Sharma, A.; Smeaton, A.; Smeaton, A.F. Automatic
Detection of Signalling Behaviour from Assistance Dogs as they Forecast the Onset
of Epileptic Seizures in Humans. *38th ACM/SIGAPP Symposium on Applied Computing
(SAC '23)*, Tallinn, 2023. [arXiv:2303.06407](https://arxiv.org/abs/2303.06407) —
*abstract only.*

<a id="r6"></a>**[R6]** Package of motion sensor data of spin alert behaviour.
figshare.
[doi:10.6084/m9.figshare.30022441](https://doi.org/10.6084/m9.figshare.30022441)
— **the dataset used in this work.**

<a id="r7"></a>**[R7]** Dog behaviour classification with movement sensors placed
on the harness and the collar. *Applied Animal Behaviour Science*, 2021.
[ScienceDirect S0168159121001805](https://www.sciencedirect.com/science/article/pii/S0168159121001805)
— *abstract only.*

<a id="r8"></a>**[R8]** Dog activity classification with movement sensor placed on
the collar. *Fifth International Conference on Animal-Computer Interaction (ACI
'18)*. [doi:10.1145/3295598.3295602](https://dl.acm.org/doi/10.1145/3295598.3295602)
— *abstract only.*

<a id="r9"></a>**[R9]** Deep Learning Empowered Wearable-Based Behavior
Recognition for Search and Rescue Dogs. *Sensors* **2022**, 22(3), 993.
[PMC8840386](https://pmc.ncbi.nlm.nih.gov/articles/PMC8840386/) — *abstract only.*

<a id="r10"></a>**[R10]** Automated seizure detection with noninvasive wearable
devices: A systematic review and meta-analysis. *Epilepsia*, 2022.
[PMC9545631](https://pmc.ncbi.nlm.nih.gov/articles/PMC9545631/) — *abstract and
reported pooled statistics only.*

<a id="r11"></a>**[R11]** Non-electroencephalogram-based seizure detection
devices: State of the art and future perspectives. *Epilepsy & Behavior*, 2023.
[ScienceDirect S1525505023004055](https://www.sciencedirect.com/science/article/pii/S1525505023004055)
— *abstract only.*

<a id="r12"></a>**[R12]** Automated seizure detection using wearable devices:
updated systematic review and meta-analysis of tonic-clonic and focal seizure
detection. *Frontiers in Bioengineering and Biotechnology*, 2026.
[doi:10.3389/fbioe.2026.1833080](https://www.frontiersin.org/journals/bioengineering-and-biotechnology/articles/10.3389/fbioe.2026.1833080/full)
— *abstract only.*

<a id="r13"></a>**[R13]** Seizure detection using wearable electrocardiogram
connected to a smartphone: a phase 3 clinical validation study. *eBioMedicine*,
2025.
[PMC12516532](https://pmc.ncbi.nlm.nih.gov/articles/PMC12516532/) — *abstract only.*

<a id="r14"></a>**[R14]** A Survey of IoT-Based Fall Detection for Aiding Elderly
Care: Sensors, Methods, Challenges and Future Trends. *Applied Sciences* **2022**,
12(7), 3276. [doi:10.3390/app12073276](https://www.mdpi.com/2076-3417/12/7/3276)
— *abstract only.*

<a id="r15"></a>**[R15]** Feasibility of Ambient Sensing Technology for Fall
Detection in People with Cognitive Changes.
[PMC12740839](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12740839/) —
*abstract only.*

<a id="r16"></a>**[R16]** Stats on the desats: alarm fatigue and the implications
for patient safety. [PMC10357676](https://pmc.ncbi.nlm.nih.gov/articles/PMC10357676/)
— *abstract only.*

<a id="r17"></a>**[R17]** Alarm Fatigue. In *Making Healthcare Safer III: A
Critical Analysis of Existing and Emerging Patient Safety Practices*. AHRQ.
[NBK555522](https://www.ncbi.nlm.nih.gov/books/NBK555522/) — *summary only.*

<a id="r18"></a>**[R18]** Optimizing Random Forest-Based Inference on RISC-V MCUs
at the Extreme Edge. *IEEE Transactions on Computer-Aided Design of Integrated
Circuits and Systems*, 2022.
[doi:10.1109/TCAD.2022.3199903](https://dl.acm.org/doi/abs/10.1109/TCAD.2022.3199903)
— *abstract only.*

<a id="r19"></a>**[R19]** Adaptive Random Forests for Energy-Efficient Inference
on Microcontrollers. [arXiv:2205.13838](https://arxiv.org/pdf/2205.13838) —
*abstract only.*

<a id="r20"></a>**[R20]** Are Microcontrollers Ready for Deep Learning-Based Human
Activity Recognition? 2021.
[ResearchGate 355787942](https://www.researchgate.net/publication/355787942_Are_Microcontrollers_Ready_for_Deep_Learning-Based_Human_Activity_Recognition)
— *abstract only.*
