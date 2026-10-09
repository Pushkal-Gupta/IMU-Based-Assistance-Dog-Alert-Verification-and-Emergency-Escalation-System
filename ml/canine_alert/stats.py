"""Uncertainty quantification and hypothesis tests for the evaluation.

Why a module of its own
-----------------------
Windows from one recording are not independent: they overlap by 50%, they come
from one dog on one day, and a model that has trouble with that dog has trouble
with every window from it.  A confidence interval that resamples *windows*
pretends there are 1710 independent observations when the honest count is
closer to the 32 recording groups.  Everything here therefore resamples whole
groups (a cluster bootstrap), and every test that compares models pairs them on
the same groups.

Nothing in here touches the dataset or a model; it is pure statistics on
arrays, so it is tested on synthetic data in ``tests/test_stats.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np
from scipy import stats as _st

#: Resamples for every bootstrap in the report.  2000 keeps the Monte-Carlo
#: error of a 95% percentile bound well below the precision we print.
N_BOOT = 2000
SEED = 20251021


@dataclass(frozen=True)
class Interval:
    """A point estimate with a two-sided interval."""

    estimate: float
    low: float
    high: float
    level: float = 0.95
    method: str = ""

    def as_dict(self) -> dict:
        return {
            "estimate": _clean(self.estimate),
            "low": _clean(self.low),
            "high": _clean(self.high),
            "level": self.level,
            "method": self.method,
        }


def _clean(value: float) -> float | None:
    value = float(value)
    return None if not np.isfinite(value) else value


# --------------------------------------------------------------------------- #
# cluster bootstrap
# --------------------------------------------------------------------------- #
def group_index(groups: Sequence) -> tuple[np.ndarray, list[np.ndarray]]:
    """Unique groups and, for each, the row indices that belong to it."""
    groups = np.asarray(groups, dtype=object)
    unique = np.array(sorted(set(groups.tolist())), dtype=object)
    members = [np.flatnonzero(groups == g) for g in unique]
    return unique, members


def cluster_bootstrap(
    groups: Sequence,
    statistic: Callable[[np.ndarray], float],
    n_boot: int = N_BOOT,
    seed: int = SEED,
    level: float = 0.95,
) -> tuple[Interval, np.ndarray]:
    """Percentile bootstrap that resamples whole groups with replacement.

    ``statistic`` receives an array of *row* indices (with repeats, because a
    group drawn twice contributes its rows twice) and returns a float.  The
    point estimate is the statistic on the original rows.

    Returns the interval and the bootstrap distribution, so callers can derive
    p-values or plot it.
    """
    _, members = group_index(groups)
    rng = np.random.default_rng(seed)
    everything = np.concatenate(members) if members else np.array([], dtype=int)
    estimate = float(statistic(everything))

    draws = np.empty(n_boot, dtype=float)
    k = len(members)
    for b in range(n_boot):
        chosen = rng.integers(0, k, size=k)
        rows = np.concatenate([members[c] for c in chosen])
        draws[b] = statistic(rows)
    finite = draws[np.isfinite(draws)]
    alpha = (1.0 - level) / 2.0
    if finite.size == 0:
        low = high = float("nan")
    else:
        low, high = np.quantile(finite, [alpha, 1.0 - alpha])
    return Interval(estimate, float(low), float(high), level, "cluster percentile bootstrap"), draws


def bootstrap_p_value(draws: np.ndarray, null: float = 0.0) -> float:
    """Two-sided bootstrap p-value for ``H0: parameter == null``.

    The share of the bootstrap distribution on the far side of ``null``,
    doubled.  A draw exactly at ``null`` counts half to each side, so a
    degenerate distribution sitting on the null gives p = 1 rather than 0.
    """
    draws = np.asarray(draws, dtype=float)
    draws = draws[np.isfinite(draws)]
    if draws.size == 0:
        return float("nan")
    below = np.mean(draws < null) + 0.5 * np.mean(draws == null)
    above = np.mean(draws > null) + 0.5 * np.mean(draws == null)
    return float(min(1.0, 2.0 * min(below, above)))


# --------------------------------------------------------------------------- #
# exact intervals for proportions and rates
# --------------------------------------------------------------------------- #
def wilson_interval(successes: int, trials: int, level: float = 0.95) -> Interval:
    """Wilson score interval: well-behaved near 0 and 1, unlike the Wald form."""
    if trials <= 0:
        return Interval(float("nan"), float("nan"), float("nan"), level, "wilson")
    z = _st.norm.ppf(0.5 + level / 2.0)
    p = successes / trials
    denom = 1.0 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denom
    half = z * np.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denom
    # At p = 0 or 1 the bound equals p analytically but can miss it by an ulp.
    low = min(p, max(0.0, centre - half))
    high = max(p, min(1.0, centre + half))
    return Interval(p, low, high, level, "wilson")


def poisson_rate_interval(count: int, exposure: float, level: float = 0.95) -> Interval:
    """Exact (Garwood) interval for an event rate, e.g. false alarms per hour.

    Used for false-alarm rates because the counts are small -- a handful of
    events over well under an hour -- and a normal approximation would put the
    lower bound below zero.
    """
    if exposure <= 0:
        return Interval(float("nan"), float("nan"), float("nan"), level, "garwood")
    alpha = 1.0 - level
    low = 0.0 if count == 0 else _st.chi2.ppf(alpha / 2, 2 * count) / 2.0
    high = _st.chi2.ppf(1 - alpha / 2, 2 * count + 2) / 2.0
    return Interval(count / exposure, low / exposure, high / exposure, level, "garwood exact")


# --------------------------------------------------------------------------- #
# paired tests
# --------------------------------------------------------------------------- #
def mcnemar_exact(b: int, c: int) -> float:
    """Exact two-sided McNemar test on the discordant counts ``b`` and ``c``."""
    n = b + c
    if n == 0:
        return 1.0
    return float(min(1.0, 2.0 * _st.binom.cdf(min(b, c), n, 0.5)))


def wilcoxon_paired(a: Sequence[float], b: Sequence[float]) -> float:
    """Two-sided Wilcoxon signed-rank p-value over paired per-fold scores.

    Returns 1.0 when every difference is zero (scipy raises in that case).
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    mask = np.isfinite(a) & np.isfinite(b)
    diff = a[mask] - b[mask]
    if diff.size == 0 or np.allclose(diff, 0.0):
        return 1.0
    return float(_st.wilcoxon(a[mask], b[mask], zero_method="wilcox").pvalue)


