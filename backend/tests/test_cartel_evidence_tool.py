"""Pure checks for the read-only Cartel evidence tool (no database, no network)."""
from zargar.tools.cartel_evidence import MINUTE, annotate_display_crossings, bucketize, classify_minutes, session_window


def _row(ts, o, h, l, c, v, source="exchange"):
    return {"ts": ts, "open": o, "high": h, "low": l, "close": c, "volume": v, "source": source}


def test_session_window_uses_the_exchange_calendar():
    opens, closes = session_window("2026-09-16")
    assert opens == 1789565400000 and (closes - opens) // MINUTE == 390  # 09:30..16:00 ET on a normal day
    opens, closes = session_window("2026-11-27")  # Black Friday early close 13:00 ET
    assert (closes - opens) // MINUTE == 210


def test_classify_minutes_names_absent_and_sampled_only_without_calling_them_empty():
    opens, _ = session_window("2026-09-16")
    rows = [_row(opens, 10, 11, 9, 10.5, 100), _row(opens + MINUTE, 10, 10, 10, 10, 7, source="sampled")]
    classes = classify_minutes(rows, opens, opens + 3 * MINUTE)
    assert [classes[opens + i * MINUTE]["class"] for i in range(3)] == ["exchange", "sampled-only", "absent"]
    assert classes[opens + 2 * MINUTE] == {"ts": opens + 2 * MINUTE, "class": "absent"}


def test_partial_buckets_report_known_values_and_never_a_crossing():
    opens, _ = session_window("2026-09-16")
    closes = opens + 45 * MINUTE
    rows = [_row(opens + i * MINUTE, 10, 11, 9, 10.5, 100) for i in range(15)]           # complete, trusted
    rows.append(_row(opens + 3 * MINUTE, 10, 20, 9, 10.5, 999, source="sampled"))         # loses to the exchange row
    rows += [_row(opens + 15 * MINUTE + i * MINUTE, 12, 12.5, 11.5, 12.2, 50) for i in range(14)]  # one minute absent
    rows[-1]["source"] = "sampled"                                                         # and one untrusted
    table = bucketize(rows, opens, closes, 15)
    assert [b["n"] for b in table] == [15, 14, 0]
    assert table[0]["partial"] is False and table[0]["classes"] == {"exchange": 15} and table[0]["volume"] == 1500
    second = table[1]
    assert second["partial"] is True and second["missingMinutes"] == ["09:59"] and second["untrustedMinutes"] == ["09:58"]
    assert second["volume"] == 700 and second["high"] == 12.5  # known values stay visible
    assert table[2]["n"] == 0 and table[2]["classes"] == {"absent": 15}
    plan = {"direction": "long", "trigger": 10.4, "targets": [13.0], "volume_baseline": {"0": 1000.0, "1": 100.0}}
    annotate_display_crossings(table, plan)
    assert table[0]["crossedDisplay"] is True and abs(table[0]["volumeRatio"] - 1.5) < 1e-9
    assert table[1]["crossedDisplay"] is None and "volumeRatio" not in table[1]  # partial: nothing judged
    assert table[2]["crossedDisplay"] is None
