"""Pure source-continuation-v1 review cases; no database, engine, or network.

Copy to backend/tests and run against reviewed commit 4902b30.
"""
import datetime as dt

from zargar.tools.em_source_candidates import evaluate_candidate


ET = dt.timezone(dt.timedelta(hours=-4))
ROW = {
    "date": "2026-09-15", "symbol": "T", "direction": "long",
    "level": 100.0, "target": 106.0,
    "availableAt": "2026-09-15T09:20:00-04:00", "retrospective": False,
}


def bars():
    result = []
    start = dt.datetime(2026, 9, 15, 9, 30, tzinfo=ET)
    for minute in range(11):
        close = 99.0 if minute < 5 else 100.2
        result.append({
            "ts": int((start + dt.timedelta(minutes=minute)).timestamp() * 1000),
            "open": close, "high": 106.0 if minute == 10 else close + 0.1,
            "low": close - 0.2, "close": close,
        })
    return result


def test_source_cannot_enter_before_its_available_at_time():
    # All observations (including the target touch) predate this source's availability.
    result = evaluate_candidate(bars(), {**ROW, "availableAt": "2026-09-15T10:00:00-04:00"})
    assert "entry" not in result, result
    assert result["outcome"] == "unknown", result


def test_missing_opening_range_minute_is_unknown_not_replaced_by_a_later_bar():
    tape = bars()
    del tape[2]  # The 09:32 minute and therefore its possible low are unknown.
    result = evaluate_candidate(tape, ROW)
    assert result["outcome"] == "unknown", result
    assert "entry" not in result, result


def test_next_stored_bar_after_a_gap_is_not_the_next_minute_open():
    tape = bars()
    tape = tape[:6] + tape[10:]  # 09:35 confirmation; missing 09:36-09:39 bars.
    result = evaluate_candidate(tape, ROW)
    assert result["outcome"] == "unknown", result
    assert "entry" not in result, result
