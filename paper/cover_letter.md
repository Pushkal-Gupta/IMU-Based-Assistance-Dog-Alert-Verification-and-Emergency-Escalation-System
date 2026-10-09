<!-- TODO(authors): fill the bracketed fields, date it on the day you submit, and paste into the MDPI submission system or export to PDF. -->

[Date]

The Editor-in-Chief
*Sensors*, MDPI

Dear Editor,

We submit the manuscript **"Closing the Loop on Assistance-Dog Seizure Alerts: An IMU Collar with Streaming Verification, Formally Verified Escalation and a Quantified False-Alarm Requirement"** for consideration as an Article in *Sensors*.

Trained seizure-alert assistance dogs signal an oncoming seizure. Recent work published in MDPI *Animals* showed that a collar-mounted inertial sensor can detect such a trained alert, but it stopped at detection. The situation the dog is trained for is one in which the owner may be unable to perceive the alert. This manuscript builds and evaluates the missing half: a streaming verification gate on an ESP32 collar, an owner → caregiver → emergency escalation ladder on the owner's phone, and a backend watchdog. We evaluate the complete chain with methods chosen to expose its weaknesses, and the results include a negative one.

The main findings are:

- **Continuous-recording evaluation changes the picture.** Evaluated with nested operating-point selection on continuous recordings, the detector produces 2.7 times the false alarms implied by the curated-clip protocol used in prior work.
- **Model checking found real defects.** A TLA⁺ specification, checked with TLC and tied to the code by property-based tests, confirms the escalation protocol's safety properties. It also exposed a watchdog design flaw, which we fix and re-verify, and an integration bug that had silently disabled the watchdog.
- **The required false-alarm rate is now quantified.** A Monte-Carlo simulation that drives the real escalation engine derives the false-alarm rate needed to keep the burden on caregivers acceptable: three orders of magnitude below the rate we measure. We propose it as a concrete target for this application.

We believe the work suits *Sensors* because it combines wearable inertial sensing, embedded machine learning and dependable IoT system design, with a fully reproducible pipeline: every number and figure in the manuscript is regenerated from the public dataset by one command. The paper makes no clinical claims and states plainly what has not been validated, including on-device execution and all-day wear.

This manuscript has not been published and is not under consideration elsewhere. All authors have approved the submission and declare no conflicts of interest. The study is a secondary analysis of a public, de-identified dataset, and no animals or humans were involved. In line with MDPI policy, we disclose that a large language model assisted with software implementation, reference verification and drafting, as described in the Materials and Methods and Acknowledgments. The authors verified all content and take full responsibility for it.

Code, the formal specification, the simulation and all artifacts are available at [repository URL / Zenodo DOI].

Yours sincerely,

Pushkal Gupta (corresponding author), [affiliation], pushkalgupta2005@gmail.com
Vanka Kaushik, [affiliation]