def holm(p_values: dict[str, float]) -> dict[str, float]:
    """Holm-Bonferroni step-down adjustment; returns adjusted p-values."""
    items = sorted(((p, k) for k, p in p_values.items() if np.isfinite(p)))
    m = len(items)
    adjusted: dict[str, float] = {}
    running = 0.0
    for rank, (p, key) in enumerate(items):
        running = max(running, min(1.0, (m - rank) * p))
        adjusted[key] = running
    for key, p in p_values.items():
        adjusted.setdefault(key, float("nan"))
    return adjusted


# --------------------------------------------------------------------------- #
# metric helpers that operate on index subsets
# --------------------------------------------------------------------------- #
def f1_from(y: np.ndarray, pred: np.ndarray) -> float:
    tp = float(np.sum((y == 1) & (pred == 1)))
    fp = float(np.sum((y == 0) & (pred == 1)))
    fn = float(np.sum((y == 1) & (pred == 0)))
    denom = 2 * tp + fp + fn
    return 2 * tp / denom if denom else float("nan")


def auc_from(y: np.ndarray, scores: np.ndarray) -> float:
    """ROC-AUC via the Mann-Whitney statistic, with ties counted half."""
    y = np.asarray(y)
    scores = np.asarray(scores, dtype=float)
    pos = scores[y == 1]
    neg = scores[y == 0]
    if pos.size == 0 or neg.size == 0:
        return float("nan")
    ranks = _st.rankdata(np.concatenate([pos, neg]))
    u = ranks[: pos.size].sum() - pos.size * (pos.size + 1) / 2.0
    return float(u / (pos.size * neg.size))


def recall_from(y: np.ndarray, pred: np.ndarray) -> float:
    positives = np.sum(y == 1)
    return float(np.sum((y == 1) & (pred == 1)) / positives) if positives else float("nan")
