"""Baselines that learn from the raw window rather than from hand-made features.

A reviewer's first question about a feature-engineered pipeline is whether a
model that learns its own features would simply do better.  Two answers are
evaluated under exactly the same leave-one-group-out folds:

* ``cnn`` -- a small 1-D convolutional network (three conv blocks, global
  average pooling), the standard deep baseline for inertial activity
  recognition;
* ``rocket`` -- random convolutional kernels with PPV and max pooling and a
  ridge classifier (Dempster et al., 2020), the standard strong baseline for
  time-series classification that needs no architecture search.

Both expose ``fit(windows, y)`` / ``predict_proba(windows)`` on raw
``(n, width, 6)`` tensors, so the protocols treat them like any other model.
"""

from __future__ import annotations

import numpy as np
from sklearn.linear_model import RidgeClassifierCV
from sklearn.preprocessing import StandardScaler


class _ChannelScaler:
    """Per-channel standardisation fitted on the training windows only."""

    def fit(self, windows: np.ndarray) -> "_ChannelScaler":
        self.mean_ = windows.mean(axis=(0, 1), keepdims=True)
        self.std_ = windows.std(axis=(0, 1), keepdims=True) + 1e-8
        return self

    def transform(self, windows: np.ndarray) -> np.ndarray:
        return (windows - self.mean_) / self.std_


# --------------------------------------------------------------------------- #
# 1-D CNN
# --------------------------------------------------------------------------- #
class CNNClassifier:
    """Small 1-D CNN, trained with class-weighted binary cross-entropy."""

    def __init__(self, epochs: int = 40, lr: float = 1e-3, batch_size: int = 64, seed: int = 42,
                 augment_rotation: bool = False) -> None:
        self.epochs = epochs
        self.lr = lr
        self.batch_size = batch_size
        self.seed = seed
        self.augment_rotation = augment_rotation

    def _net(self, n_channels: int):
        import torch.nn as nn

        return nn.Sequential(
            nn.Conv1d(n_channels, 32, 7, padding=3), nn.BatchNorm1d(32), nn.ReLU(),
            nn.Conv1d(32, 64, 5, padding=2), nn.BatchNorm1d(64), nn.ReLU(),
            nn.MaxPool1d(2),
            nn.Conv1d(64, 64, 3, padding=1), nn.BatchNorm1d(64), nn.ReLU(),
            nn.AdaptiveAvgPool1d(1), nn.Flatten(), nn.Linear(64, 1),
        )

    def fit(self, windows: np.ndarray, y: np.ndarray) -> "CNNClassifier":
        import torch

        torch.manual_seed(self.seed)
        rng = np.random.default_rng(self.seed)
        self.scaler_ = _ChannelScaler().fit(windows)
        X = self.scaler_.transform(windows).astype(np.float32)
        y = np.asarray(y, dtype=np.float32)
        self.net_ = self._net(X.shape[2])
        pos = max(1.0, float(y.sum()))
        weight = torch.tensor((len(y) - pos) / pos)
        loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=weight)
        opt = torch.optim.Adam(self.net_.parameters(), lr=self.lr, weight_decay=1e-4)
        self.net_.train()
        for _ in range(self.epochs):
            order = rng.permutation(len(y))
            for start in range(0, len(y), self.batch_size):
                idx = order[start : start + self.batch_size]
                xb = X[idx]
                if self.augment_rotation:
                    from .robustness import random_rotations, rotate

                    xb = rotate(xb.astype(np.float64) * self.scaler_.std_ + self.scaler_.mean_,
                                random_rotations(len(idx), rng))
                    xb = self.scaler_.transform(xb).astype(np.float32)
                xt = torch.from_numpy(np.ascontiguousarray(xb.transpose(0, 2, 1)))
                yt = torch.from_numpy(y[idx])
                opt.zero_grad()
                loss = loss_fn(self.net_(xt).squeeze(1), yt)
                loss.backward()
                opt.step()
        self.classes_ = np.array([0, 1])
        return self

    def predict_proba(self, windows: np.ndarray) -> np.ndarray:
        import torch

        self.net_.eval()
        X = self.scaler_.transform(windows).astype(np.float32)
        with torch.no_grad():
            logits = self.net_(torch.from_numpy(np.ascontiguousarray(X.transpose(0, 2, 1)))).squeeze(1).numpy()
        p = 1.0 / (1.0 + np.exp(-logits))
        return np.column_stack([1 - p, p])

    def predict(self, windows: np.ndarray) -> np.ndarray:
        return (self.predict_proba(windows)[:, 1] >= 0.5).astype(int)

    def n_parameters(self) -> int:
        return int(sum(p.numel() for p in self.net_.parameters()))


