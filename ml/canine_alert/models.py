"""Classifiers and the heuristic baseline.

Four supervised models are evaluated, matching the paper: Random Forest,
Support Vector Machine, Gaussian Naive Bayes and Logistic Regression.  Each is
wrapped in a pipeline that does its own feature selection and scaling, so
nothing fitted on training data ever sees the held-out fold.

The heuristic baseline classifies a window as 'spin' when its mean gyroscope
magnitude exceeds a threshold, with the threshold tuned on the training fold
only -- the paper's baseline, reproduced so the ML gain is measured against the
same reference.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.naive_bayes import GaussianNB
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from .config import DEFAULT_CONFIG, PipelineConfig
from .selection import ThreeStageSelector

MODEL_ORDER: tuple[str, ...] = (
    "random_forest",
    "svm",
    "naive_bayes",
    "logistic_regression",
)

#: A deliberately small forest sized to fit an ESP32.  A 200-tree, depth-12
#: forest is roughly 100 kB of node tables once transpiled to C, which is
#: workable in flash but wasteful; 32 trees at depth 8 is about 8 kB and costs
#: little accuracy (both are reported side by side in docs/07-evaluation.md).
#: This is the model the collar firmware actually runs.
EMBEDDED_MODEL = "random_forest_embedded"


def build_model(
    name: str,
    feature_names: list[str] | None = None,
    config: PipelineConfig = DEFAULT_CONFIG,
) -> Pipeline:
    """Return an unfitted pipeline: selector -> scaler -> classifier."""
    selector = ThreeStageSelector(
        variance_threshold=config.variance_threshold,
        correlation_threshold=config.correlation_threshold,
        k=config.n_selected_features,
        feature_names=feature_names,
    )
    seed = config.random_state

    if name == "random_forest":
        classifier = RandomForestClassifier(
            n_estimators=200,
            max_depth=12,
            min_samples_leaf=2,
            class_weight="balanced_subsample",
            n_jobs=-1,
            random_state=seed,
        )
    elif name == EMBEDDED_MODEL:
        classifier = RandomForestClassifier(
            n_estimators=32,
            max_depth=8,
            min_samples_leaf=4,
            class_weight="balanced_subsample",
            n_jobs=-1,
            random_state=seed,
        )
    elif name == "svm":
        classifier = SVC(
            C=1.0,
            kernel="rbf",
            gamma="scale",
            class_weight="balanced",
            probability=True,
            random_state=seed,
        )
    elif name == "naive_bayes":
        classifier = GaussianNB()
    elif name == "logistic_regression":
        classifier = LogisticRegression(
            C=1.0,
            max_iter=2000,
            class_weight="balanced",
            random_state=seed,
        )
    else:
        raise ValueError(
            f"unknown model {name!r}; expected one of {(*MODEL_ORDER, EMBEDDED_MODEL)}"
        )

    return Pipeline(
        [
            ("select", selector),
            ("scale", StandardScaler()),
            ("clf", classifier),
        ]
    )


class GyroMagnitudeBaseline(BaseEstimator, ClassifierMixin):
    """Threshold on mean gyroscope magnitude, tuned on the training fold.

    Fitted on the raw *window tensor* rather than the feature matrix, because
    the statistic is defined directly on the signal.  The threshold search
    maximises training F1 over the observed range of the statistic.
    """

    def __init__(self, n_grid: int = 200) -> None:
        self.n_grid = n_grid

    def fit(self, statistic: np.ndarray, y: np.ndarray) -> "GyroMagnitudeBaseline":
        statistic = np.asarray(statistic, dtype=np.float64).ravel()
        y = np.asarray(y).ravel()
        lo, hi = float(statistic.min()), float(statistic.max())
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
            self.threshold_ = float(hi)
            self.train_f1_ = 0.0
            return self

        candidates = np.linspace(lo, hi, self.n_grid)
        best_threshold, best_score = candidates[0], -1.0
        for threshold in candidates:
            score = f1_score(y, (statistic > threshold).astype(int), zero_division=0)
            if score > best_score:
                best_threshold, best_score = float(threshold), float(score)
        self.threshold_ = best_threshold
        self.train_f1_ = best_score
        self.classes_ = np.array([0, 1])
        return self

    def predict(self, statistic: np.ndarray) -> np.ndarray:
        statistic = np.asarray(statistic, dtype=np.float64).ravel()
        return (statistic > self.threshold_).astype(int)

    def predict_proba(self, statistic: np.ndarray) -> np.ndarray:
        """Pseudo-probability: a logistic squash of the margin, so the baseline
        can be fed to the same ROC-AUC and verification code as the ML models."""
        statistic = np.asarray(statistic, dtype=np.float64).ravel()
        scale = max(abs(self.threshold_), 1.0)
        positive = 1.0 / (1.0 + np.exp(-(statistic - self.threshold_) / (0.1 * scale)))
        return np.column_stack([1.0 - positive, positive])


def predict_scores(model, X: np.ndarray) -> np.ndarray:
    """Positive-class score for any of our estimators."""
    if hasattr(model, "predict_proba"):
        return model.predict_proba(X)[:, 1]
    if hasattr(model, "decision_function"):
        margin = model.decision_function(X)
        return 1.0 / (1.0 + np.exp(-margin))
    return model.predict(X).astype(float)
