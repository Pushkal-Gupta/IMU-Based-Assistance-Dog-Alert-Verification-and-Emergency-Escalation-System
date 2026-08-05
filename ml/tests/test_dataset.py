"""Dataset loading, event curation and segmentation."""

from __future__ import annotations

import numpy as np
import pytest

from canine_alert.config import DEFAULT_CONFIG
from canine_alert.dataset import Event, curate_events, dataset_summary, spin_events
from canine_alert.segmentation import segment_events


def test_loads_every_published_file(recordings):
    assert len(recordings) == 78
    assert {r.session for r in recordings} == {"1st_A22C", "2nd_0098", "3rd_A22C"}


def test_annotation_count_matches_publication(recordings):
    """The paper reports 135 labelled spin alerts; the release must contain them."""
    total = sum(len(spin_events(r)) for r in recordings)
    assert total == 135


def test_annotated_durations_match_publication(recordings):
    """Paper: 135 events, 1.02-5.42 s each, mean 2.58 s, median 2.52 s.

    Those figures assume a 50 Hz sample rate.  The release is actually clocked
    at 51.2 Hz, so durations computed from the true rate are 2.4% shorter --
    which is exactly what we assert here.  Getting the same numbers as the paper
    requires dividing sample counts by 50, and this test is the record of why we
    do not.
    """
    summary = dataset_summary(recordings)
    assert summary["median_fs_hz"] == pytest.approx(51.2, abs=0.05)

    stats = summary["event_duration_s"]
    rate_correction = 51.2 / 50.0
    assert stats["mean"] * rate_correction == pytest.approx(2.58, abs=0.05)
    assert stats["median"] * rate_correction == pytest.approx(2.52, abs=0.05)
    assert stats["min"] * rate_correction == pytest.approx(1.02, abs=0.05)
    assert stats["max"] * rate_correction == pytest.approx(5.42, abs=0.05)


def test_labels_are_binarised(recordings):
    """The raw column holds 0/200; downstream code must only ever see 0/1."""
    for rec in recordings[:5]:
        assert set(np.unique(rec.labels)).issubset({0, 1})


def test_every_annotated_spin_yields_a_positive_event(recordings):
    events = curate_events(recordings, DEFAULT_CONFIG)
    positives = [e for e in events if e.label == 1]
    # A spin in a recording shorter than one curated event cannot be used.
    usable = sum(
        len(spin_events(r))
        for r in recordings
        if len(r.frame) >= DEFAULT_CONFIG.event_samples(r.fs_hz)
    )
    assert len(positives) == usable


def test_positive_events_contain_spin_and_negatives_do_not(recordings):
    for event in curate_events(recordings, DEFAULT_CONFIG):
        if event.label == 1:
            assert event.sample_labels.any(), f"{event.event_id} is labelled positive but has no spin"
        else:
            assert not event.sample_labels.any(), f"{event.event_id} leaks a spin sample"


def test_negative_events_keep_a_guard_from_any_spin(recordings):
    """A negative event abutting a spin would teach the model the wrong boundary."""
    by_source = {r.source_id: r for r in recordings}
    for event in curate_events(recordings, DEFAULT_CONFIG):
        if event.label != 0:
            continue
        rec = by_source[event.source_id]
        guard = int(round(DEFAULT_CONFIG.negative_guard_seconds * rec.fs_hz))
        lo = max(0, event.start_index - guard)
        hi = min(len(rec.labels), event.start_index + event.n_samples + guard)
        assert not rec.labels[lo:hi].any(), f"{event.event_id} is within the guard of a spin"


def test_events_are_uniform_length(recordings):
    events = curate_events(recordings, DEFAULT_CONFIG)
    lengths = {e.n_samples for e in events}
    assert len(lengths) == 1, f"expected one event length, got {sorted(lengths)}"


def test_event_yields_exactly_the_configured_window_count(recordings):
    """The paper aggregates five 2.6 s segments per event; so must we."""
    events = curate_events(recordings, DEFAULT_CONFIG)
    segments = segment_events(events, DEFAULT_CONFIG)
    _, counts = np.unique(segments.event_ids, return_counts=True)
    assert set(counts.tolist()) == {DEFAULT_CONFIG.event_windows}


def test_window_geometry_matches_the_paper_durations(recordings):
    events = curate_events(recordings, DEFAULT_CONFIG)
    segments = segment_events(events, DEFAULT_CONFIG)
    fs = segments.fs_hz
    assert segments.windows.shape[1] / fs == pytest.approx(2.6, abs=0.01)
    assert DEFAULT_CONFIG.stride_samples(fs) / fs == pytest.approx(1.3, abs=0.01)


def test_onset_is_the_first_spin_sample():
    labels = np.zeros(400, dtype=np.int8)
    labels[128:256] = 1
    event = Event(
        event_id="synthetic",
        group="g",
        source_id="s",
        label=1,
        fs_hz=51.2,
        signals=np.zeros((400, 6)),
        sample_labels=labels,
        start_index=0,
    )
    assert event.onset_s == pytest.approx(128 / 51.2)


def test_windows_never_straddle_two_events(recordings):
    """Segment-level splitting is only leak-free if each window has one parent."""
    events = curate_events(recordings, DEFAULT_CONFIG)
    segments = segment_events(events, DEFAULT_CONFIG)
    by_event = {}
    for event_id, group in zip(segments.event_ids, segments.groups):
        by_event.setdefault(event_id, set()).add(group)
    assert all(len(groups) == 1 for groups in by_event.values())
