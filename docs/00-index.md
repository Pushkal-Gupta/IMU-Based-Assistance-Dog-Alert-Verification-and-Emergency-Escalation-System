# Documentation index

## Reading order

**If you have five minutes** — the [root README](../README.md), then
[§7 Results](07-evaluation.md#3-results-at-a-glance).

**If you are assessing the project** — read in this order:

1. [01-project-report.md](01-project-report.md) — the full report: problem,
   related work, method, results, discussion, conclusion.
2. [09-limitations.md](09-limitations.md) — read this *before* the results, not
   after. It says what the numbers do not support.
3. [07-evaluation.md](07-evaluation.md) — every measurement, with its protocol.

**If you are building on it** —
[02-architecture.md](02-architecture.md) →
[03-detection-pipeline.md](03-detection-pipeline.md) →
[04-escalation-protocol.md](04-escalation-protocol.md) →
[05-hardware.md](05-hardware.md) → [06-api.md](06-api.md).

## Document map

| # | Document | Answers |
|---|---|---|
| 01 | [Project report](01-project-report.md) | What was built and why, end to end |
| 02 | [Architecture](02-architecture.md) | Why the escalation runs on the phone; how the three nodes divide the work |
| 03 | [Detection pipeline](03-detection-pipeline.md) | Windowing, the 159 features, selection, the four models, the verification gate |
| 04 | [Escalation protocol](04-escalation-protocol.md) | The state machine, its timers, and every failure mode it handles |
| 05 | [Hardware](05-hardware.md) | Components, wiring, pin map, power budget, cost |
| 06 | [REST API](06-api.md) | The contract between relay, backend and dashboard |
| 07 | [Evaluation](07-evaluation.md) | Protocols, results, and where they deviate from the source paper |
| 08 | [Literature](08-literature.md) | Prior art and the precise novelty claim |
| 09 | [Limitations](09-limitations.md) | What is not validated, and what would have to change |

## Where the numbers come from

No figure in this documentation is transcribed by hand. Everything traces to a
generated artifact:

| Artifact | Produced by | Consumed by |
|---|---|---|
| `ml/artifacts/results.json` | `ml/scripts/run_experiments.py` | docs 01, 03, 07 |
| `ml/artifacts/dataset_summary.json` | same | docs 03, 07 |
| `ml/artifacts/firmware_export.json` | `ml/scripts/export_firmware_model.py` | docs 03, 05 |
| `docs/figures/*.png` | `ml/scripts/make_figures.py` | docs 01, 07 |
| `firmware/collar/src/model.h` | `ml/scripts/export_firmware_model.py` | the firmware itself |

To regenerate everything:

```bash
make artifacts
```

## Conventions

- **"the paper"** always means Brady et al., *Animals* 2025, 15, 3081.
- **"the dataset"** always means the figshare release accompanying it.
- **"ours"** marks a contribution not present in that work.
- Time values in the escalation layer are **monotonic seconds**, not wall-clock;
  see [04-escalation-protocol.md §2](04-escalation-protocol.md#2-time).
