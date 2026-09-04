"""T1.3a extended (theory T-11, MU 2026-09-04): with `seed_window_extremes` the
window's swing high/low becomes a level even with one touch. Default off - the
knob exists so the variant harness can sweep it (`sweep --set seed_window_extremes=true`)."""
import datetime as dt

from zargar.domain import Bar
from zargar.marketstructure.levels import detect_levels
from zargar.marketstructure.rules import MarketRules
from zargar.marketstructure.sessions import ET


def _bars() -> list[Bar]:
    """Three sessions of 30m bars around 100; session 1 prints a single spike to
    110 (the multi-session swing high) that is never revisited."""
    out = []
    for d, spike in ((1, True), (2, False), (3, False)):
        for i in range(13):
            ts = int(dt.datetime(2026, 9, d, 9, 30, tzinfo=ET).timestamp() * 1000) + i * 30 * 60_000
            o = c = 100.0 + (i % 3) * 0.2
            h, lo = o + 0.4, o - 0.4
            if spike and i == 5:
                h = 110.0
            out.append(Bar(symbol="T", tf="30m", ts=ts, open=o, high=h, low=lo, close=c, volume=1000))
    return out


def _has_level_near(levels, price: float, tol: float = 0.5) -> bool:
    return any(abs(float(lv.price) - price) <= tol for lv in levels)


def test_window_extremes_seed_is_off_by_default_and_on_when_asked():
    bars = _bars()
    base = detect_levels(bars, thresholds=MarketRules(), timeframe="30m")
    assert not _has_level_near(base, 110.0), [lv.price for lv in base]
    on = detect_levels(bars, thresholds=MarketRules(seed_window_extremes=True), timeframe="30m")
    hit = [lv for lv in on if abs(float(lv.price) - 110.0) <= 0.5]
    assert hit and hit[0].kind == "resistance" and "T1.3a-window" in hit[0].sources, [(lv.price, lv.sources) for lv in on]
