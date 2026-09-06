"""Regular-session clip at the fetch source (PLATFORM-RULES 2026-09-05): a
same-evening Yahoo fetch returns a trailing bucket stamped at the close (16:00)
that a next-day fetch does not; the phantom bar changed DELL's plan geometry."""
import datetime as dt

from zargar.domain import Bar
from zargar.marketstructure.history import clip_to_rth
from zargar.marketstructure.sessions import ET


def _bar(h: int, m: int, tf: str = "1h") -> Bar:
    ts = int(dt.datetime(2026, 9, 3, h, m, tzinfo=ET).timestamp() * 1000)
    return Bar(symbol="DELL", tf=tf, ts=ts, open=1, high=1, low=1, close=1, volume=1)


def test_clip_drops_the_close_bucket_and_premarket_but_keeps_the_session():
    bars = [_bar(9, 0), _bar(9, 30), _bar(10, 30), _bar(15, 30), _bar(16, 0), _bar(17, 30)]
    kept = clip_to_rth(bars, "1h")
    stamps = [dt.datetime.fromtimestamp(b.ts / 1000, ET).strftime("%H:%M") for b in kept]
    assert stamps == ["09:30", "10:30", "15:30"]
    # 1m: 15:59 stays, 16:00 goes
    m = clip_to_rth([_bar(15, 59, "1m"), _bar(16, 0, "1m")], "1m")
    assert [dt.datetime.fromtimestamp(b.ts / 1000, ET).strftime("%H:%M") for b in m] == ["15:59"]
    # daily bars are not intraday: untouched (their stamp is midnight-ish)
    d = [Bar(symbol="DELL", tf="1d", ts=int(dt.datetime(2026, 9, 3, 0, 0, tzinfo=ET).timestamp() * 1000), open=1, high=1, low=1, close=1, volume=1)]
    assert clip_to_rth(d, "1d") == d
