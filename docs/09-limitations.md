# Limitations

> **Research update.** Several items below have since been addressed by the
> analyses in `paper/` (see [11-research.md](11-research.md)):
> - §2.3 (operating point chosen on its own data): resolved by nested
>   cross-validation;
> - §2.2: the false-alarm rate is now also measured on continuous recordings,
>   where it is higher, not lower;
> - §3 (MPU6050 vs Shimmer3): analysed by simulation, which finds that collar
>   rotation, not sensor noise, is the dominant risk;
> - §5 ("the ladder runs on the phone"): formally model-checked, which found
>   a watchdog flaw and a heartbeat-id bug. The bug is fixed; the ladder-aware
>   watchdog is specified but not yet in the Java backend.
>
> Everything else on this page still stands.

Read this alongside the results, not after them.

---

## 1. This is not a medical device

It has not been clinically validated, holds no regulatory approval, and must not
be relied upon for medical decisions. No animals were involved in building it;
all data comes from a published release.

The single most important limitation: **a person could be harmed by trusting
this system.** Everything below is a specific way that could happen.

---

## 2. What the evaluation does not establish

### 2.1 Generalisation to an unseen dog

The public dataset carries no dog identities, so a true Leave-One-Dog-Out split
cannot be reproduced from it. We use Leave-One-Group-Out over recording groups,
which cannot guarantee that two recordings of the same dog land in different
folds ([07-evaluation.md §1.2](07-evaluation.md#12-what-we-could-not-reconstruct)).

**Our cross-subject numbers are therefore not directly comparable to the paper's,
and may be optimistic by an unknown amount.** Resolving this needs the authors'
recording-to-dog mapping — which is the single highest-value thing to ask them
for.

Even with it, the underlying dataset is six dogs, three breeds, all aged 1.5–2
years, all trained by one organisation. Nothing here evidences generalisation to
an older dog, a different breed, or a different training programme.

### 2.2 The false-alarm rate

19.9 false alarms per hour at the shipped operating point, measured on
training-session motion. Discussed at length in
[07-evaluation.md §5](07-evaluation.md#5-the-false-alarm-rate-stated-plainly).

The honest summary: the negatives in our evaluation are the hardest possible ones
(an actively-cued dog seconds away from spinning), the true all-day rate is
probably much lower, **and we have not measured it.** The authors' unlabelled
412.6 h of motion data is exactly what would be needed.

### 2.3 The operating point is chosen on the data it is reported on

The 2-of-4 @ p ≥ 0.45 policy was selected by inspecting the LOGO sweep. Its
reported sensitivity of 0.769 is therefore optimistic by an unquantified amount.
A nested cross-validation would measure the optimism; we did not run one. Treat
0.769 as an upper bound.

### 2.4 Cued behaviour in a controlled setting

Every spin in the dataset was elicited by a trainer on command. A spontaneous
seizure alert may look different — different arousal, different context,
different preceding behaviour. This limitation is inherited from the source study
and the source study says so too.

### 2.5 The verification gate's K ceiling

Sensitivity collapses at K ≥ 3 because the trained alert lasts ~2.5 s and a
window spans 2.6 s ([07-evaluation.md §4.1](07-evaluation.md#41-why-k--3-collapses)).
A trained dog that goes unacknowledged repeats its alert, which would make higher
K viable and cut false alarms substantially — but that repetition is not in this
dataset and we have not measured it.

---

## 3. What has not been run on hardware

**The firmware has never executed on an ESP32.** No board was available.

What *is* verified: the algorithmic core (features, forest, verification gate,
ring buffer) compiles as portable C and passes 240 checks against golden vectors
from the real dataset, with zero vote-decision disagreements against
scikit-learn ([07-evaluation.md §7](07-evaluation.md#7-on-device-parity)).

What is **not** verified:

| Unverified | Why it matters |
|---|---|
| Timing on real silicon | The 133-point DFT × 8 signals is estimated at a few ms; unmeasured |
| MPU6050 vs Shimmer3 | The model was trained on Shimmer3 data. The firmware converts to the same physical units, but sensor noise, DLPF response and mounting differ. **This is the most likely source of a silent accuracy loss in a real build.** |
| BLE range, reconnection, battery life | All estimated in [05-hardware.md](05-hardware.md), none measured |
| Sampling jitter | Frequency features assume a uniform 51.2 Hz |
| Enclosure, waterproofing, animal welfare in wear | Not addressed at all |

A hardware bring-up would begin by recording a dog performing cued spins with
*both* a Shimmer3 and an MPU6050 collar, and comparing the feature distributions.
If they differ materially, the model must be retrained on MPU6050 data.

---

## 4. What is not production-ready in the software

| Component | Gap |
|---|---|
| `AlertRepository` (Java) | **In-memory.** Alert history does not survive a restart. An audit log for a safety system must be durable — this is the first thing to change. The append-only JSONL store in `tools/devserver.py` is the shape it should take. |
| Notification transport | `ConsoleNotifier` prints. No SMS gateway, no delivery receipts, no carrier testing. |
| Emergency channel | Must not dial emergency services directly. Automated calls are regulated and create false-dispatch liability; point it at a named human or an accredited monitoring provider. |
| Authentication | The API key is a single shared static string. No per-relay identity, no rotation, no transport security below the API layer. |
| Privacy | Location and alert history are health-adjacent personal data. No retention policy, no subject-access mechanism, no encryption at rest. A real deployment is a GDPR data controller. |
| Phone app | The relay is a Python process, not an Android/iOS app. Background execution, doze-mode wakelocks and notification permissions are the hard part of shipping this on a real handset, and none of it is addressed. |
| `backend/` build | **Not compiled.** No Maven in this environment; the Java is syntax-checked only. The nine watchdog tests have never been executed. |

---

## 5. Design decisions that could be wrong

Stated as decisions, not facts, because reasonable people would choose otherwise.

**The ladder runs on the phone, not the cloud.** Rationale in
[02-architecture.md](02-architecture.md): the alert matters most where
connectivity is worst. The cost is that the phone is a single point of failure,
patched — not eliminated — by the backend watchdog. A cloud-first design would
trade a network dependency for a hardware one.

**T1 = 60 s.** Arbitrary. It should be set per owner with their clinician. Sixty
seconds may be far too long for someone whose seizures escalate quickly and far
too short for someone who routinely leaves their phone in another room.

**Random Forest over SVM.** SVM narrowly wins on segment F1 (0.661 vs 0.657). We
ship Random Forest for deployability, not accuracy
([07-evaluation.md §3.1](07-evaluation.md#31-segment-level)). On a platform
without the flash constraint, the choice might go the other way.

**A fixed K-of-N gate.** An adaptive threshold — per dog, per time of day, or
learned from dismissal history — would very likely beat a fixed one. Untested.

---

## 6. Ordered next steps

1. **Obtain the recording-to-dog mapping** from the authors and re-run under true
   LODO. Everything downstream depends on knowing how much §2.1 costs.
2. **Measure the false-alarm rate on all-day data** using the unlabelled 412.6 h.
   Without this the system cannot be worn.
3. **Build one collar and validate MPU6050 against Shimmer3** on the same
   behaviour.
4. **Make the backend durable** and put the alert log behind real authentication.
5. **Model the repeated alert.** A dog that repeats an unacknowledged signal
   should allow higher K and a much lower false-alarm rate — the single largest
   available accuracy win, and it needs no new sensing.
6. **Ship the relay as a real phone app**, with the background-execution work
   that implies.
7. Only then: a supervised trial with a real handler, with a clinician involved
   and the system explicitly non-load-bearing.