# --------------------------------------------------------------------------- #
# ROCKET
# --------------------------------------------------------------------------- #
class RocketClassifier:
    """Multivariate ROCKET: random dilated kernels, PPV + max, ridge."""

    def __init__(self, n_kernels: int = 2000, seed: int = 42) -> None:
        self.n_kernels = n_kernels
        self.seed = seed

    def _generate(self, length: int, n_channels: int) -> None:
        rng = np.random.default_rng(self.seed)
        self.kernels_ = []
        for _ in range(self.n_kernels):
            k = int(rng.choice([7, 9, 11]))
            n_ch = int(rng.integers(1, n_channels + 1))
            channels = rng.choice(n_channels, n_ch, replace=False)
            w = rng.normal(0.0, 1.0, (n_ch, k))
            w -= w.mean(axis=1, keepdims=True)
            bias = rng.uniform(-1.0, 1.0)
            max_exp = np.log2((length - 1) / (k - 1))
            dilation = int(2 ** rng.uniform(0, max_exp))
            padding = ((k - 1) * dilation) // 2 if rng.integers(2) else 0
            self.kernels_.append((channels, w, bias, dilation, padding))

    def _transform(self, X: np.ndarray) -> np.ndarray:
        # X: (n, length, channels)
        n, length, _ = X.shape
        out = np.empty((n, 2 * len(self.kernels_)))
        for j, (channels, w, bias, dilation, padding) in enumerate(self.kernels_):
            k = w.shape[1]
            xs = X[:, :, channels]
            if padding:
                xs = np.pad(xs, ((0, 0), (padding, padding), (0, 0)))
            span = (k - 1) * dilation
            m = xs.shape[1] - span
            if m <= 0:
                out[:, 2 * j] = 0.0
                out[:, 2 * j + 1] = 0.0
                continue
            conv = np.full((n, m), bias)
            for t in range(k):
                conv += xs[:, t * dilation : t * dilation + m, :] @ w[:, t]
            out[:, 2 * j] = (conv > 0).mean(axis=1)
            out[:, 2 * j + 1] = conv.max(axis=1)
        return out

    def fit(self, windows: np.ndarray, y: np.ndarray) -> "RocketClassifier":
        self.scaler_ = _ChannelScaler().fit(windows)
        X = self.scaler_.transform(windows)
        self._generate(X.shape[1], X.shape[2])
        F = self._transform(X)
        self.fscale_ = StandardScaler().fit(F)
        self.ridge_ = RidgeClassifierCV(alphas=np.logspace(-3, 3, 10), class_weight="balanced")
        self.ridge_.fit(self.fscale_.transform(F), y)
        self.classes_ = np.array([0, 1])
        return self

    def decision_function(self, windows: np.ndarray) -> np.ndarray:
        F = self._transform(self.scaler_.transform(windows))
        return self.ridge_.decision_function(self.fscale_.transform(F))

    def predict_proba(self, windows: np.ndarray) -> np.ndarray:
        p = 1.0 / (1.0 + np.exp(-self.decision_function(windows)))
        return np.column_stack([1 - p, p])

    def predict(self, windows: np.ndarray) -> np.ndarray:
        return (self.decision_function(windows) > 0).astype(int)
