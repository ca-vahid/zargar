"""The stream handler's fast paths (2026-09-28) are bit-identical to the original functions."""
import datetime as dt
import random
from zoneinfo import ZoneInfo

from zargar.brokers.alpaca import AlpacaQuoteFeed, parse_rfc3339_ms

ET = ZoneInfo("America/New_York")


def _orig_parse(t: str) -> int:
    s = t.replace("Z", "+00:00")
    if "." in s:
        head, rest = s.split(".", 1)
        off = ""
        for i, ch in enumerate(rest):
            if ch in "+-":
                rest, off = rest[:i], rest[i:]
                break
        s = f"{head}.{rest[:6].ljust(6, '0')}{off}"
    return int(dt.datetime.fromisoformat(s).timestamp() * 1000)


def test_parse_matches_the_original_for_every_precision():
    rnd = random.Random(7)
    base = dt.datetime(2026, 3, 1, tzinfo=dt.timezone.utc)
    for _ in range(20000):
        t = base + dt.timedelta(seconds=rnd.randrange(0, 400 * 86400), microseconds=rnd.randrange(0, 10**6))
        digits = rnd.choice([1, 3, 6, 9])
        frac = f"{t.microsecond:06d}{rnd.randrange(0, 1000):03d}"[:digits]
        s = t.strftime("%Y-%m-%dT%H:%M:%S") + "." + frac + rnd.choice(["Z", "+00:00", "-04:00"])
        assert parse_rfc3339_ms(s) == _orig_parse(s), s
    for s in ("2026-09-28T13:30:00Z", "2026-09-28T13:30:00+00:00", "2026-09-28T13:30:00.5Z"):
        assert parse_rfc3339_ms(s) == _orig_parse(s)


def test_minute_info_matches_a_direct_conversion_across_dst():
    rnd = random.Random(11)
    starts = [dt.datetime(2026, 3, 8, 5, 0, tzinfo=dt.timezone.utc), dt.datetime(2026, 11, 1, 4, 0, tzinfo=dt.timezone.utc),
              dt.datetime(2026, 9, 28, 13, 0, tzinfo=dt.timezone.utc)]
    for st in starts:
        for _ in range(3000):
            ms = int(st.timestamp() * 1000) + rnd.randrange(0, 12 * 3600 * 1000)
            t = dt.datetime.fromtimestamp(ms / 1000, ET)
            m = t.hour * 60 + t.minute
            assert AlpacaQuoteFeed._session_day(ms) == t.strftime("%Y-%m-%d")
            assert AlpacaQuoteFeed._is_regular(ms) == (t.weekday() < 5 and 570 <= m < 960)
