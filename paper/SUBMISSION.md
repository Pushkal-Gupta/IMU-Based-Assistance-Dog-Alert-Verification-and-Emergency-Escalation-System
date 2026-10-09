# Submission guide

**Target journal:** MDPI *Sensors*, article type "Article".
**Manuscript:** `paper/main.tex`, built to `paper/build/main.pdf` by `make paper`.

---

## 1. Why *Sensors*

| Criterion | *Sensors* |
|---|---|
| Scope fit | Wearable and inertial sensing, IoT health systems and embedded ML are core topics. The source study (Brady et al.) is also MDPI (*Animals*), which helps reviewer matching. |
| What reviewers will value here | A reproducible secondary analysis, an honest negative result (the false-alarm gap), formal verification, and an end-to-end system. All are acceptable in *Sensors*; hardware validation is not mandatory for a methods/system paper that states its limits. |
| Speed | Typically a few weeks to first decision. |
| Cost | Open access, with an article processing charge (APC) payable only on acceptance. A Sensors special-issue page and third-party sources list **CHF 2,600**; one source lists CHF 2,400. **Check the current figure on the journal's APC page before submitting.** MDPI offers discounts through institutional open-access programmes (IOAP) and considers waivers on request, so ask your institution's library. |
| Standing | Impact factor 3.5 (2024 JCR, released June 2025), Q2 in its categories. Check Clarivate for the 2025 JCR. |

### Fallback venues, in order

1. **IEEE Access.** Broad scope, single-round review, APC ≈ US$1,995. Cut to about 10 pages; keep the formal-verification and false-alarm-requirement results.
2. ***Animals* (MDPI)**, the source study's venue. Reframe for animal-welfare and assistance-dog readers: shorten the formal-methods section and lead with the dog-repetition and false-alarm findings.
3. **ACM Animal-Computer Interaction (ACI) conference.** Best topical fit; registration fee instead of an APC. Submit a short paper on the escalation/false-alarm requirement, and the full journal version elsewhere afterwards. *Check that the conference's prior-publication policy allows this.*

---

## 2. Before you submit: author TODO list

These need your input. Each is marked `TODO(authors)` in the source; `grep -rn "TODO(authors)" paper/` finds them all.

- [ ] **Author names and order.** The manuscript uses "Pushkal Gupta and Vanka Kaushik", and citations as "Gupta, P.; Kaushik, V.". If Vanka is the family name, change `\AuthorCitation` to "Vanka, K." and `\Author` accordingly.
- [ ] **Affiliations**: department, institution, city, postcode and country for each author, plus e-mail addresses.
- [ ] **ORCID iDs**: add `\newcommand{\orcidauthorA}{…}` and `\orcidA{}` after each name.
- [ ] **CRediT contributions.** The current roles are a placeholder; edit them to reflect who did what.
- [ ] **GenAI disclosure.** Methods (§3.10 "Use of generative AI") and the Acknowledgments both disclose AI assistance. Check them against MDPI's current ethics page (mdpi.com/ethics) and edit them to describe your use accurately. Also state it in the cover letter, which already does.
- [ ] **Public code and data.**
  1. Push the repository to a public host (GitHub).
  2. Archive a release on Zenodo to get a DOI.
  3. Put both in the Data Availability statement.
- [ ] **Suggested reviewers.** MDPI asks for 3–5, with no conflicts and from different institutions. Suggested profiles, to be filled with names you check yourself:
  - a researcher in canine wearable or behaviour sensing (animal–computer interaction);
  - a researcher in wearable seizure detection or its validation;
  - a researcher in formal methods for safety-critical or medical systems;
  - a researcher in TinyML or embedded inertial sensing.

  Do not suggest the source study's authors, who have a conflict of interest as dataset providers. You may instead list them as people to inform.
- [ ] **Optional but recommended:** email the source study's authors, who released the dataset, before submission.
  - Tell them about the 51.2 Hz rate finding and the gyroscope saturation.
  - Ask for the recording-to-dog mapping. A true leave-one-dog-out rerun would remove the single largest threat to validity.
  - A short acknowledgement of their reply would strengthen the paper.

---

## 3. MDPI checklist

- [x] MDPI LaTeX template (`Definitions/`, unmodified), `sensors` journal option, `submit` mode with line numbers
- [x] Abstract ≤ 200 words, single paragraph, no headings
- [x] Keywords (3–10)
- [x] Sections: Introduction, Related Work, Materials and Methods, Results, Discussion, Conclusions
- [x] Back matter: Supplementary Materials, Author Contributions, Funding, IRB statement (not applicable, secondary data; the source study's approvals are cited), Informed Consent, Data Availability, Acknowledgments, Conflicts of Interest, Abbreviations, Appendix
- [x] Generative-AI use disclosed in Materials and Methods and Acknowledgments
- [x] References: 72 entries, each verified against its DOI or a stable URL (`references_notes.md`); MDPI BibTeX style
- [x] Figures as vector PDFs (`figures/`), each cited in the text; tables are generated
- [x] Supplementary files (`supplementary/`): Tables S1–S3 (CSV), File S1 (TLA⁺ spec), File S2 (simulation assumptions)
- [ ] Author details, ORCID, CRediT, public repository and DOI (§2)
- [ ] Cover letter: fill in names and affiliations in `cover_letter.md`

### What to upload

1. `main.tex`, `references.bib`, `sections/`, `figures/`, `generated/` and `Definitions/`. These are the LaTeX sources; MDPI recompiles them.
2. `build/main.pdf` (the PDF build of the manuscript).
3. The contents of `supplementary/`, zipped.
4. The cover letter.

---

## 4. Likely reviewer questions, and where the answer is

| Question | Answer in the paper |
|---|---|
| "Never run on hardware." | Stated in the Abstract and Limitations. The host-verified C core, the simulated transfer (§4.5) and the explicit ESP32 non-claim pre-empt it. |
| "Leave-one-group-out is not leave-one-dog-out." | §3.2 and Limitations. The session- and device-shift protocols (Table 4) bound it, and the mapping request is listed as future work. |
| "Simulation parameters are made up." | Table 2 labels them as assumptions. The sensitivity analysis (§4.4) shows the conclusions are structural. |
| "Why not deep learning?" | CNN and ROCKET baselines (Table 3), and the discussion of data size. |
| "Small dataset, overlapping CIs." | Cluster-bootstrap intervals everywhere; the paper explicitly declines to rank models (§4.1). |
| "Is the formal model faithful to the code?" | Property-based conformance tests with 10,000 examples per property. The model-to-code cross-check found a real bug (§4.3). |

---

## 5. Reproducing everything

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-lock.txt
brew install tectonic ghostscript      # for the PDF only
make all-research                       # ~25 min on 8+ cores
```

Download the dataset (figshare 30022441) into `spinning_dataset/` first.
