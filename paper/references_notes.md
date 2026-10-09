# references.bib — verification notes

Checked on 9 October 2026. **82 entries.** Each DOI was resolved through the Crossref REST API (`api.crossref.org/works/<doi>`). The figshare and Zenodo DOIs were resolved through DataCite. Abstracts came from PubMed E-utilities or the Crossref abstract field, and in a few cases from PMC/Europe PMC full text. URL-only entries were checked to return HTTP 200 with the stated title.

**Depth legend.**
- *full text*: the relevant passage was read in the full text (PMC/Europe PMC).
- *abstract*: the abstract was read.
- *metadata*: only the bibliographic record was checked (title, authors, venue, volume, pages). The DOI resolves to the stated work, but its content was not read in this pass.

Numbers in the "finding" column appear only where they were seen in the abstract or full text.

---

## A. Corrections to `docs/08-literature.md` (important)

| Ref | What the doc says | What is actually true | Severity |
|---|---|---|---|
| **R1** | "*Epilepsy & Behavior*, 2018" | The paper is in **PLoS ONE** 13(12): e0208280, 2018, doi:10.1371/journal.pone.0208280. Authors: Catala, Cousillas, Hausberger, Grandgeorge. The PMID/PMC links in the doc are correct; only the journal name is wrong. | **Wrong journal** |
| R1 | Accuracy "70–85%" | The abstract says "accuracy from **≥70% to 85%** according to owner reports". Lead time 10 s–5 h is correct. Only **5 of 28** studies qualified for inclusion (1 prospective, 4 questionnaires). | minor wording |
| **R2** | doi:10.1016/j.yebeh.2008.**09.019** | That DOI resolves to a **different paper** (Ablah et al., "Exercise and epilepsy: A survey of Midwest epilepsy patients", Epilepsy Behav 14(1)). The correct DOI is **10.1016/j.yebeh.2008.05.011** (Kirton, Winter, Wirrell, Snead; Epilepsy Behav 13(3):499–504, 2008). The ScienceDirect PII link in the doc is correct. | **Wrong DOI** |
| R2 | Barking/whining 95%, licking 50%, anxious 41% | **Not in the abstract.** The abstract gives n=22 (88% response), spontaneous alerting in **59%** (confirmed), and emergency-response-system activation by the dog in **27%**. The behaviour percentages could not be verified without the paywalled full text. Keep them out of the paper unless someone checks the full text. | unverified numbers |
| **R3** | "*Epilepsy & Behavior*, **2023**" | Issue year is **2024**: vol. 150, 109563 (Jan 2024; online 9 Dec 2023). Authors: Luff, Belluomo, Lugarà, Walker. | wrong year (for citation) |
| R4 | Ward, T. | The author is Tomás Ward. All other metadata is correct. | trivial |
| R5 | arXiv only | Published version: *Proc. 38th ACM/SIGAPP SAC*, pp. 585–592, doi:10.1145/3555776.3577656. 11 dogs and 107 days confirmed from the arXiv abstract. The abstract gives **no performance figures**. The limitations attributed to R5 are Brady et al.'s characterisation, as the doc already says. | add DOI |
| R6 | no authors | DataCite lists the creators as **Song, Hailin; Brady, Shelley; Smeaton, Alan**, figshare, 2025, resource type Dataset. | add authors |
| R7 | 91% vs 75% | **Confirmed** from the abstract: back/harness sensor "up to 91%", collar "75% at best". 45 dogs; adding the gyroscope improved accuracy by 0.7–2.6%. Authors: Kumpulainen et al., AABS 241:105393. | OK |
| R8 | — | Kumpulainen et al., ACI '18, pp. 1–6. Metadata confirmed. | OK |
| R9 | — | Kasnesis et al., Sensors 22(3):993. Confirmed. The abstract reports F1 > 99% for victim-spotting in two SaR scenarios, with CNN models deployed on the wearable. | OK |
| **R10** | "accelerometry-based … pooled sensitivity 93% (95% CI 85–99%), FAR 2.5/24 h (95% CI 1.95–3.1)" | The numbers are correct (confirmed in the PMC full text), but they are the **wrist-worn (wrist/ankle accelerometry) subgroup**. The headline **overall** figures are sensitivity **0.91 (0.85–0.96)** and FAR **2.1/24 h (1.7–2.6)** across 23 studies. Surface EMG: 0.90 (0.71–1.00), 0.96/24 h (0.25–1.66). Say "wrist-worn subgroup" in the paper. Authors: Naganur et al., Epilepsia 63(8):1930–1941. | needs qualification |
| R11 | 79.4–96%, 0.20–1.92/24 h | **Confirmed** (abstract). These figures apply only to devices with **phase-3/4 evidence** for tonic-clonic/major motor seizures (accelerometry, sEMG, or ACM+HR). The rate is also "0–0.03 per night". Authors: Meritam Larsen & Beniczky. | OK; add the phase qualifier |
| **R12** | "ILAE/IFCN clinical practice guidelines … and proposed standards … adapted from QUADAS-2 [R12]" | R12 (Mohamed, Shaikh, Piaggio 2026) is a meta-analysis. The **guideline** is **Beniczky et al. 2021** (`beniczky2021ilae`) and the **validation standards** are **Beniczky & Ryvlin 2018** (`beniczky2018standards`). Cite those primary sources. R12's own numbers (abstract): TCS pooled sensitivity **89.9% (85.0–93.9)**, FAR **1.43/24 h (1.22–1.64)**; focal sensitivity **73.5%**, FAR **2.85/24 h**. The doc says R12 "revisits both figures" but gives none. | misattribution |
| R13 | — | Jeppesen et al., eBioMedicine 120:105952, 2025. Abstract: sensitivity **90.5% (77.4–97.3)** over 42 seizures; mean FAR **2.5/day**, zero at night. A smartphone behavioural test **cancelled all false alarms**, which is directly relevant to our acknowledgement gate. | OK |
| R14 | — | Karar, Shehata, Reyad; Appl. Sci. 12(7):3276. Metadata confirmed. | OK |
| **R15** | presented as a study | This is a **conference abstract** (Alzheimer's & Dementia 21(S4):e101697, 2025, AAIC supplement; Ferguson et al.), not a peer-reviewed full paper. The "circle of friends" finding is **confirmed: 24 of 25 families** preferred escalation to the circle of friends over automatic 911 dispatch. n=25 participants in 23 homes. Cite it as an abstract. | flag as abstract |
| **R16** | "80–99% of ECG monitor alarms are false or clinically insignificant [R16]" | **Not supported by R16.** Anderson et al. (BMJ Open Qual 12(3):e002262, 2023) is a single-site Mayo Clinic QI project on SpO₂ (Masimo) alarms. Its text says "**more than 70%** of alarms could be false". Its own baseline was **55–85%** false notifications, and the intervention cut alarms by 16.92% (p = 0.25, not significant). The Joint Commission 2021 statement is in R16. I could not find the 80–99% figure in any source I read. The commonly quoted range from Sendelbach & Funk 2013 is "72–99%", but I could not confirm it from primary text (no PubMed abstract; secondary sources disagree). **Remove the 80–99% figure or verify it from a primary full text.** | **unsupported number** |
| R17 | AHRQ chapter, no authors | NCBI Bookshelf NBK555522 is chapter 13, "Alarm Fatigue", in *Making Healthcare Safer III* (Hall KK, Shoemaker-Hunt S, Hoffman L, et al.; AHRQ, Rockville MD, March 2020). The chapter-level authors could not be retrieved (Bookshelf returned a reCAPTCHA wall), so the entry uses the corporate author. | partial |
| R18 | — | Tabanelli, Tagliavini, Benini; IEEE TCAD 41(11):4516–4526, 2022. Metadata confirmed. | OK |
| R19 | arXiv:2205.13838 only | Published version: Daghero et al., *VLSI-SoC 2021*, pp. 1–6, doi:10.1109/VLSI-SoC53125.2021.9606986 (the arXiv journal-ref confirms this). | add DOI |
| R20 | ResearchGate link, "2021" | The paper is **Elsts & McConville, *Electronics* 10(21):2640, 2021**, doi:10.3390/electronics10212640. Abstract: RF achieves accuracy similar to a small CNN while being "several times faster"; both are orders of magnitude faster than state-of-the-art deep models. Replace the ResearchGate link with the DOI. | add DOI |

Also check the claim in doc §1.2, cited to Brady et al., of "canine identification of pre-clinical seizure VOCs at ~82% accuracy". The primary source (Maa et al. 2021) reports **82.2% probability that a positive detection predicts a seizure**, a PPV-like figure (OR 4.60, 95% CI 0.98–21.69, so the CI crosses 1). Dogs detected the scent before 78.7% of seizures, and ictal-versus-interictal discrimination was 93.7%. "~82% accuracy" is a loose paraphrase. Cite `maa2021voc` directly and use the exact wording.

## B. Unresolved / caveated items

- **None fully UNRESOLVED.** Every entry resolves.
- **R2 behaviour percentages** (95% / 50% / 41%): unverifiable from the abstract (paywalled).
- **R16 "80–99%"**: not found in R16 or anywhere else checked (see A).
- **R17 chapter authors**: not retrieved, so the corporate author is used.
- **Sendelbach & Funk 2013** content: metadata only. The DOI resolves; Crossref gives the short title "Alarm Fatigue", and the full title "Alarm fatigue: a patient safety concern" comes from widely cited records. There is no PubMed abstract, so no numbers are taken from it.
- **Hussain et al. 2022**: the task brief suggested a *Sensors* 2022 paper by Hussain on dog activity. **No such Sensors paper was found.** The verifiable Hussain et al. 2022 dog-activity paper is in **Applied Sciences** 12(19):9427 (LSTM, accelerometer + gyroscope), and that is the one included. Do not cite it as *Sensors*.
- **"Ryvlin et al. 2018 Lancet Neurol wearable devices"** (task brief): no such Lancet Neurology paper was found. The verifiable 2018 Ryvlin wearable paper is *Epilepsia* 59(S1):61–66 (`ryvlin2018wearable`). The Ryvlin Lancet Neurology paper is MORTEMUS (2013).
- **"Ziyabari et al. 2019" OVLP metrics**: the archival, citable version is **Shah, Golmohammadi, Obeid, Picone 2021**, a Springer book chapter (`shah2021metrics`). The earlier Ziyabari et al. arXiv preprint was not added.
- **"Byrne et al." assistance-dog technology**: resolved to Byrne et al. 2014, *IEEE Pervasive Computing* 13(2):80–83.
- **emlearn**: cited as the Zenodo software record (Nordby 2019; DataCite lists the sole creator as Jon Nordby). A peer-reviewed JOSS paper exists for emlearn-*micropython* (2025, doi:10.21105/joss.09093), but that is a different package and was not used.
- **micromlgen**: there is no paper; it is a GitHub URL only (HTTP 200).
- **MPU-6050 datasheet**: the URL returns 200 but serves an HTML redirect, so it could not be parsed programmatically. Rev. 3.4 (PS-MPU-6000A-00, 19 Aug 2013) was confirmed via several mirrors. If needed, add a university mirror such as the courses.cs.washington.edu copy.
- **PyTorch**: page numbers were omitted because they were not shown on the NeurIPS proceedings page. The author list matches the proceedings page.
- **SzCORE**: online 2024, but the issue is **Epilepsia 66(S3):14–24, 2025**. Cite it as 2025.
- **Bibliography size**: 82 entries is above the ~45–55 target, because the requested topic list alone needed about 60. Every entry is verified, and BibTeX prints only what is cited. Candidates to drop if space is tight: `cameron2008cluster`, `mubashir2013fall`, `mcnemar1947`, `strong1999sad`, `jiang2012pacemaker`, `karar2022fall`, `anderson2023desats`.

---

## C. Per-entry table

| Key | Key finding relevant to this paper | Verified at | Depth |
|---|---|---|---|
| brady2025collar | Source study: Shimmer3 IMU collar, 6 dogs, 135 spin events; RF best (LODO F1 0.65, AUC 0.70 per docs); offline only, with transmission named as future work | https://doi.org/10.3390/ani15213081 | metadata (project docs report full text read) |
| raju2023signalling | Predecessor: collar accelerometer, 11 trained dogs, 107 days; ML separates signalling from routine behaviour; no figures in abstract | https://doi.org/10.1145/3555776.3577656 ; arXiv:2303.06407 | abstract |
| song2025figshare | Public annotated spin-alert IMU dataset used in this work (creators Song, Brady, Smeaton) | https://doi.org/10.6084/m9.figshare.30022441 | metadata (DataCite) |
| catala2018scoping | Only 5/28 studies met PRISMA inclusion; alert lead 10 s–5 h; owner-reported accuracy ≥70–85%; rigour "generally poor" | https://doi.org/10.1371/journal.pone.0208280 | abstract |
| kirton2008srd | 22 SRD graduates; spontaneous alerting developed in 59%; dog activated an emergency response system in 27% | https://doi.org/10.1016/j.yebeh.2008.05.011 | abstract |
| luff2024dogs | Review: trained and untrained dogs; VOC evidence; lack of controlled prospective studies; inconsistent alert timings | https://doi.org/10.1016/j.yebeh.2023.109563 | abstract |
| strong1999sad | Early report: Support Dogs-trained dogs gave overt signals 15–45 min before seizures (uncontrolled) | https://doi.org/10.1053/seiz.1998.0250 | abstract |
| brown2011sad | "No rigorous data exist" on whether SAD prediction beats chance or on false-positive/negative rates | https://doi.org/10.1016/j.eplepsyres.2011.10.019 | abstract |
| catala2019odour | Trained dogs discriminated a general seizure odour across individuals and seizure types | https://doi.org/10.1038/s41598-019-40721-4 | abstract |
| maa2021voc | Ictal vs interictal sweat: 93.7% correct; scent present before 78.7% of seizures; 82.2% probability a positive predicts a seizure; mean warning phase 68.2 min | https://doi.org/10.1016/j.yebeh.2020.107690 | abstract |
| ladha2013dogslife | Early collar-accelerometer activity recognition for dogs (UbiComp '13) | https://doi.org/10.1145/2493432.2493519 | metadata |
| kumpulainen2018collar | Collar-mounted movement-sensor dog activity classification (ACI '18) | https://doi.org/10.1145/3295598.3295602 | metadata |
| kumpulainen2021harness | 45 dogs; harness sensor up to 91% vs collar 75% at best; gyroscope adds 0.7–2.6%; static postures hardest from the collar | https://doi.org/10.1016/j.applanim.2021.105393 | abstract (via JYX repository) |
| chambers2021deep | Single collar accelerometer, >2500 dogs; drinking sens/spec 0.949/0.999, eating 0.988/0.983; collar position had no measurable impact | https://doi.org/10.3390/ani11061549 | abstract |
| kasnesis2022sar | On-device CNNs (acc+gyro+audio) for search-and-rescue dogs; real-time alerting to rescuers; F1 > 99% in two scenarios | https://doi.org/10.3390/s22030993 | abstract |
| hussain2022lstm | LSTM on neck/tail acc+gyro, 10 dogs, 10 behaviours (Applied Sciences, not Sensors) | https://doi.org/10.3390/app12199427 | metadata (+ search summary) |
| mancini2011aci | Founding manifesto of Animal-Computer Interaction | https://doi.org/10.1145/1978822.1978836 | metadata |
| jackson2013fido | FIDO: wearable dog-activated interfaces for working/assistance dogs | https://doi.org/10.1145/2493988.2494334 | metadata |
| byrne2014twoway | Two-way communication between working dogs and handlers via wearables | https://doi.org/10.1109/MPRV.2014.38 | metadata |
| burns2010shimmer | SHIMMER wireless sensor platform (the IMU used by Brady et al.) | https://doi.org/10.1109/JSEN.2010.2045498 | metadata |
| invensense2013mpu6000 | MPU-6000/6050 product specification Rev 3.4 (our collar IMU) | https://invensense.tdk.com/wp-content/uploads/2015/02/MPU-6000-Datasheet1.pdf | metadata |
| beniczky2021ilae | ILAE–IFCN CPG: high evidence for GTCS/FBTCS detection; recommends clinically validated devices especially in unsupervised patients; does not recommend devices for other seizure types | https://doi.org/10.1111/epi.16818 (co-pub. https://doi.org/10.1016/j.clinph.2020.12.009) | abstract |
| beniczky2018standards | Phase 0–4 framework and reporting standards for seizure-detection-device validation | https://doi.org/10.1111/epi.14049 | abstract |
| ryvlin2018wearable | GTCS-triggered alarms enable caregiver intervention likely to reduce SUDEP odds | https://doi.org/10.1111/epi.14054 | abstract |
| naganur2022meta | 23 studies: overall sens 0.91, FAR 2.1/24 h; wrist-worn 0.93 (0.85–0.99), 2.5/24 h (1.95–3.1) | https://doi.org/10.1111/epi.17297 | full text (PMC9545631) |
| meritamlarsen2023nonEEG | Phase-3/4 devices: sensitivity 79.4–96%, FAR 0.20–1.92/24 h (0–0.03/night) | https://doi.org/10.1016/j.yebeh.2023.109486 | abstract |
| mohamed2026updated | 31 TCS studies: sens 89.9%, FAR 1.43/24 h; focal sens 73.5%, FAR 2.85/24 h | https://doi.org/10.3389/fbioe.2026.1833080 | abstract |
| jeppesen2025ecg | Phase-3 ECG + smartphone: sens 90.5%; FAR 2.5/day (0 at night); smartphone behavioural test cancelled all false alarms | https://doi.org/10.1016/j.ebiom.2025.105952 | abstract |
| regalia2019empatica | Embrace/E4: GTCS sens 92–100%; FAR fell from ~2 to 0.2–1/day inpatient; outpatient FAR from ~6 to <0.5 | https://doi.org/10.1016/j.eplepsyres.2019.02.007 | abstract |
| arends2018nightwatch | NightWatch (HR + ACM), 28 participants, 1826 nights: median sens 86%; PPV 49% | https://doi.org/10.1212/WNL.0000000000006545 | abstract |
| dan2025szcore | SzCORE: standardised datasets, CV strategies and event-based metrics for seizure-detection validation | https://doi.org/10.1111/epi.18113 | abstract |
| shah2021metrics | Objective event-level scoring metrics for EEG event detection (cite for any-overlap/OVLP scoring; confirm the OVLP section in full text before quoting) | https://doi.org/10.1007/978-3-030-67494-6_8 | metadata |
| ryvlin2013mortemus | 16 SUDEP in EMUs (14 at night); terminal apnoea within 11 min post-GTCS; SUDEP aggravated by suboptimal supervision | https://doi.org/10.1016/S1474-4422(13)70214-X | abstract |
| vanderlende2018nocturnal | 60 SUDEP cases: nocturnal convulsions 77% vs 33% of controls; the centre with the lowest supervision had the highest SUDEP incidence | https://doi.org/10.1212/WNL.0000000000006356 | abstract |
| sveinsson2020sudep | GTCS OR 26.81; living alone OR 5.01; not sharing a bedroom with GTCS OR 67.10; 69% of such SUDEP potentially preventable by night supervision | https://doi.org/10.1212/WNL.0000000000008741 | abstract |
| sendelbach2013alarm | Alarm fatigue as a patient-safety concern (AACN) | https://doi.org/10.4037/NCI.0b013e3182a903f9 | metadata |
| cvach2012alarm | Integrative review (72 articles): desensitisation driven by high false-alarm rates and poor PPV | https://doi.org/10.2345/0899-8205-46.4.268 | abstract |
| anderson2023desats | ">70% of alarms could be false"; local baseline 55–85% false; Joint Commission 2021 target | https://doi.org/10.1136/bmjoq-2023-002262 | full text (Europe PMC) |
| ahrq2020alarm | AHRQ evidence review chapter on alarm-fatigue patient-safety practices | https://www.ncbi.nlm.nih.gov/books/NBK555522/ | metadata (Bookshelf esummary) |
| igual2013fall | Fall-detection review; challenges in real-life performance, usability, acceptance | https://doi.org/10.1186/1475-925X-12-66 | abstract |
| mubashir2013fall | Survey of fall-detection principles and approaches | https://doi.org/10.1016/j.neucom.2011.09.037 | metadata |
| karar2022fall | IoT fall-detection survey (sensors, methods, architectures) | https://doi.org/10.3390/app12073276 | metadata |
| fleming2008floor | People >90: 80% of fallers could not get up; 30% lay ≥1 h; call alarms widely available but mostly **not used** in long lies | https://doi.org/10.1136/bmj.a2227 | abstract |
| ferguson2025ambient | 24/25 families preferred "circle of friends" escalation to automatic 911 dispatch (conference abstract) | https://doi.org/10.1002/alz70858_101697 | full text of abstract (Europe PMC) |
| aringhieri2017ems | Broad OR review of EMS (location, dispatch, simulation) | https://doi.org/10.1016/j.cor.2016.09.016 | metadata |
| sancheziborra2020tinyml | TinyML overview: challenges and opportunities for frugal smart objects | https://doi.org/10.1109/MCAS.2020.3005467 | metadata |
| banbury2021mlperftiny | MLPerf Tiny: first industry-standard TinyML benchmark (accuracy, latency, energy; 4 tasks) | NeurIPS D&B 2021 proceedings URL; arXiv:2106.07597 | abstract |
| tabanelli2022rf | RF inference optimisation on RISC-V MCUs | https://doi.org/10.1109/TCAD.2022.3199903 | metadata |
| daghero2021adaptive | Energy-adaptive RF with early stopping on MCUs | https://doi.org/10.1109/VLSI-SoC53125.2021.9606986 | metadata (arXiv record) |
| elsts2021mcu | HAR on MCUs: RF matches small-CNN accuracy and is several times faster | https://doi.org/10.3390/electronics10212640 | abstract |
| nordby2019emlearn | C99 inference engine for scikit-learn-style models on microcontrollers | https://doi.org/10.5281/zenodo.2589394 | metadata (DataCite) |
| micromlgen | Python→C code generator for sklearn classifiers on MCUs | https://github.com/eloquentarduino/micromlgen | metadata |
| um2017augmentation | Data augmentation of wearable IMU data for CNN training (cite for rotation/jitter-style augmentation; specific transforms not re-read here) | https://doi.org/10.1145/3136755.3136817 | metadata |
| stisen2015smart | Cross-device sensing heterogeneity degrades HAR and must be assessed and mitigated (title-level claim) | https://doi.org/10.1145/2809695.2809718 | metadata |
| ordonez2016deepconvlstm | DeepConvLSTM baseline for wearable HAR | https://doi.org/10.3390/s16010115 | metadata |
| wang2019deephar | Survey of deep learning for sensor-based HAR | https://doi.org/10.1016/j.patrec.2018.02.010 | metadata |
| dempster2020rocket | ROCKET random-convolution-kernel time-series classifier | https://doi.org/10.1007/s10618-020-00701-z | metadata |
| dempster2021minirocket | MiniRocket, a fast near-deterministic variant | https://doi.org/10.1145/3447548.3467231 | metadata |
| breiman2001rf | Random forests | https://doi.org/10.1023/A:1010933404324 | metadata |
| delong1988roc | Nonparametric comparison of correlated ROC AUCs | https://doi.org/10.2307/2531595 | metadata |
| efron1993bootstrap | Bootstrap textbook | https://doi.org/10.1007/978-1-4899-4541-9 | metadata |
| field2007clustered | Bootstrap schemes for clustered data (resample clusters) | https://doi.org/10.1111/j.1467-9868.2007.00593.x | metadata |
| cameron2008cluster | Cluster bootstrap inference with few clusters | https://doi.org/10.1162/rest.90.3.414 | metadata |
| varma2006bias | CV error of a CV-tuned classifier is substantially biased; nested CV gives a near-unbiased estimate | https://doi.org/10.1186/1471-2105-7-91 | abstract |
| cawley2010overfitting | Model-selection over-fitting biases performance estimates | https://www.jmlr.org/papers/v11/cawley10a.html | metadata (JMLR page) |
| holm1979 | Holm step-down multiple-testing correction | https://www.jstor.org/stable/4615733 | metadata |
| dietterich1998tests | McNemar and 5×2 CV tests for comparing classifiers | https://doi.org/10.1162/089976698300017197 | metadata |
| mcnemar1947 | McNemar test for paired proportions | https://doi.org/10.1007/BF02295996 | metadata |
| wilcoxon1945 | Wilcoxon signed-rank test | https://doi.org/10.2307/3001968 | metadata |
| clopper1934 | Exact binomial CI | https://doi.org/10.1093/biomet/26.4.404 | metadata |
| garwood1936 | Exact Poisson CI (for false-alarm rates per hour) | https://doi.org/10.1093/biomet/28.3-4.437 | metadata |
| lamport2002specifying | TLA+ language and tools (book; ISBN 978-0-321-14306-8) | https://lamport.azurewebsites.net/tla/book.html | metadata |
| yu1999tlc | TLC explicit-state model checker for TLA+ (CHARME 1999, LNCS 1703) | https://doi.org/10.1007/3-540-48153-2_6 | metadata |
| newcombe2015aws | Industrial use of TLA+/formal methods at AWS | https://doi.org/10.1145/2699417 | metadata |
| jee2010pacemaker | Model-checked timed automata (pacemaker VVI/DDI case study), code generation, timing-deviation handling | https://doi.org/10.1109/RTCSA.2010.42 | metadata (+ UPenn repository summary) |
| jiang2012pacemaker | Formal modelling and verification of a dual-chamber pacemaker (TACAS 2012, LNCS 7214) | https://doi.org/10.1007/978-3-642-28756-5_14 | metadata |
| claessen2000quickcheck | QuickCheck property-based random testing | https://doi.org/10.1145/351240.351266 | metadata |
| maciver2019hypothesis | Hypothesis property-based testing for Python | https://doi.org/10.21105/joss.01891 | metadata |
| pedregosa2011sklearn | scikit-learn | https://www.jmlr.org/papers/v12/pedregosa11a.html | metadata |
| harris2020numpy | NumPy | https://doi.org/10.1038/s41586-020-2649-2 | metadata |
| virtanen2020scipy | SciPy 1.0 | https://doi.org/10.1038/s41592-019-0686-2 | metadata |
| paszke2019pytorch | PyTorch | NeurIPS 2019 proceedings URL | metadata |
