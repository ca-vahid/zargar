"""Measured setup families and causal context; fixtures are synthetic, not P&L claims."""
import datetime as dt

import pytest

from zargar.marketstructure.market_calendar import is_trading_day
from zargar.techniques.options_cartel.data import DailyBar
from zargar.techniques.options_cartel.setups import SetupParameters, analyze_setups


def histories():
    day = dt.date(2026, 1, 2)
    bars, index = [], []
    while len(bars) < 80:
        if is_trading_day(day):
            i = len(bars)
            price = 100+i*.5 if i < 60 else 130+(i-60)*1.5 if i < 70 else 145
            bars.append(DailyBar(symbol="TEST", session=day, open=price, high=price+2,
                                 low=price-2, close=price, volume=3_000_000 if i < 70 else 1_000_000))
            index.append(DailyBar(symbol="SPY", session=day, open=100, high=101, low=99, close=100, volume=100))
        day += dt.timedelta(days=1)
    return bars, index


def read(bars, index, *, direction="long", at=None, passed=True, parameters=None):
    at = at or bars[-1].closes_at
    return analyze_setups(bars, index, {"asOfMs": at, "symbol": "TEST", "direction": direction,
                                       "screenPassed": passed}, parameters or SetupParameters(), at,
                          direction=direction)


def test_base_context_is_measured_and_targets_are_not_invented():
    bars, index = histories()
    result = read(bars, index)
    base = next(c for c in result["candidates"] if c["setup"] == "base")
    assert base["contextPassed"]
    assert base["trigger"] == 147 and base["invalidation"] == 143
    assert base["reviewRequired"] and base["needsTargets"] and base["targets"] == []
    assert base["evidence"]["volumeRatio"] == pytest.approx(1/3)


@pytest.mark.parametrize("kind", ["flag", "pennant", "wedge"])
def test_contracting_pattern_families_have_distinct_geometry(kind):
    bars, index = histories()
    for j in range(10):
        if kind == "pennant":
            high, low = 150-j*.45, 140+j*.40
        elif kind == "wedge":
            high, low = 152-j*.5, 142-j*.2
        else:
            high, low = 149-j*.3, 143-j*.3
        mid = (high+low)/2
        bars[70+j] = bars[70+j].model_copy(update={"high": high, "low": low, "open": mid, "close": mid})
    result = read(bars, index)
    assert kind in {c["setup"] for c in result["candidates"]}
    if kind in ("pennant", "wedge"):
        assert next(c for c in result["candidates"] if c["setup"] == kind)["evidence"]["tightens"]


def test_inside_day_uses_mother_bar_boundaries():
    bars, index = histories()
    bars[-2] = bars[-2].model_copy(update={"high": 148, "low": 142})
    result = read(bars, index)
    candidate = next(c for c in result["candidates"] if c["setup"] == "inside_day")
    assert candidate["trigger"] == 148 and candidate["invalidation"] == 142


def test_ma_pullback_retains_which_averages_were_touched():
    bars, index = histories()
    result = read(bars, index)
    candidate = next(c for c in result["candidates"] if c["setup"] == "ma_pullback")
    assert 8 in candidate["evidence"]["touchedEmas"]


def test_ascending_triangle_requires_repeated_ceiling_and_rising_support():
    bars, index = histories()
    for j in range(10):
        high, low = 150., 140+j*.4
        bars[70+j] = bars[70+j].model_copy(update={'high': high, 'low': low,
                                                 'open': (high+low)/2, 'close': (high+low)/2})
    candidate = next(c for c in read(bars, index)['candidates'] if c['setup'] == 'ascending_triangle')
    assert candidate['trigger'] == 150 and candidate['invalidation'] == 140
    assert candidate['evidence']['ceilingTouches'] == 10 and candidate['reviewRequired']
    assert candidate['contextPassed']
    assert not any(c['setup'] == 'ascending_triangle' for c in read(bars, index, direction='short')['candidates'])
    for j in range(10):
        bars[70+j] = bars[70+j].model_copy(update={'low': 140.})
    assert not any(c['setup'] == 'ascending_triangle' for c in read(bars, index)['candidates'])


def test_triangle_label_does_not_override_failed_market_context():
    bars, index = histories()
    for j in range(10):
        bars[70+j] = bars[70+j].model_copy(update={'high': 150., 'low': 140+j*.4})
    triangle = next(c for c in read(bars, index, passed=False)['candidates'] if c['setup'] == 'ascending_triangle')
    assert triangle['contextPassed'] is False


def test_breakout_retest_uses_a_level_from_before_the_break():
    bars, index = histories()
    bars[-2] = bars[-2].model_copy(update={"open": 147, "high": 150, "low": 146, "close": 149})
    bars[-1] = bars[-1].model_copy(update={"open": 149, "high": 149.5, "low": 146.9, "close": 148})
    result = read(bars, index)
    candidate = next(c for c in result["candidates"] if c["setup"] == "breakout_retest")
    assert candidate["evidence"]["retestLevel"] == 147
    assert candidate["trigger"] == 149.5 and candidate["invalidation"] == 146.9


def test_future_daily_input_cannot_improve_a_historical_setup():
    bars, index = histories()
    at = bars[-1].closes_at
    next_day = bars[-1].session + dt.timedelta(days=1)
    while not is_trading_day(next_day):
        next_day += dt.timedelta(days=1)
    future = DailyBar(symbol="TEST", session=next_day, open=200, high=220, low=180, close=210, volume=9_000_000)
    assert read(bars, index, at=at) == read(bars+[future], index, at=at)


def test_failed_screen_and_missing_benchmark_cannot_be_overridden_by_a_pattern():
    bars, index = histories()
    assert all(not c["contextPassed"] for c in read(bars, index, passed=False)["candidates"])
    result = read(bars, [], passed=True)
    assert all(not c["contextPassed"] for c in result["candidates"])
    assert next(c for c in result["checks"] if c["name"].startswith("Relative"))["status"] == "unknown"


def test_insufficient_weekly_history_and_expanding_volume_are_visible():
    bars, index = histories()
    result = read(bars, index, parameters=SetupParameters(weekly_context_weeks=52))
    assert all(not c["contextPassed"] for c in result["candidates"])
    bars[-10:] = [b.model_copy(update={"volume": 6_000_000}) for b in bars[-10:]]
    result = read(bars, index)
    assert next(c for c in result["checks"] if c["name"].startswith("Volume"))["status"] == "fail"


def test_bearish_geometry_and_relative_weakness_are_supported():
    bars, index = histories()
    mirrored = [b.model_copy(update={"open": 300-b.open, "close": 300-b.close,
                                     "high": 300-b.low, "low": 300-b.high}) for b in bars]
    result = read(mirrored, index, direction="short")
    base = next(c for c in result["candidates"] if c["setup"] == "base")
    assert base["contextPassed"] and base["trigger"] < base["invalidation"]


def test_old_confirmed_pivots_supply_targets_without_future_anchors():
    bars, index = histories()
    bars[30] = bars[30].model_copy(update={"high": 170})
    result = read(bars, index)
    assert result["candidates"][0]["targets"] == [170]


def test_screen_identity_and_asof_must_match():
    bars, index = histories()
    with pytest.raises(ValueError, match="same as-of"):
        analyze_setups(bars, index, {"asOfMs": 0}, SetupParameters(), bars[-1].closes_at)
