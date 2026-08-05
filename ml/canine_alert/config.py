"""Central configuration for the detection pipeline.

Every tunable that appears in the written report lives here so that the docs and
the code cannot drift apart.  Values marked "paper" reproduce Brady et al. 2025;
values marked "ours" belong to the verification/escalation contribution.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET_DIR = REPO_ROOT / "spinning_dataset"
DEFAULT_ARTIFACT_DIR = REPO_ROOT / "ml" / "artifacts"

#: Channels used for classification.  The Shimmer3 also exposes a wide-range
#: accelerometer and a magnetometer; the paper uses only the low-noise
#: accelerometer and the gyroscope, and so do we, because the target hardware
#: (MPU6050) has no magnetometer and a single accelerometer range.
IMU_CHANNELS: Sequence[str] = (
    "Accel_LN_X",
    "Accel_LN_Y",
    "Accel_LN_Z",
    "Gyro_X",
    "Gyro_Y",
    "Gyro_Z",
)

ACCEL_CHANNELS: Sequence[str] = IMU_CHANNELS[:3]
GYRO_CHANNELS: Sequence[str] = IMU_CHANNELS[3:]

LABEL_COLUMN = "Spin"
TIME_COLUMN = "Timestamp"


@dataclass(frozen=True)
class PipelineConfig:
    """Parameters for segmentation, feature selection and verification."""

    # --- sampling -----------------------------------------------------------
    # The published dataset is recorded at a nominal 51.2 Hz (the Shimmer3
    # 1024/20 divider).  The paper rounds this to 50 Hz.  We measure the true
    # rate from the timestamps and derive window lengths in samples from it, so
    # window *durations* match the paper exactly even though the sample counts
    # differ slightly.
    nominal_fs_hz: float = 51.2

    # --- segmentation (paper) ----------------------------------------------
    window_seconds: float = 2.6
    stride_seconds: float = 1.3
    #: A window is labelled 'spin' when at least this fraction of its samples
    #: fall inside an annotated spin event.
    positive_window_fraction: float = 0.5

    # --- event curation (paper) --------------------------------------------
    #: Number of overlapping windows a curated event must yield.  The paper
    #: evaluates 7.8 s events and describes them as having "five constituent
    #: 2.6 s segments", so we derive the event length from the window geometry
    #: (``width + 4 * stride``) instead of hard-coding 7.8 s.  At the dataset's
    #: true 51.2 Hz that is 401 samples = 7.83 s, which both matches the paper's
    #: stated segment count and keeps the tiling exact.
    event_windows: int = 5
    #: Minimum guard between a curated negative event and any annotated spin, so
    #: negative events are behaviourally "pure".
    negative_guard_seconds: float = 1.0

    # --- feature selection (paper) -----------------------------------------
    variance_threshold: float = 0.1
    correlation_threshold: float = 0.95
    n_selected_features: int = 20

    # --- multi-stage verification (ours) ------------------------------------
    #: The collar only raises an alert when `verify_k` of the last `verify_n`
    #: consecutive windows are classified as spin.  With a 1.3 s stride this
    #: turns a single 2.6 s snapshot into a sustained-behaviour requirement,
    #: which is what separates a trained double-spin alert from a one-off
    #: shake-off or play spin.
    verify_k: int = 2
    verify_n: int = 3
    #: Minimum classifier probability for a window to count as a positive vote.
    verify_probability_threshold: float = 0.5
    #: After an alert fires, suppress further alerts for this long so that one
    #: behavioural episode produces exactly one escalation.
    refractory_seconds: float = 60.0

    # --- reproducibility ----------------------------------------------------
    random_state: int = 42
    #: Fraction of curated events held out in the within-subject protocol.
    test_size: float = 0.2

    def window_samples(self, fs_hz: float) -> int:
        return int(round(self.window_seconds * fs_hz))

    def stride_samples(self, fs_hz: float) -> int:
        return int(round(self.stride_seconds * fs_hz))

    def event_samples(self, fs_hz: float) -> int:
        return self.window_samples(fs_hz) + (self.event_windows - 1) * self.stride_samples(fs_hz)

    def event_seconds(self, fs_hz: float) -> float:
        return self.event_samples(fs_hz) / fs_hz

    def as_dict(self) -> dict:
        return asdict(self)


DEFAULT_CONFIG = PipelineConfig()


@dataclass(frozen=True)
class EscalationConfig:
    """Timing contract of the escalation layer (ours).

    These values are the defaults shipped in the relay app and the backend; both
    read them from the same document (``docs/04-escalation-protocol.md``).
    """

    #: T1 - how long the owner has to acknowledge before the caregiver is paged.
    owner_ack_seconds: float = 60.0
    #: T2 - how long the caregiver has to acknowledge before the emergency
    #: contact is paged.
    caregiver_ack_seconds: float = 120.0
    #: Heartbeat the relay sends to the backend.  If the backend misses this
    #: many consecutive heartbeats while an alert is open, it escalates on the
    #: relay's behalf (covers "the owner's phone died" as a failure mode).
    relay_heartbeat_seconds: float = 15.0
    relay_missed_heartbeats_before_takeover: int = 3
    #: Maximum age of a GPS fix that may be attached to an escalation message.
    max_location_age_seconds: float = 300.0
    #: Notification delivery retries before the channel is declared failed.
    notify_max_attempts: int = 3
    notify_retry_backoff_seconds: float = 5.0


DEFAULT_ESCALATION_CONFIG = EscalationConfig()
