"""Pure FM-05 follow-up: an unobserved first confirmation cannot be skipped.

Copy to backend/tests and run against ef98903. No database, engine or network.
"""

import datetime as dt
from zoneinfo import ZoneInfo

from zargar.tools.em_source_candidates import evaluate_candidate


def test_missing_eligible_confirmation_minutes_cannot_be_replaced_by_later_entry():
    start = dt.datetime(2026, 9, 15, 9, 30, tzinfo=ZoneInfo("America/New_York"))

    def bar(minute, price=99.0, high=None):
        return {
            "ts": int((start + dt.timedelta(minutes=minute)).timestamp() * 1000),
            "open": price,
            "high": price + 0.1 if high is None else high,
            "low": price - 0.2,
            "close": price,
        }

    # The opening range is complete, but the whole eligible 09:35-09:59
    # interval is missing. An earlier confirmation/entry may have occurred.
    tape = [bar(i) for i in range(5)] + [bar(30, 100.2), bar(31, 100.2, 106.0)]
    row = {
        "date": "2026-09-15", "symbol": "T", "direction": "long",
        "level": 100.0, "target": 106.0,
        "availableAt": "2026-09-15T09:20:00-04:00",
        "retrospective": False,
    }

    result = evaluate_candidate(tape, row)

    assert result["outcome"] == "unknown", result
    assert "entry" not in result, result
