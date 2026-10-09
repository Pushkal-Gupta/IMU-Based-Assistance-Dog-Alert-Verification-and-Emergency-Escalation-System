"""Evaluation protocols: within-subject, leave-one-group-out, and event-level.

Three questions are answered separately, because they have different answers:

``within_subject``
    Windows from every recording are pooled and split at random.  Windows from
    one behavioural episode land on both sides of the split, so this number is
    optimistic by construction.  The paper reports it as a reference point and
    so do we -- it is the ceiling, not the deployment estimate.

``logo`` (Leave-One-Group-Out)
    Whole recordings are held out in turn.  Nothing from a held-out recording
    influences feature selection, scaling or fitting.  This is our stand-in for
    the paper's Leave-One-Dog-Out, since the public release carries no dog
    identities (see ``dataset.py``).

``event``
    The LOGO out-of-fold window predictions are aggregated back up to the 7.8 s
    curated events: an event counts as detected if any of its windows fires.
    This is the number that matters operationally, because an alert is a
    sustained behaviour and the escalation layer consumes events, not windows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import LeaveOneGroupOut, train_test_split

from .config import DEFAULT_CONFIG, DEFAULT_DATASET_DIR, PipelineConfig
from .dataset import Event, curate_events, dataset_summary, load_recordings
from .features import extract_features, feature_names, gyro_magnitude_mean
from .models import (
    EMBEDDED_MODEL,
    MODEL_ORDER,
    GyroMagnitudeBaseline,
    build_model,
    predict_scores,
)
from .segmentation import SegmentSet, segment_events

BASELINE_NAME = "heuristic_baseline"
ALL_MODELS: tuple[str, ...] = (BASELINE_NAME, *MODEL_ORDER, EMBEDDED_MODEL)


@dataclass
class ExperimentData:
    """Everything the protocols need, computed once."""

    events: list[Event]
    segments: SegmentSet
    features: np.ndarray
    feature_names: list[str]
    gyro_statistic: np.ndarray
    summary: dict
    config: PipelineConfig = field(default=DEFAULT_CONFIG)

    @property
    def y(self) -> np.ndarray:
        return self.segments.labels.astype(int)

    @property
    def groups(self) -> np.ndarray:
        return self.segments.groups


def prepare(
    dataset_dir: Path | str = DEFAULT_DATASET_DIR,
    config: PipelineConfig = DEFAULT_CONFIG,
) -> ExperimentData:
    """Load, curate, segment and featurise the dataset."""
    recordings = load_recordings(dataset_dir)
    summary = dataset_summary(recordings)
    events = curate_events(recordings, config)
    segments = segment_events(events, config)
    names = feature_names()
    features = extract_features(segments.windows, segments.fs_hz)
    if features.shape[1] != len(names):
        raise AssertionError(
            f"feature matrix has {features.shape[1]} columns but {len(names)} names"
        )
    summary["n_events"] = len(events)
    summary["n_event_groups"] = len({e.group for e in events})
    summary["event_samples"] = config.event_samples(segments.fs_hz)
    summary["event_seconds"] = round(config.event_seconds(segments.fs_hz), 3)
    summary["windows_per_event"] = config.event_windows
    summary["n_positive_events"] = int(sum(e.label for e in events))
    summary["n_negative_events"] = int(len(events) - sum(e.label for e in events))
    summary["n_windows"] = len(segments)
    summary["n_positive_windows"] = int(segments.labels.sum())
    summary["window_samples"] = int(segments.windows.shape[1])
    summary["stride_samples"] = config.stride_samples(segments.fs_hz)
    summary["n_features"] = int(features.shape[1])
    return ExperimentData(
        events=events,
        segments=segments,
        features=features,
        feature_names=names,
        gyro_statistic=gyro_magnitude_mean(segments.windows),
        summary=summary,
        config=config,
    )


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #
def binary_metrics(y_true: np.ndarray, y_pred: np.ndarray, scores: np.ndarray | None = None) -> dict:
    y_true = np.asarray(y_true, dtype=int)
    y_pred = np.asarray(y_pred, dtype=int)
    matrix = confusion_matrix(y_true, y_pred, labels=[0, 1])
    tn, fp, fn, tp = matrix.ravel()
    out = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "specificity": float(tn / (tn + fp)) if (tn + fp) else float("nan"),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "support": {"negative": int(tn + fp), "positive": int(fn + tp)},
    }
    if scores is not None and len(np.unique(y_true)) == 2:
        out["roc_auc"] = float(roc_auc_score(y_true, scores))
    else:
        out["roc_auc"] = float("nan")
    return out


# --------------------------------------------------------------------------- #
# protocol 1: within-subject (pooled random split)
# --------------------------------------------------------------------------- #
def run_within_subject(data: ExperimentData) -> dict[str, dict]:
    config = data.config
    indices = np.arange(len(data.segments))
    train_idx, test_idx = train_test_split(
        indices,
        test_size=config.test_size,
        random_state=config.random_state,
        stratify=data.y,
    )

    results: dict[str, dict] = {}
    for name in ALL_MODELS:
        if name == BASELINE_NAME:
            model = GyroMagnitudeBaseline()
            model.fit(data.gyro_statistic[train_idx], data.y[train_idx])
            predictions = model.predict(data.gyro_statistic[test_idx])
            scores = model.predict_proba(data.gyro_statistic[test_idx])[:, 1]
            extra = {"threshold": float(model.threshold_)}
        else:
            model = build_model(name, data.feature_names, config)
            model.fit(data.features[train_idx], data.y[train_idx])
            predictions = model.predict(data.features[test_idx])
            scores = predict_scores(model, data.features[test_idx])
            extra = {"selected_features": model.named_steps["select"].selected_names()}

        results[name] = {**binary_metrics(data.y[test_idx], predictions, scores), **extra}
    return results


# --------------------------------------------------------------------------- #
# protocol 2: leave-one-group-out
# --------------------------------------------------------------------------- #
@dataclass
class LogoResult:
    segment_metrics: dict
    per_fold: list[dict]
    oof_predictions: np.ndarray
    oof_scores: np.ndarray
    selection_frequency: dict[str, int]
    #: Fitted model per held-out fold label, when ``keep_models`` was set.  The
    #: continuous-stream evaluation needs them to score whole recordings of a
    #: held-out group with a model that never saw that group.
    models: dict = field(default_factory=dict)


def run_logo(
    data: ExperimentData,
    models: Sequence[str] = ALL_MODELS,
    fold_labels: np.ndarray | None = None,
    keep_models: bool = False,
) -> dict[str, LogoResult]:
    """Leave-one-out over ``fold_labels`` (default: recording groups).

    Passing session or device labels instead gives leave-one-session-out and
    cross-device protocols with exactly the same fitting code, so the only thing
    that differs between protocols is the split.
    """
    labels = data.groups if fold_labels is None else np.asarray(fold_labels, dtype=object)
    splitter = LeaveOneGroupOut()
    folds = list(splitter.split(data.features, data.y, labels))

    results: dict[str, LogoResult] = {}
    for name in models:
        oof_predictions = np.full(len(data.segments), -1, dtype=int)
        oof_scores = np.full(len(data.segments), np.nan, dtype=float)
        per_fold: list[dict] = []
        selection_counts: dict[str, int] = {}
        fitted: dict = {}

        for train_idx, test_idx in folds:
            y_train = data.y[train_idx]
            # A fold whose training half lost an entire class cannot be fitted.
            if len(np.unique(y_train)) < 2:
                continue

            if name == BASELINE_NAME:
                model = GyroMagnitudeBaseline()
                model.fit(data.gyro_statistic[train_idx], y_train)
                predictions = model.predict(data.gyro_statistic[test_idx])
                scores = model.predict_proba(data.gyro_statistic[test_idx])[:, 1]
            else:
                model = build_model(name, data.feature_names, data.config)
                model.fit(data.features[train_idx], y_train)
                predictions = model.predict(data.features[test_idx])
                scores = predict_scores(model, data.features[test_idx])
                for feature in model.named_steps["select"].selected_names():
                    selection_counts[feature] = selection_counts.get(feature, 0) + 1

            oof_predictions[test_idx] = predictions
            oof_scores[test_idx] = scores

            held_out_group = str(labels[test_idx][0])
            if keep_models:
                fitted[held_out_group] = model
            per_fold.append(
                {
                    "group": held_out_group,
                    "n_test_windows": int(test_idx.size),
                    "n_test_positive": int(data.y[test_idx].sum()),
                    **binary_metrics(data.y[test_idx], predictions, scores),
                }
            )

        evaluated = oof_predictions >= 0
        results[name] = LogoResult(
            segment_metrics=binary_metrics(
                data.y[evaluated], oof_predictions[evaluated], oof_scores[evaluated]
            ),
            per_fold=per_fold,
            oof_predictions=oof_predictions,
            oof_scores=oof_scores,
            selection_frequency=dict(
                sorted(selection_counts.items(), key=lambda kv: (-kv[1], kv[0]))
            ),
            models=fitted,
        )
    return results


# --------------------------------------------------------------------------- #
# protocol 3: event-level aggregation
# --------------------------------------------------------------------------- #
def aggregate_to_events(
    data: ExperimentData,
    predictions: np.ndarray,
    scores: np.ndarray,
    min_positive_windows: int = 1,
) -> dict:
    """Roll window predictions up to their 7.8 s curated events.

    ``min_positive_windows`` is the OR-rule threshold: 1 reproduces the paper's
    "positive if at least one of its constituent segments is positive".
    """
    evaluated = predictions >= 0
    event_ids = data.segments.event_ids[evaluated]
    event_labels = data.segments.event_labels[evaluated].astype(int)
    window_predictions = predictions[evaluated]
    window_scores = scores[evaluated]

    unique_ids, inverse = np.unique(event_ids, return_inverse=True)
    positive_counts = np.zeros(unique_ids.size, dtype=int)
    max_scores = np.zeros(unique_ids.size, dtype=float)
    truth = np.zeros(unique_ids.size, dtype=int)

    np.add.at(positive_counts, inverse, window_predictions)
    np.maximum.at(max_scores, inverse, np.nan_to_num(window_scores))
    truth[inverse] = event_labels

    event_predictions = (positive_counts >= min_positive_windows).astype(int)
    return {
        "min_positive_windows": int(min_positive_windows),
        "n_events": int(unique_ids.size),
        **binary_metrics(truth, event_predictions, max_scores),
    }


def event_probability_streams(
    data: ExperimentData, scores: np.ndarray
) -> tuple[dict, dict, dict]:
    """Per-event ordered probability streams, for the verification sweep.

    Returns ``(streams, labels, onsets)``.  ``onsets`` gives the time of the
    first annotated spin sample within each event, so the sweep can report
    latency from behaviour onset rather than from the padded event's start.
    """
    evaluated = ~np.isnan(scores)
    streams: dict[str, list[float]] = {}
    labels: dict[str, int] = {}
    for index in np.flatnonzero(evaluated):
        event_id = str(data.segments.event_ids[index])
        streams.setdefault(event_id, []).append(float(scores[index]))
        labels[event_id] = int(data.segments.event_labels[index])
    onsets = {event.event_id: event.onset_s for event in data.events if event.event_id in streams}
    return {k: np.asarray(v) for k, v in streams.items()}, labels, onsets
