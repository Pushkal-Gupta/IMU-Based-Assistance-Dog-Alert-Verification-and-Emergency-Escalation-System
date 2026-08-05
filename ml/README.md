# `ml` — the detection layer

Reproduces the spin-alert detection pipeline of Brady et al. (*Animals* 2025, 15,
3081) on their released dataset, and adds the verification gate the escalation
layer depends on.

## Package

| Module | Purpose |
|---|---|
| `config.py` | Every tunable that appears in the report, so docs and code cannot drift |
| `dataset.py` | Loading the figshare pickles, event curation, the NumPy 2 unpickle shim |
| `segmentation.py` | 2.6 s windows, 1.3 s stride |
| `features.py` | 159 features — the reference the C firmware must match |
| `selection.py` | Three-stage selector, fitted inside each CV fold |
| `models.py` | Four classifiers plus the heuristic baseline |
| `verification.py` | The K-of-N gate (ours) |
| `evaluate.py` | Within-subject, leave-one-group-out, event-level protocols |
| `export.py` | Transpiles a fitted forest to C |
| `plotting.py` | Shared figure style |

## Scripts

```bash
python ml/scripts/run_experiments.py        # -> artifacts/results.json  (~20 s)
python ml/scripts/export_firmware_model.py  # -> firmware/collar/src/model.h
python ml/scripts/make_firmware_vectors.py  # -> firmware/test/vectors.bin
python ml/scripts/make_figures.py           # -> docs/figures/
```

## Tests

```bash
python -m pytest ml/tests -q     # 90 tests
```

Notable ones:

- `test_annotation_count_matches_publication` — the release really does contain
  the 135 spins the paper reports.
- `test_annotated_durations_match_publication` — documents the 51.2 Hz vs 50 Hz
  discrepancy so it cannot be silently reintroduced.
- `test_selection_depends_only_on_training_data` — the leakage guarantee.
- `test_magnitude_features_are_rotation_invariant` — why the magnitude features
  exist at all.
- `test_flattened_forest_matches_sklearn` — the C export is the same function.

## The dataset

Not vendored here. Download *Package of motion sensor data of spin alert
behaviour* ([doi:10.6084/m9.figshare.30022441](https://doi.org/10.6084/m9.figshare.30022441))
and unpack it to `spinning_dataset/` at the repository root.

The pickles were written with NumPy 2.x; `dataset.py` installs a module alias so
they load under NumPy 1.x too. No array data is reinterpreted.
