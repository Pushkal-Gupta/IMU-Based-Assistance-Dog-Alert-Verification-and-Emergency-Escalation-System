"""Sensor-transfer and mounting perturbations, applied to held-out windows.

The model is trained on a Shimmer3 strapped to the collar at one orientation.
The collar it ships on is an MPU6050 that will sit at whatever angle the collar
slips to.  No hardware was available to measure that transfer, so this module
simulates the specific ways the two differ, each parameterised from the
MPU6050 datasheet (InvenSense PS-MPU-6000A-00 rev 3.4) rather than invented:

=====================  ==========================================  ===========
perturbation           model                                       source
=====================  ==========================================  ===========
collar rotation        rigid rotation of both triads               mounting
white noise            density x sqrt(bandwidth)                   datasheet
zero-rate / 0-g bias   constant offset, uniform within tolerance   datasheet
sensitivity error      per-axis gain, uniform within tolerance     datasheet
range and resolution   clip to full scale, quantise to 16-bit LSB  datasheet
sampling jitter        sample at jittered instants, treat uniform  ESP32 timer
rate mismatch          resample before windowing                   config
=====================  ==========================================  ===========

Windows are ``(n, width, 6)`` arrays of ``[ax, ay, az, gx, gy, gz]`` in m/s^2
and deg/s, the units the dataset and the firmware both use.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

G = 9.80665

#: MPU6050 datasheet values (PS-MPU-6000A-00 rev 3.4, tables 6.1 and 6.2).
MPU6050 = {
    "gyro_noise_density_dps_rthz": 0.005,
    "accel_noise_density_ug_rthz": 400.0,
    "gyro_zero_rate_offset_dps": 20.0,      # initial ZRO tolerance, +/-
    "accel_zero_g_offset_mg_xy": 50.0,      # +/-
    "accel_zero_g_offset_mg_z": 80.0,       # +/-
    "gyro_sensitivity_tolerance": 0.03,     # +/- 3 %
    "accel_sensitivity_tolerance": 0.03,    # +/- 3 % (calibration tolerance)
    "gyro_full_scale_dps": 2000.0,          # as configured in collar.ino
    "accel_full_scale_g": 8.0,              # as configured in collar.ino
    "adc_bits": 16,
}


# --------------------------------------------------------------------------- #
# rotations
# --------------------------------------------------------------------------- #
def axis_rotation(axis: int, angle_rad: np.ndarray) -> np.ndarray:
    """``(n, 3, 3)`` rotations by ``angle_rad`` about device axis ``axis``."""
    c, s = np.cos(angle_rad), np.sin(angle_rad)
    n = np.size(angle_rad)
    R = np.zeros((n, 3, 3))
    i, j = [(1, 2), (0, 2), (0, 1)][axis]
    R[:, axis, axis] = 1.0
    R[:, i, i] = c
    R[:, j, j] = c
    R[:, i, j] = -s
    R[:, j, i] = s
    return R


def random_rotations(n: int, rng: np.random.Generator) -> np.ndarray:
    """Uniform random rotations in SO(3), via normalised quaternions."""
    q = rng.normal(size=(n, 4))
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    w, x, y, z = q.T
    return np.stack(
        [
            np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], -1),
            np.stack([2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], -1),
            np.stack([2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)], -1),
        ],
        axis=1,
    )


def rotate(windows: np.ndarray, R: np.ndarray) -> np.ndarray:
    """Rotate both triads of every window; ``R`` is ``(n, 3, 3)`` or ``(3, 3)``."""
    R = np.broadcast_to(R, (windows.shape[0], 3, 3))
    out = np.empty_like(windows)
    out[:, :, 0:3] = np.einsum("nij,ntj->nti", R, windows[:, :, 0:3])
    out[:, :, 3:6] = np.einsum("nij,ntj->nti", R, windows[:, :, 3:6])
    return out


# --------------------------------------------------------------------------- #
# sensor error model
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SensorModel:
    noise_scale: float = 1.0          # multiple of datasheet noise density
    bias_scale: float = 1.0           # multiple of datasheet offset tolerance
    gain_scale: float = 1.0           # multiple of datasheet sensitivity tolerance
    quantise: bool = True
    gyro_full_scale_dps: float = MPU6050["gyro_full_scale_dps"]
    accel_full_scale_g: float = MPU6050["accel_full_scale_g"]
    bandwidth_hz: float = 25.6        # Nyquist at 51.2 Hz


def apply_sensor(windows: np.ndarray, model: SensorModel, rng: np.random.Generator) -> np.ndarray:
    """Pass Shimmer3 windows through an MPU6050-like error model.

    Biases and gains are drawn once per window -- one window is one wearing of
    one device for this purpose -- and noise per sample.
    """
    n, width, _ = windows.shape
    out = windows.copy()
    d = MPU6050
    # gain
    g_tol = model.gain_scale * np.array([d["accel_sensitivity_tolerance"]] * 3 + [d["gyro_sensitivity_tolerance"]] * 3)
    out *= 1.0 + rng.uniform(-1, 1, (n, 1, 6)) * g_tol
    # bias
    acc_bias = np.array([d["accel_zero_g_offset_mg_xy"]] * 2 + [d["accel_zero_g_offset_mg_z"]]) * 1e-3 * G
    gyr_bias = np.full(3, d["gyro_zero_rate_offset_dps"])
    b = np.concatenate([acc_bias, gyr_bias]) * model.bias_scale
    out += rng.uniform(-1, 1, (n, 1, 6)) * b
    # white noise
    sd_acc = d["accel_noise_density_ug_rthz"] * 1e-6 * G * np.sqrt(model.bandwidth_hz)
    sd_gyr = d["gyro_noise_density_dps_rthz"] * np.sqrt(model.bandwidth_hz)
    sd = np.array([sd_acc] * 3 + [sd_gyr] * 3) * model.noise_scale
    out += rng.normal(size=out.shape) * sd
    # range and resolution
    fs_acc = model.accel_full_scale_g * G
    fs_gyr = model.gyro_full_scale_dps
    out[:, :, 0:3] = np.clip(out[:, :, 0:3], -fs_acc, fs_acc)
    out[:, :, 3:6] = np.clip(out[:, :, 3:6], -fs_gyr, fs_gyr)
    if model.quantise:
        levels = 2 ** (d["adc_bits"] - 1)
        out[:, :, 0:3] = np.round(out[:, :, 0:3] / (fs_acc / levels)) * (fs_acc / levels)
        out[:, :, 3:6] = np.round(out[:, :, 3:6] / (fs_gyr / levels)) * (fs_gyr / levels)
    return out


def clip_gyro(windows: np.ndarray, full_scale_dps: float) -> np.ndarray:
    out = windows.copy()
    out[:, :, 3:6] = np.clip(out[:, :, 3:6], -full_scale_dps, full_scale_dps)
    return out


# --------------------------------------------------------------------------- #
# timing
# --------------------------------------------------------------------------- #
def jitter(windows: np.ndarray, sigma_s: float, fs_hz: float, rng: np.random.Generator) -> np.ndarray:
    """Sample each window at jittered instants, then treat them as uniform.

    This is what a late timer interrupt does: the value is read slightly off
    its nominal time but stored in the nominal slot.
    """
    n, width, ch = windows.shape
    t = np.arange(width) / fs_hz
    out = np.empty_like(windows)
    for i in range(n):
        tj = np.clip(t + rng.normal(0.0, sigma_s, width), t[0], t[-1])
        for c in range(ch):
            out[i, :, c] = np.interp(tj, t, windows[i, :, c])
    return out


def resample(windows: np.ndarray, factor: float) -> np.ndarray:
    """Resample by ``factor`` (new_rate / old_rate) and re-cut to the same width.

    Models a collar sampling at a different rate than the model was trained at
    while still cutting fixed-sample windows: e.g. a 50 Hz collar running a
    model trained at 51.2 Hz sees each window cover 2.4% more time.
    """
    n, width, ch = windows.shape
    src = np.arange(width)
    dst = np.arange(width) / factor
    keep = dst <= src[-1]
    out = np.empty_like(windows)
    for i in range(n):
        for c in range(ch):
            col = np.interp(dst[keep], src, windows[i, :, c])
            out[i, :, c] = np.pad(col, (0, width - col.size), mode="edge")
    return out
