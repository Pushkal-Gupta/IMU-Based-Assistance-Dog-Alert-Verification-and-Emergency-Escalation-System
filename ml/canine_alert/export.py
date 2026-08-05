"""Transpile a fitted pipeline into C for the ESP32 collar.

The collar has no Python, so the pipeline is emitted as three plain-C artefacts:

* the *feature plan* -- which of the 159 features survived selection, so the
  firmware computes only those (typically 20, from a handful of signals);
* the *standardiser* -- the per-feature mean and scale learned by
  ``StandardScaler``;
* the *forest* -- every tree flattened into a single node array.

Trees are emitted as flat arrays rather than nested ``if`` statements.  Nested
conditionals blow up instruction cache and compile time at a few thousand nodes;
a flat array is data, lives in flash via ``const``, and is walked with a
three-line loop.

The generated header is validated by ``ml/tests/test_export.py``, which runs the
same reference walker over the emitted tables and asserts bit-for-bit agreement
with scikit-learn's ``predict_proba`` on the whole dataset.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline

from .features import SIGNAL_NAMES, describe_feature, feature_names

#: Sentinel marking a leaf in the flattened node table.
LEAF = -1


@dataclass
class ForestTables:
    """Flattened random forest, ready to emit as C arrays."""

    feature: np.ndarray  # int16, index into the *selected* feature vector, or LEAF
    threshold: np.ndarray  # float32
    left: np.ndarray  # int16, index of the left child in this same array
    right: np.ndarray  # int16
    value: np.ndarray  # float32, P(spin) at a leaf
    tree_offsets: np.ndarray  # int16, first node index of each tree
    n_trees: int
    n_nodes: int

    @property
    def flash_bytes(self) -> int:
        """Size of the emitted tables in flash."""
        return int(
            self.feature.nbytes
            + self.threshold.nbytes
            + self.left.nbytes
            + self.right.nbytes
            + self.value.nbytes
            + self.tree_offsets.nbytes
        )


def flatten_forest(forest: RandomForestClassifier) -> ForestTables:
    """Concatenate every tree's node table into one flat array."""
    features: list[int] = []
    thresholds: list[float] = []
    lefts: list[int] = []
    rights: list[int] = []
    values: list[float] = []
    offsets: list[int] = []

    positive_column = int(np.flatnonzero(forest.classes_ == 1)[0])

    for estimator in forest.estimators_:
        tree = estimator.tree_
        base = len(features)
        offsets.append(base)
        for node in range(tree.node_count):
            is_leaf = tree.children_left[node] == -1
            if is_leaf:
                counts = tree.value[node][0]
                total = counts.sum()
                probability = float(counts[positive_column] / total) if total > 0 else 0.0
                features.append(LEAF)
                thresholds.append(0.0)
                lefts.append(-1)
                rights.append(-1)
                values.append(probability)
            else:
                features.append(int(tree.feature[node]))
                thresholds.append(float(tree.threshold[node]))
                lefts.append(int(tree.children_left[node]) + base)
                rights.append(int(tree.children_right[node]) + base)
                values.append(0.0)

    return ForestTables(
        feature=np.asarray(features, dtype=np.int16),
        threshold=np.asarray(thresholds, dtype=np.float32),
        left=np.asarray(lefts, dtype=np.int16),
        right=np.asarray(rights, dtype=np.int16),
        value=np.asarray(values, dtype=np.float32),
        tree_offsets=np.asarray(offsets, dtype=np.int16),
        n_trees=len(offsets),
        n_nodes=len(features),
    )


def predict_from_tables(tables: ForestTables, X: np.ndarray) -> np.ndarray:
    """Reference walker over the flattened tables.

    Mirrors ``rf_predict()`` in the generated C exactly, including the ``<=``
    comparison scikit-learn uses at every split.  Runs on the *scaled, selected*
    feature matrix.
    """
    X = np.atleast_2d(np.asarray(X, dtype=np.float32))
    out = np.empty(X.shape[0], dtype=np.float64)
    for row in range(X.shape[0]):
        total = 0.0
        for tree in range(tables.n_trees):
            node = int(tables.tree_offsets[tree])
            while tables.feature[node] != LEAF:
                if X[row, tables.feature[node]] <= tables.threshold[node]:
                    node = int(tables.left[node])
                else:
                    node = int(tables.right[node])
            total += float(tables.value[node])
        out[row] = total / tables.n_trees
    return out


def _c_array(
    name: str,
    values: Sequence,
    ctype: str,
    fmt: str,
    per_line: int = 12,
    suffix: str = "",
) -> str:
    """Emit a ``static const`` C array.

    ``suffix`` appends a C literal suffix (``f`` for single-precision), which is
    not a Python format spec and so cannot live in ``fmt``.
    """
    body = []
    for start in range(0, len(values), per_line):
        chunk = values[start : start + per_line]
        body.append("    " + ", ".join(format(v, fmt) + suffix for v in chunk) + ",")
    joined = "\n".join(body)
    return f"static const {ctype} {name}[{len(values)}] = {{\n{joined}\n}};\n"


