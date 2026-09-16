"""P2 follow-up: the timestamp and sequence must belong to one ordering key.

Pure functions only; no database, application or network access.
"""
from types import SimpleNamespace

from zargar.technique.source_revisions import _advance_watermark, _compare_order, parse_ts


def test_same_timestamp_forward_sequence_is_newer():
    at = parse_ts("2026-09-14T13:05:00+00:00")
    assert _compare_order(at, 6, at, 5) == "newer"


def test_newer_event_time_does_not_keep_the_old_events_sequence():
    previous = parse_ts("2026-09-14T13:00:00+00:00")
    current = parse_ts("2026-09-14T13:05:00+00:00")
    note = SimpleNamespace(meta={})
    _advance_watermark(note, previous, 100)
    assert _compare_order(current, 5, previous, 100) == "newer"
    _advance_watermark(note, current, 5)
    watermark = note.meta["sourceWatermark"]
    assert _compare_order(current, 6, parse_ts(watermark["at"]), watermark["seq"]) == "newer", (
        "The accepted newer event was (13:05, 5), not the synthetic pair (13:05, 100); "
        "its later same-time sequence 6 must not be discarded as older"
    )
