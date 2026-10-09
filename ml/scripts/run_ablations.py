#!/usr/bin/env python3
"""Baselines on raw windows, ablations, the embedded size/accuracy front, and
sensor-transfer robustness.  Writes ``ml/artifacts/ablations.json``.

Every number is leave-one-group-out with all fitting inside the fold, exactly
as in ``run_experiments.py``.

    python ml/scripts/run_ablations.py           # ~10 min on 8+ cores
    python ml/scripts/run_ablations.py --quick   # CNN and grids trimmed
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from dataclasses import replace
from pathlib import Path

import numpy as np
from joblib import Parallel, delayed
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from canine_alert import robustness as rb  # noqa: E402
from canine_alert import stats  # noqa: E402
from canine_alert.config import DEFAULT_ARTIFACT_DIR, DEFAULT_CONFIG, DEFAULT_DATASET_DIR  # noqa: E402
from canine_alert.evaluate import prepare  # noqa: E402
from canine_alert.features import SIGNAL_NAMES, extract_features  # noqa: E402
from canine_alert.models import EMBEDDED_MODEL, build_model, predict_scores  # noqa: E402
from canine_alert.raw_models import CNNClassifier, RocketClassifier  # noqa: E402
from run_experiments import to_jsonable  # noqa: E402

warnings.filterwarnings("ignore")


# --------------------------------------------------------------------------- #
# generic LOGO over an arbitrary fit/score pair
# --------------------------------------------------------------------------- #
def _fold(fit_score, data, test_group):
    test = data.groups == test_group
    train = ~test
    if len(np.unique(data.y[train])) < 2:
        return test_group, None
    return test_group, fit_score(np.flatnonzero(train), np.flatnonzero(test))


def logo_scores(data, fit_score, n_jobs=-1):
    groups = sorted(set(data.groups.tolist()))
    out = Parallel(n_jobs=n_jobs)(delayed(_fold)(fit_score, data, g) for g in groups)
    scores = np.full(len(data.y), np.nan)
    for g, s in out:
        if s is not None:
            scores[data.groups == g] = s
    return scores


def summarise_scores(data, scores, threshold=0.5):
    ok = np.isfinite(scores)
    y, s, g = data.y[ok], scores[ok], data.groups[ok]
    pred = (s >= threshold).astype(int)
    # event recall/specificity under the paper's OR rule
    ev = data.segments.event_ids[ok]
    uniq, inv = np.unique(ev, return_inverse=True)
    hit = np.zeros(uniq.size, dtype=int)
    np.add.at(hit, inv, pred)
    lab = np.zeros(uniq.size, dtype=int)
    lab[inv] = data.segments.event_labels[ok]
    ev_pred = (hit >= 1).astype(int)
    auc_ci, _ = stats.cluster_bootstrap(g, lambda i: stats.auc_from(y[i], s[i]), n_boot=500)
    return {
        "segment_f1": stats.f1_from(y, pred),
        "segment_auc": stats.auc_from(y, s),
        "segment_auc_ci": auc_ci.as_dict(),
        "event_recall": stats.recall_from(lab, ev_pred),
        "event_specificity": stats.recall_from(1 - lab, 1 - ev_pred),
        "event_f1": stats.f1_from(lab, ev_pred),
    }


# --------------------------------------------------------------------------- #
# model factories (module level so joblib can pickle them)
# --------------------------------------------------------------------------- #
class FeatureModel:
    def __init__(self, data, name=EMBEDDED_MODEL, cols=None, config=DEFAULT_CONFIG, clf=None, X=None):
        self.data, self.name, self.cols, self.config, self.clf = data, name, cols, config, clf
        self.X = data.features if X is None else X

    def __call__(self, train, test):
        cols = np.arange(self.X.shape[1]) if self.cols is None else self.cols
        names = [self.data.feature_names[c] for c in cols]
        model = build_model(self.name, names, self.config)
        if self.clf is not None:
            model.steps[-1] = ("clf", self.clf)
        if "n_jobs" in model.named_steps["clf"].get_params():
            model.set_params(clf__n_jobs=1)
        model.fit(self.X[train][:, cols], self.data.y[train])
        return predict_scores(model, self.X[test][:, cols])


class RawModel:
    def __init__(self, data, factory):
        self.data, self.factory = data, factory

    def __call__(self, train, test):
        import torch

        torch.set_num_threads(1)
        model = self.factory()
        model.fit(self.data.segments.windows[train], self.data.y[train])
        return model.predict_proba(self.data.segments.windows[test])[:, 1]


def cnn_factory():
    return CNNClassifier(epochs=30)


def rocket_factory():
    return RocketClassifier(n_kernels=2000)


def signal_columns(names, signals):
    return np.array([i for i, n in enumerate(names) if n.split("_")[0] in signals or
                     (n.startswith("corr_") and all(p in signals for p in n.split("_")[1:]))])


# --------------------------------------------------------------------------- #
# robustness: perturb test windows only, model trained on clean data
# --------------------------------------------------------------------------- #
class PerturbedModel:
    def __init__(self, data, perturb, seed, augment=0, cols=None):
        self.data, self.perturb, self.seed, self.augment = data, perturb, seed, augment
        self.cols = np.arange(data.features.shape[1]) if cols is None else cols

    def __call__(self, train, test):
        rng = np.random.default_rng(self.seed + int(test[0]))
        fs = self.data.segments.fs_hz
        W, y = self.data.segments.windows, self.data.y
        Xtr, ytr = self.data.features[train], y[train]
        if self.augment:
            # Rotation augmentation: add `augment` randomly rotated copies of
            # every training window.
            extra = [extract_features(rb.rotate(W[train], rb.random_rotations(train.size, rng)), fs)
                     for _ in range(self.augment)]
            Xtr = np.vstack([Xtr, *extra])
            ytr = np.concatenate([ytr] * (self.augment + 1))
        names = [self.data.feature_names[c] for c in self.cols]
        model = build_model(EMBEDDED_MODEL, names, DEFAULT_CONFIG)
        model.set_params(clf__n_jobs=1)
        model.fit(Xtr[:, self.cols], ytr)
        Wt = self.perturb(W[test], rng, fs)
        return predict_scores(model, extract_features(Wt, fs)[:, self.cols])


def _p_identity(W, rng, fs):
    return W


class Rot:
    def __init__(self, axis=None, deg=None):
        self.axis, self.deg = axis, deg

    def __call__(self, W, rng, fs):
        if self.axis is None:
            return rb.rotate(W, rb.random_rotations(W.shape[0], rng))
        # One rotation per held-out group: the collar slipped once.
        return rb.rotate(W, rb.axis_rotation(self.axis, np.array([np.deg2rad(self.deg)]))[0])


class Sensor:
    def __init__(self, **kw):
        self.kw = kw

    def __call__(self, W, rng, fs):
        return rb.apply_sensor(W, rb.SensorModel(**self.kw), rng)


class GyroClip:
    def __init__(self, fs_dps):
        self.fs_dps = fs_dps

    def __call__(self, W, rng, fs):
        return rb.clip_gyro(W, self.fs_dps)


class Jitter:
    def __init__(self, sigma_ms):
        self.sigma_ms = sigma_ms

    def __call__(self, W, rng, fs):
        return rb.jitter(W, self.sigma_ms / 1000.0, fs, rng)


class Resample:
    def __init__(self, factor):
        self.factor = factor

    def __call__(self, W, rng, fs):
        return rb.resample(W, self.factor)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    started = time.time()
    data = prepare(args.dataset_dir, DEFAULT_CONFIG)
    names = data.feature_names
    out: dict = {}

    def run(label, fit_score, bucket):
        t = time.time()
        res = summarise_scores(data, logo_scores(data, fit_score))
        bucket[label] = res
        print(f"  {label:42s} F1={res['segment_f1']:.3f} AUC={res['segment_auc']:.3f} "
              f"evRec={res['event_recall']:.3f} evSpec={res['event_specificity']:.3f} ({time.time()-t:.0f}s)",
              flush=True)

    # 1. baselines --------------------------------------------------------
    print("[1/5] baselines", flush=True)
    out["baselines"] = {}
    run("random_forest_embedded", FeatureModel(data), out["baselines"])
    run("hist_gradient_boosting", FeatureModel(
        data, clf=HistGradientBoostingClassifier(max_depth=6, learning_rate=0.1, max_iter=200,
                                                 class_weight="balanced", random_state=42)), out["baselines"])
    run("rocket_2000", RawModel(data, rocket_factory), out["baselines"])
    run("cnn_1d", RawModel(data, cnn_factory), out["baselines"])
    out["cnn_parameters"] = CNNClassifier(epochs=1).fit(data.segments.windows[:64], data.y[:64]).n_parameters()

    # 2. feature-family ablations -----------------------------------------
    print("[2/5] feature families", flush=True)
    families = {
        "all_159": SIGNAL_NAMES,
        "magnitudes_only": ("amag", "gmag"),
        "per_axis_only": ("ax", "ay", "az", "gx", "gy", "gz"),
        "gyro_only": ("gx", "gy", "gz", "gmag"),
        "accel_only": ("ax", "ay", "az", "amag"),
        "gyro_magnitude_only": ("gmag",),
    }
    out["feature_families"] = {}
    for label, signals in families.items():
        cols = signal_columns(names, set(signals))
        run(f"{label} ({cols.size} features)", FeatureModel(data, cols=cols), out["feature_families"])
        out["feature_families"][f"{label} ({cols.size} features)"]["n_features"] = int(cols.size)

    # 3. selection size and window length ---------------------------------
    print("[3/5] selection size, window length", flush=True)
    out["n_selected"] = {}
    for k in ((5, 20, 40) if args.quick else (5, 10, 20, 40, 80)):
        run(f"k={k}", FeatureModel(data, config=replace(DEFAULT_CONFIG, n_selected_features=k)), out["n_selected"])
    out["window_seconds"] = {}
    for w in ((2.1, 2.6, 3.1) if args.quick else (1.6, 2.1, 2.6, 3.1, 3.6)):
        cfg = replace(DEFAULT_CONFIG, window_seconds=w, stride_seconds=w / 2)
        d2 = prepare(args.dataset_dir, cfg)
        res = summarise_scores(d2, logo_scores(d2, FeatureModel(d2, config=cfg)))
        out["window_seconds"][str(w)] = res
        print(f"  window {w} s: F1={res['segment_f1']:.3f} AUC={res['segment_auc']:.3f} "
              f"evRec={res['event_recall']:.3f}", flush=True)

    # 4. embedded Pareto front --------------------------------------------
    print("[4/5] embedded size/accuracy front", flush=True)
    front = []
    trees = (8, 32, 128) if args.quick else (4, 8, 16, 32, 64, 128)
    depths = (4, 8, 12) if args.quick else (4, 6, 8, 10, 12)
    for n_trees in trees:
        for depth in depths:
            clf = RandomForestClassifier(n_estimators=n_trees, max_depth=depth, min_samples_leaf=4,
                                         class_weight="balanced_subsample", random_state=42)
            res = summarise_scores(data, logo_scores(data, FeatureModel(data, clf=clf)))
            full = build_model(EMBEDDED_MODEL, names, DEFAULT_CONFIG)
            full.steps[-1] = ("clf", clf)
            full.fit(data.features, data.y)
            # Same layout as export.ForestTables.flash_bytes (14 bytes per node,
            # 2 per tree offset), computed directly because the largest forests
            # here overflow the int16 node index the exporter emits.
            n_nodes = sum(t.tree_.node_count for t in full.named_steps["clf"].estimators_)
            flash = 14 * n_nodes + 2 * n_trees
            row = {"n_trees": n_trees, "max_depth": depth, "flash_bytes": int(flash),
                   "n_nodes": int(n_nodes), "fits_int16_export": n_nodes < 32767, **res}
            front.append(row)
            print(f"  trees={n_trees:3d} depth={depth:2d} {flash/1024:6.1f} KiB "
                  f"AUC={res['segment_auc']:.3f} evF1={res['event_f1']:.3f}", flush=True)
    out["embedded_front"] = front

    # 5. robustness --------------------------------------------------------
    print("[5/5] sensor-transfer robustness", flush=True)
    perturbations = {
        "clean": _p_identity,
        "rot_x_30deg": Rot(0, 30), "rot_x_90deg": Rot(0, 90), "rot_x_180deg": Rot(0, 180),
        "rot_y_30deg": Rot(1, 30), "rot_y_90deg": Rot(1, 90), "rot_y_180deg": Rot(1, 180),
        "rot_z_30deg": Rot(2, 30), "rot_z_90deg": Rot(2, 90), "rot_z_180deg": Rot(2, 180),
        "rot_random_so3": Rot(None),
        "mpu6050_datasheet": Sensor(),
        "mpu6050_noise_x10": Sensor(noise_scale=10.0, bias_scale=0.0, gain_scale=0.0),
        "mpu6050_bias_only": Sensor(noise_scale=0.0, gain_scale=0.0),
        "mpu6050_gain_only": Sensor(noise_scale=0.0, bias_scale=0.0),
        "gyro_full_scale_250dps": GyroClip(250.0),
        "gyro_full_scale_1000dps": GyroClip(1000.0),
        "jitter_2ms": Jitter(2.0), "jitter_5ms": Jitter(5.0),
        "rate_50hz": Resample(50.0 / 51.2), "rate_45hz": Resample(45.0 / 51.2), "rate_60hz": Resample(60.0 / 51.2),
    }
    if args.quick:
        perturbations = {k: perturbations[k] for k in ("clean", "rot_z_90deg", "rot_random_so3", "mpu6050_datasheet")}
    out["robustness"] = {}
    for augment in (0, 2):
        bucket = out["robustness"].setdefault("augmented" if augment else "clean_training", {})
        for label, perturb in perturbations.items():
            if augment and not (label.startswith("rot") or label in ("clean", "mpu6050_datasheet")):
                continue
            run(label, PerturbedModel(data, perturb, seed=7, augment=augment), bucket)

    # The rotation-invariant variant: magnitude features only.  Invariant to
    # any rigid rotation by construction, so the rotation rows should not move.
    mag_cols = signal_columns(names, {"amag", "gmag"})
    bucket = out["robustness"].setdefault("magnitudes_only", {})
    for label, perturb in perturbations.items():
        if label.startswith("rot") or label in ("clean", "mpu6050_datasheet", "jitter_5ms", "rate_50hz"):
            run(label, PerturbedModel(data, perturb, seed=7, cols=mag_cols), bucket)

    out["runtime_seconds"] = round(time.time() - started, 1)
    path = args.artifact_dir / "ablations.json"
    path.write_text(json.dumps(to_jsonable(out), indent=2) + "\n")
    print(f"wrote {path} in {out['runtime_seconds']} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