def _c_float_array(name: str, values: Sequence[float], per_line: int = 6) -> str:
    return _c_array(name, [float(v) for v in values], "float", ".8e", per_line, suffix="f")


def generate_header(
    pipeline: Pipeline,
    model_name: str,
    fs_hz: float,
    verify_k: int,
    verify_n: int,
    vote_threshold: float,
    refractory_seconds: float,
    window_samples: int,
    stride_samples: int,
) -> str:
    """Emit ``firmware/collar/src/model.h``."""
    selector = pipeline.named_steps["select"]
    scaler = pipeline.named_steps["scale"]
    forest = pipeline.named_steps["clf"]
    if not isinstance(forest, RandomForestClassifier):
        raise TypeError(f"only RandomForestClassifier can be transpiled, got {type(forest).__name__}")

    selected = selector.selected_names()
    all_names = feature_names()
    tables = flatten_forest(forest)
    selected_indices = [int(i) for i in selector.support_]

    needed_signals = sorted(
        {s for name in selected for s in describe_feature(name)["signal"].split(",")},
        key=SIGNAL_NAMES.index,
    )
    needs_fft = any(describe_feature(name)["kind"] == "frequency" for name in selected)

    header = f"""\
/* Generated by ml/canine_alert/export.py -- DO NOT EDIT BY HAND.
 *
 * Model:            {model_name}
 * Trees:            {tables.n_trees}
 * Nodes:            {tables.n_nodes}
 * Selected features:{len(selected)} of {len(all_names)}
 * Table size:       {tables.flash_bytes} bytes in flash
 * Sample rate:      {fs_hz:.2f} Hz
 *
 * Regenerate with:  python ml/scripts/export_firmware_model.py
 */

#ifndef CA_MODEL_H
#define CA_MODEL_H

#include <stdint.h>

/* ---- window geometry ---------------------------------------------------- */
#define CA_SAMPLE_RATE_HZ      {fs_hz:.4f}f
#define CA_WINDOW_SAMPLES      {window_samples}
#define CA_STRIDE_SAMPLES      {stride_samples}
/* Length of the full feature vector features.c builds, before selection. */
#define CA_N_ALL_FEATURES      {len(all_names)}
/* Length of the vector the forest actually consumes. */
#define CA_N_FEATURES          {len(selected)}

/* ---- verification gate (mirrors ml/canine_alert/verification.py) --------- */
#define CA_VERIFY_K            {verify_k}
#define CA_VERIFY_N            {verify_n}
#define CA_VOTE_THRESHOLD      {vote_threshold:.6f}f
#define CA_REFRACTORY_MS       {int(refractory_seconds * 1000)}

/* ---- which derived signals the selected features need -------------------- */
{chr(10).join(f'#define CA_NEEDS_{s.upper():<6} 1' for s in needed_signals)}
#define CA_NEEDS_FFT           {1 if needs_fft else 0}

/* ---- feature selection --------------------------------------------------
 * Indices into the full CA_N_ALL_FEATURES vector produced by ca_extract().
 * The firmware computes the full vector and gathers these, rather than trying
 * to compute only the survivors: gathering is a memcpy-cheap loop and it makes
 * the C impossible to desynchronise from features.py when the model is
 * retrained and different features win.
 */
{_c_array('ca_feature_index', selected_indices, 'int16_t', 'd', 16)}
/* ---- standardiser (StandardScaler fitted on the selected features) ------- */
{_c_float_array('ca_feature_mean', scaler.mean_)}
{_c_float_array('ca_feature_scale', scaler.scale_)}

/* ---- flattened random forest -------------------------------------------- */
#define CA_N_TREES             {tables.n_trees}
#define CA_N_NODES             {tables.n_nodes}

{_c_array('ca_tree_offset', tables.tree_offsets.tolist(), 'int16_t', 'd', 16)}
{_c_array('ca_node_feature', tables.feature.tolist(), 'int16_t', 'd', 16)}
{_c_array('ca_node_left', tables.left.tolist(), 'int16_t', 'd', 16)}
{_c_array('ca_node_right', tables.right.tolist(), 'int16_t', 'd', 16)}
{_c_float_array('ca_node_threshold', tables.threshold)}
{_c_float_array('ca_node_value', tables.value)}

/* Names of the selected features, in vector order.  Only used for the serial
 * diagnostics banner; the compiler drops it when diagnostics are off. */
static const char *const ca_feature_names[CA_N_FEATURES] = {{
{chr(10).join(f'    "{name}",' for name in selected)}
}};

#endif /* CA_MODEL_H */
"""
    return header


def export_summary(pipeline: Pipeline) -> dict:
    """Sizing information for the report."""
    tables = flatten_forest(pipeline.named_steps["clf"])
    return {
        "n_trees": tables.n_trees,
        "n_nodes": tables.n_nodes,
        "flash_bytes": tables.flash_bytes,
        "flash_kib": round(tables.flash_bytes / 1024, 1),
        "selected_features": pipeline.named_steps["select"].selected_names(),
    }
