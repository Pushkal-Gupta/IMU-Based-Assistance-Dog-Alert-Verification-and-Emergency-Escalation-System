"""Firmware export: the transpiled forest must be the same function as sklearn's.

A silent divergence here would mean the collar behaves differently from every
number in the evaluation report, so these tests check the tables numerically
rather than just checking that a file was produced.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest
from sklearn.ensemble import RandomForestClassifier

from canine_alert.config import DEFAULT_CONFIG, REPO_ROOT
from canine_alert.export import (
    LEAF,
    export_summary,
    flatten_forest,
    generate_header,
    predict_from_tables,
)
from canine_alert.features import extract_features, feature_names
from canine_alert.models import EMBEDDED_MODEL, build_model

HEADER_PATH = REPO_ROOT / "firmware" / "collar" / "src" / "model.h"


@pytest.fixture(scope="module")
def fitted(experiment):
    pipeline = build_model(EMBEDDED_MODEL, experiment.feature_names, DEFAULT_CONFIG)
    pipeline.fit(experiment.features, experiment.y)
    selected = pipeline.named_steps["select"].transform(experiment.features)
    scaled = pipeline.named_steps["scale"].transform(selected)
    return pipeline, scaled


def test_flattened_forest_matches_sklearn(fitted):
    pipeline, scaled = fitted
    forest = pipeline.named_steps["clf"]
    tables = flatten_forest(forest)
    reference = forest.predict_proba(scaled)[:, 1]
    transpiled = predict_from_tables(tables, scaled)
    # float32 tables vs float64 sklearn: agreement is limited by rounding only.
    assert np.max(np.abs(reference - transpiled)) < 1e-6


def test_flattened_decisions_match_sklearn(fitted):
    pipeline, scaled = fitted
    tables = flatten_forest(pipeline.named_steps["clf"])
    reference = pipeline.named_steps["clf"].predict(scaled)
    transpiled = (predict_from_tables(tables, scaled) >= 0.5).astype(int)
    assert np.array_equal(reference, transpiled)


def test_child_indices_are_absolute_and_in_range(fitted):
    """Each tree is offset into one flat array; a stale relative index would
    silently walk into a neighbouring tree."""
    tables = flatten_forest(fitted[0].named_steps["clf"])
    internal = tables.feature != LEAF
    assert np.all(tables.left[internal] > 0)
    assert np.all(tables.right[internal] > 0)
    assert np.all(tables.left[internal] < tables.n_nodes)
    assert np.all(tables.right[internal] < tables.n_nodes)


def test_children_always_come_after_their_parent(fitted):
    """Guarantees the walk terminates without a visited set."""
    tables = flatten_forest(fitted[0].named_steps["clf"])
    internal = np.flatnonzero(tables.feature != LEAF)
    assert np.all(tables.left[internal] > internal)
    assert np.all(tables.right[internal] > internal)


def test_leaves_are_probabilities(fitted):
    tables = flatten_forest(fitted[0].named_steps["clf"])
    leaves = tables.value[tables.feature == LEAF]
    assert leaves.size > 0
    assert np.all((leaves >= 0.0) & (leaves <= 1.0))


def test_every_tree_has_an_offset(fitted):
    forest = fitted[0].named_steps["clf"]
    tables = flatten_forest(forest)
    assert tables.n_trees == forest.n_estimators
    assert tables.tree_offsets[0] == 0
    assert np.all(np.diff(tables.tree_offsets) > 0)


def test_split_features_index_the_selected_vector(fitted):
    """Node feature indices address the 20-wide selected vector, not the 159."""
    tables = flatten_forest(fitted[0].named_steps["clf"])
    internal = tables.feature[tables.feature != LEAF]
    assert internal.max() < DEFAULT_CONFIG.n_selected_features


def test_int16_tables_do_not_overflow(fitted):
    """The C tables are int16; a bigger forest would silently wrap."""
    tables = flatten_forest(fitted[0].named_steps["clf"])
    assert tables.n_nodes < np.iinfo(np.int16).max


def test_generated_header_is_self_consistent(fitted):
    pipeline, _ = fitted
    header = generate_header(
        pipeline=pipeline,
        model_name=EMBEDDED_MODEL,
        fs_hz=51.2,
        verify_k=2,
        verify_n=4,
        vote_threshold=0.45,
        refractory_seconds=60.0,
        window_samples=133,
        stride_samples=67,
    )
    tables = flatten_forest(pipeline.named_steps["clf"])

    def define(name):
        match = re.search(rf"^#define {name}\s+(\S+)$", header, re.MULTILINE)
        assert match, f"{name} missing from generated header"
        return match.group(1)

    assert int(define("CA_N_TREES")) == tables.n_trees
    assert int(define("CA_N_NODES")) == tables.n_nodes
    assert int(define("CA_N_FEATURES")) == DEFAULT_CONFIG.n_selected_features
    assert int(define("CA_N_ALL_FEATURES")) == len(feature_names())
    assert int(define("CA_VERIFY_K")) == 2
    assert int(define("CA_VERIFY_N")) == 4
    assert int(define("CA_REFRACTORY_MS")) == 60000

    for array, length in (
        ("ca_node_feature", tables.n_nodes),
        ("ca_node_left", tables.n_nodes),
        ("ca_node_right", tables.n_nodes),
        ("ca_node_threshold", tables.n_nodes),
        ("ca_node_value", tables.n_nodes),
        ("ca_tree_offset", tables.n_trees),
        ("ca_feature_index", DEFAULT_CONFIG.n_selected_features),
        ("ca_feature_mean", DEFAULT_CONFIG.n_selected_features),
        ("ca_feature_scale", DEFAULT_CONFIG.n_selected_features),
    ):
        declared = re.search(rf"{array}\[(\d+)\]", header)
        assert declared, f"{array} missing from generated header"
        assert int(declared.group(1)) == length, array
        emitted = header.split(f"{array}[")[1].split("{", 1)[1].split("};")[0]
        assert emitted.count(",") == length, f"{array} has the wrong number of entries"


def test_header_float_literals_are_single_precision(fitted):
    """Missing 'f' suffixes would promote every constant to double on the ESP32."""
    header = generate_header(
        pipeline=fitted[0],
        model_name=EMBEDDED_MODEL,
        fs_hz=51.2,
        verify_k=2,
        verify_n=4,
        vote_threshold=0.45,
        refractory_seconds=60.0,
        window_samples=133,
        stride_samples=67,
    )
    block = header.split("ca_node_threshold[")[1].split("};")[0]
    literals = re.findall(r"-?\d+\.\d+e[+-]\d+f?", block)
    assert literals, "no float literals found"
    assert all(literal.endswith("f") for literal in literals)


def test_feature_index_points_at_the_named_features(fitted):
    pipeline, _ = fitted
    selector = pipeline.named_steps["select"]
    names = feature_names()
    assert [names[i] for i in selector.support_] == selector.selected_names()


def test_export_summary_reports_real_sizes(fitted):
    info = export_summary(fitted[0])
    assert info["n_trees"] == 32
    assert info["flash_bytes"] > 0
    assert len(info["selected_features"]) == DEFAULT_CONFIG.n_selected_features


@pytest.mark.skipif(not HEADER_PATH.exists(), reason="run scripts/export_firmware_model.py first")
def test_checked_in_header_is_current(fitted):
    """The header in firmware/ must match what the current code and data produce.

    If this fails, the firmware is carrying a stale model -- regenerate it.
    """
    on_disk = HEADER_PATH.read_text()
    tables = flatten_forest(fitted[0].named_steps["clf"])
    assert f"#define CA_N_NODES             {tables.n_nodes}" in on_disk
    assert f"#define CA_N_TREES             {tables.n_trees}" in on_disk
