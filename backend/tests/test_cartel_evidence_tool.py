"""Pure checks for the read-only Cartel evidence tool (no database)."""
from zargar.tools.cartel_evidence import MINUTE, bucketize, session_open_ms


def _row(ts, o, h, l, c, v, source="exchange"):
    return {"ts": ts, "open": o, "high": h, "low": l, "close": c, "volume": v, "source": source}


def test_session_open_is_0930_et_in_daylight_time():
    assert session_open_ms("2026-09-16") == 1789565400000  # 2026-09-16 13:30:00 UTC


def test_bucketize_prefers_exchange_rows_and_keeps_gaps_visible():
    opens = session_open_ms("2026-09-16")
    rows = []
    for i in range(15):  # complete first bucket, one minute duplicated as sampled + exchange
        rows.append(_row(opens + i * MINUTE, 10, 11, 9, 10.5, 100))
    rows.append(_row(opens + 3 * MINUTE, 10, 20, 9, 10.5, 999, source="sampled"))  # must lose to the exchange row
    rows.append(_row(opens + 15 * MINUTE, 10.5, 10.6, 10.4, 10.55, 50))  # partial second bucket
    table = bucketize(rows, opens, 15, minutes=45)
    assert [b["n"] for b in table] == [15, 1, 0]
    first = table[0]
    assert first["exchange"] == 15 and first["high"] == 11 and first["volume"] == 1500
    assert abs(first["closeLocationLong"] - 0.75) < 1e-9 and abs(first["closeLocationShort"] - 0.25) < 1e-9
    assert table[2] == {"slot": 2, "start": opens + 30 * MINUTE, "n": 0}
