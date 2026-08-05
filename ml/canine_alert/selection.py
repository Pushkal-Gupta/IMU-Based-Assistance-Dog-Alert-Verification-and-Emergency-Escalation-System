"""Three-stage feature selection (paper, Section 2.7).

1. **Low-variance filtering** -- drop features whose variance falls below a
   threshold, eliminating quasi-constant predictors.
2. **Collinearity reduction** -- of any pair with ``|Pearson r| > 0.95``, keep
   one.
3. **Univariate selection** -- keep the ``k`` features with the highest ANOVA
   F-statistic against the label.

Implemented as a scikit-learn transformer so it can be fitted *inside* each
cross-validation fold.  Fitting the selector on the full dataset before
splitting would leak test-set label information into feature choice; the paper
does not state which it did, and we take the conservative route.  See
``docs/07-evaluation.md`` Section 7.

The variance threshold is applied to standardised features rather than raw ones.
On raw features a fixed threshold of 0.1 is scale-dependent (it would delete
correlations, which live in [-1, 1], while keeping every gyro feature, whose
units are deg/s), so a literal reading of the paper would make stage 1 a no-op
for most of the vector.  Standardising first makes the threshold mean the same
thing for every feature.
"""

from __future__ import annotations

import numpy as np
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.feature_selection import f_classif
from sklearn.utils.validation import check_is_fitted

from .config import DEFAULT_CONFIG, PipelineConfig


class ThreeStageSelector(BaseEstimator, TransformerMixin):
    """Variance filter -> correlation pruning -> ANOVA F-test top-k."""

    def __init__(
        self,
        variance_threshold: float = DEFAULT_CONFIG.variance_threshold,
        correlation_threshold: float = DEFAULT_CONFIG.correlation_threshold,
        k: int = DEFAULT_CONFIG.n_selected_features,
        feature_names: list[str] | None = None,
    ) -> None:
        self.variance_threshold = variance_threshold
        self.correlation_threshold = correlation_threshold
        self.k = k
        self.feature_names = feature_names

    # -- sklearn API ---------------------------------------------------------
    def fit(self, X: np.ndarray, y: np.ndarray) -> "ThreeStageSelector":
        X = np.asarray(X, dtype=np.float64)
        y = np.asarray(y)
        n_features = X.shape[1]

        # Stage 0: standardise so the variance threshold is scale-free.
        mean = X.mean(axis=0)
        scale = X.std(axis=0)
        scale = np.where(scale < 1e-12, 1.0, scale)
        Z = (X - mean) / scale

        # Stage 1: low-variance filtering.  After standardisation a feature has
        # unit variance unless it was constant, in which case scale was clamped
        # to 1 and the variance is 0.
        variances = Z.var(axis=0)
        stage1 = np.flatnonzero(variances >= self.variance_threshold)
        if stage1.size == 0:
            stage1 = np.arange(n_features)

        # Stage 2: collinearity reduction on the survivors, keeping the earlier
        # feature of any highly correlated pair (deterministic given the fixed
        # feature order).
        stage2 = self._prune_correlated(Z[:, stage1], stage1)

        # Stage 3: univariate ANOVA F-test, top k.
        scores, _ = f_classif(X[:, stage2], y)
        scores = np.nan_to_num(scores, nan=-np.inf)
        k = min(self.k, stage2.size)
        # argsort on (-score, index) keeps ties in original feature order.
        order = sorted(range(stage2.size), key=lambda i: (-scores[i], i))
        stage3 = stage2[np.asarray(sorted(order[:k]))]

        self.n_features_in_ = n_features
        self.variance_survivors_ = stage1
        self.correlation_survivors_ = stage2
        self.support_ = stage3
        self.scores_ = scores
        self.stage_sizes_ = {
            "input": int(n_features),
            "after_variance": int(stage1.size),
            "after_correlation": int(stage2.size),
            "selected": int(stage3.size),
        }
        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        check_is_fitted(self, "support_")
        return np.asarray(X, dtype=np.float64)[:, self.support_]

    # -- helpers -------------------------------------------------------------
    def _prune_correlated(self, Z: np.ndarray, indices: np.ndarray) -> np.ndarray:
        if Z.shape[1] < 2:
            return indices
        with np.errstate(invalid="ignore", divide="ignore"):
            corr = np.corrcoef(Z, rowvar=False)
        corr = np.nan_to_num(corr, nan=0.0)
        keep = np.ones(Z.shape[1], dtype=bool)
        for i in range(Z.shape[1]):
            if not keep[i]:
                continue
            redundant = np.flatnonzero(np.abs(corr[i, i + 1 :]) > self.correlation_threshold) + i + 1
            keep[redundant] = False
        survivors = indices[keep]
        return survivors if survivors.size else indices

    def selected_names(self) -> list[str]:
        check_is_fitted(self, "support_")
        if self.feature_names is None:
            return [f"f{i}" for i in self.support_]
        return [self.feature_names[i] for i in self.support_]

    def get_feature_names_out(self, input_features=None):  # noqa: ARG002
        return np.asarray(self.selected_names(), dtype=object)
