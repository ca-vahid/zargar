"""Source numerical rules and causal data boundaries, without network or orders."""
import datetime as dt

import pytest
from pydantic import ValidationError

from zargar.marketstructure.market_calendar import is_trading_day
from zargar.techniques.options_cartel.data import DailyBar, complete_weeks, completed_daily
from zargar.techniques.options_cartel.rules import CartelRules
from zargar.techniques.options_cartel.screen import ListingFacts, focus_list, market_regime, screen_listing


@pytest.mark.parametrize('profile', ['september_2026', 'september_2026_video', 'june_2026',
                                     'june_2026_image', 'may_2026', 'may_2026_image'])
def test_profile_only_api_rules_match_named_factory(profile):
    assert CartelRules.model_validate({'profile': profile}) == CartelRules.for_profile(profile)


def test_may_image_preserves_text_market_context_but_uses_visible_stock_filters():
    text, image = CartelRules.for_profile('may_2026'), CartelRules.for_profile('may_2026_image')
    assert text.stock_ema_periods == (8, 21) and text.require_positive_change
    assert image.stock_ema_periods == (21, 50) and not image.require_positive_change
    assert image.market_ema_periods == (8, 21) and image.focus_count == 10
    assert (image.volume_basis, image.volume_period, image.min_adr_pct) == ('average', 10, 2.)
    assert 'S04' in image.snapshot()['sources']


def test_explicit_serialized_profile_values_are_not_replaced_by_defaults():
    raw = CartelRules.for_profile('may_2026').model_dump()
    raw.update(stock_ema_periods=(21, 50), min_adr_pct=3., require_positive_change=False)
    restored = CartelRules.model_validate(raw)
    assert restored.stock_ema_periods == (21, 50) and restored.min_adr_pct == 3.
    assert restored.require_positive_change is False


def test_industry_tie_range_is_unknown_and_fresh_ranks_do_not_refresh_old_stock_facts():
    bars, facts, indices, at = inputs()
    facts = facts.model_copy(update={'week_rank': 11, 'week_rank_best': 9,
        'month_rank': 2, 'rank_observed_at': at, 'rank_data_as_of_ms': at})
    result = screen_listing(bars, facts, indices, CartelRules(), at)
    gate = next(g for g in result['gates'] if g['label'].startswith('Industry ranks'))
    assert gate['status'] == 'unknown'
    old = facts.model_copy(update={'observed_at': at-8*86_400_000, 'week_rank': 1, 'week_rank_best': 1})
    result = screen_listing(bars, old, indices, CartelRules(), at)
    assert next(g for g in result['gates'] if 'capitalization' in g['label'])['status'] == 'unknown'
    assert next(g for g in result['gates'] if g['label'].startswith('Industry ranks'))['status'] == 'unknown'


def test_future_rank_values_are_not_displayed_as_historical_facts():
    bars, facts, indices, at = inputs()
    facts = facts.model_copy(update={'rank_observed_at': at+1, 'rank_data_as_of_ms': at})
    result = screen_listing(bars, facts, indices, CartelRules(), at)
    assert result['facts']['market_cap'] == facts.market_cap
    assert result['facts']['week_rank'] is None and result['facts']['month_rank'] is None


def series(symbol="TEST", *, down=False, count=80):
    day = dt.date(2026, 1, 2)
    out = []
    while len(out) < count:
        if is_trading_day(day):
            price = 200 - len(out) if down else 100 + len(out)
            out.append(DailyBar(symbol=symbol, session=day, open=price, close=price,
                                high=price * 1.03, low=price * .97, volume=1_000_000))
        day += dt.timedelta(days=1)
    return out


def inputs(*, down=False):
    bars = series(down=down)
    at = bars[-1].closes_at
    facts = ListingFacts(symbol="TEST", observed_at=at, source="test-snapshot",
                         market_cap=500_000_000, industry="Example", week_rank=3, month_rank=8,
                         rank_direction="short" if down else "long")
    return bars, facts, {sym: series(sym, down=down) for sym in ("SPY", "QQQ")}, at


def test_numerical_source_profiles_are_distinct_and_snapshotted():
    may = CartelRules.for_profile("may_2026")
    june = CartelRules.for_profile("june_2026")
    september = CartelRules.for_profile("september_2026")
    assert may.min_adr_pct == 2 and may.stock_ema_periods == (8, 21)
    assert june.min_adr_pct == 3 and june.stock_ema_periods == (21, 50)
    assert not june.require_industry_rank and september.require_industry_rank
    snapshot = september.snapshot()
    assert CartelRules.model_validate(snapshot["rules"]) == september
    assert "septemberScreen" in snapshot["engineeringDefinitions"]
    assert snapshot["sources"] == ["S01", "S02", "S06"]


def test_video_profile_has_strict_relative_volume_gate_without_changing_legacy_rules():
    bars, facts, indices, at = inputs()
    rules = CartelRules.for_profile("september_2026_video")
    assert rules == CartelRules.model_validate({"profile": "september_2026_video"})
    assert rules.min_adr_pct == 2 and rules.volume_basis == "average"
    assert rules.min_relative_volume == 1 and rules.snapshot()["sources"] == ["S24"]
    assert CartelRules().min_relative_volume is None
    result = screen_listing(bars, facts, indices, rules, at)
    assert result["metrics"]["relativeVolume"] == 1 and not result["screenPassed"]
    bars[-1] = bars[-1].model_copy(update={"volume": 2_000_000})
    result = screen_listing(bars, facts, indices, rules, at)
    assert result["metrics"]["relativeVolume"] == 2 and result["screenPassed"]
    # The tested session must not enter its own denominator.
    assert result["metrics"]["liquidityVolume"] == 1_100_000


def test_video_relative_volume_is_unknown_without_a_nonzero_complete_baseline():
    bars, facts, indices, at = inputs()
    rules = CartelRules.for_profile("september_2026_video")
    for history in (bars[-10:], [b.model_copy(update={"volume": 0}) for b in bars[:-1]] + bars[-1:]):
        result = screen_listing(history, facts, indices, rules, at)
        assert result["metrics"]["relativeVolume"] is None and not result["screenPassed"]


@pytest.mark.parametrize("override", [{"stock_ema_periods": ()}, {"market_ema_periods": (0,)},
                                      {"stock_ema_periods": (8, 8)}, {"min_price": float("nan")}])
def test_invalid_rules_rejected_even_on_direct_construction(override):
    with pytest.raises(ValidationError):
        CartelRules(**override)


def test_regular_session_close_and_half_day_are_respected():
    bar = DailyBar(symbol="X", session=dt.date(2026, 11, 27), open=10, high=11, low=9, close=10, volume=100)
    assert completed_daily([bar], bar.closes_at - 1) == []
    assert completed_daily([bar], bar.closes_at) == [bar]
    assert dt.datetime.fromtimestamp(bar.closes_at / 1000, dt.UTC).hour == 18


def test_incomplete_and_missing_week_do_not_masquerade_as_volume_contraction():
    dates = [dt.date(2026, 11, d) for d in (23, 24, 25, 27)]  # Thanksgiving week
    bars = [DailyBar(symbol="X", session=d, open=10, high=11, low=9, close=10, volume=100) for d in dates]
    assert complete_weeks(bars, bars[-1].closes_at - 1) == []
    assert complete_weeks(bars[:-1], bars[-1].closes_at) == []
    week = complete_weeks(bars, bars[-1].closes_at)[0]
    assert week["sessions"] == 4 and week["volume"] == 400


def test_future_daily_bars_cannot_change_a_historical_screen():
    bars, facts, indices, at = inputs()
    rules = CartelRules()
    expected = screen_listing(bars, facts, indices, rules, at)
    later = series(count=90)[80:]
    later_indices = {s: series(s, count=90) for s in indices}
    actual = screen_listing(bars + later, facts, later_indices, rules, at)
    assert expected == actual
    assert expected["screenPassed"]


@pytest.mark.parametrize("updates", [{"market_cap": None}, {"week_rank": None}, {"month_rank": None},
                                     {"industry": None}, {"rank_direction": "short"}])
def test_missing_or_wrong_direction_fundamentals_remain_unknown(updates):
    bars, facts, indices, at = inputs()
    result = screen_listing(bars, facts.model_copy(update=updates), indices, CartelRules(), at)
    assert not result["screenPassed"]
    assert any(g["status"] == "unknown" for g in result["gates"])


def test_future_fundamentals_are_not_exposed_as_historical_facts():
    bars, facts, indices, at = inputs()
    result = screen_listing(bars, facts.model_copy(update={"observed_at": at + 1}), indices, CartelRules(), at)
    assert result["facts"]["available"] is False
    assert "market_cap" not in result["facts"]
    industry = next(g for g in result["gates"] if "Industry ranks" in g["label"])
    assert industry["value"]["weekRank"] is None
    assert any(g["status"] == "unknown" for g in result["gates"])


@pytest.mark.parametrize("offset", [1, -8 * 86_400_000])
def test_future_and_stale_metadata_cannot_be_used_in_replay(offset):
    bars, facts, indices, at = inputs()
    result = screen_listing(bars, facts.model_copy(update={"observed_at": at + offset}), indices, CartelRules(), at)
    assert not result["screenPassed"]


def test_bearish_context_is_supported_without_share_shorting_or_orders():
    bars, facts, indices, at = inputs(down=True)
    result = screen_listing(bars, facts, indices, CartelRules(), at, direction="short")
    assert result["market"]["direction"] == "short" and result["screenPassed"]
    assert "order" not in result and "arm" not in result


def test_one_missing_index_is_unknown_and_disagreement_is_mixed():
    bars, facts, indices, at = inputs()
    assert market_regime({"SPY": indices["SPY"]}, CartelRules(), at)["direction"] == "unknown"
    indices["QQQ"] = series("QQQ", down=True)
    assert market_regime(indices, CartelRules(), at)["direction"] == "mixed"
    assert not screen_listing(bars, facts, indices, CartelRules(), at)["screenPassed"]


def test_missing_trading_day_and_conflicting_duplicates_are_data_errors():
    bars, facts, indices, at = inputs()
    with pytest.raises(ValueError, match="missing regular-session"):
        screen_listing(bars[:20] + bars[21:], facts, indices, CartelRules(), at)
    duplicate = bars[-1].model_copy(update={"volume": 200})
    with pytest.raises(ValueError, match="conflicting"):
        completed_daily(bars + [duplicate], at)
    assert completed_daily(bars + [bars[-1]], at) == bars


def test_stale_price_history_is_not_current_just_because_indicators_exist():
    bars, facts, indices, at = inputs()
    result = screen_listing(bars[:-1], facts, indices, CartelRules(), at)
    assert not result["screenPassed"]
    assert next(g for g in result["gates"] if g["rule"] == "DATA")["status"] == "fail"


def test_source_thresholds_are_strict_and_industry_cutoff_inclusive():
    bars, facts, indices, at = inputs()
    result = screen_listing(bars, facts.model_copy(update={"market_cap": 300_000_000}), indices, CartelRules(), at)
    assert not result["screenPassed"]
    assert screen_listing(bars, facts.model_copy(update={"week_rank": 10}), indices, CartelRules(), at)["screenPassed"]
    assert not screen_listing(bars, facts.model_copy(update={"week_rank": 11}), indices, CartelRules(), at)["screenPassed"]


def test_focus_list_excludes_incomplete_reads_and_uses_volume_order():
    rules = CartelRules(focus_count=2)
    reads = [{"symbol": s, "screenPassed": passed, "metrics": {"dailyVolume": v}}
             for s, v, passed in [("Z", 20, True), ("A", 20, True), ("B", 100, False), ("C", 10, True)]]
    assert [r["symbol"] for r in focus_list(reads, rules)] == ["A", "Z"]
    with pytest.raises(ValueError, match="duplicate"):
        focus_list(reads + [reads[0]], rules)


def test_june_image_and_text_profiles_preserve_the_documented_discrepancy():
    text = CartelRules.for_profile("june_2026")
    image = CartelRules.for_profile("june_2026_image")
    assert text.min_adr_pct == 3 and text.volume_basis == "last_session"
    assert image.min_adr_pct == 2 and image.volume_basis == "average" and image.volume_period == 10
    assert image.stock_ema_periods == (21, 50)
    assert image.min_volume == 500000 and image.min_market_cap == 300000000


def test_average_volume_does_not_mistake_a_quiet_consolidation_day_for_illiquidity():
    bars, facts, indices, at = inputs()
    bars[-1] = bars[-1].model_copy(update={"volume": 100000})
    image = screen_listing(bars, facts, indices, CartelRules.for_profile("june_2026_image"), at)
    text = screen_listing(bars, facts, indices, CartelRules.for_profile("june_2026"), at)
    assert image["screenPassed"] and not text["screenPassed"]
    assert image["metrics"]["liquidityVolume"] == 910000


def test_one_volume_spike_cannot_pass_a_low_average_volume_screen():
    bars, facts, indices, at = inputs()
    bars[-10:] = [b.model_copy(update={"volume": 100000}) for b in bars[-10:]]
    bars[-1] = bars[-1].model_copy(update={"volume": 1000000})
    image = screen_listing(bars, facts, indices, CartelRules.for_profile("june_2026_image"), at)
    assert not image["screenPassed"] and image["metrics"]["liquidityVolume"] == 190000


def test_average_volume_requires_full_window_and_strict_threshold():
    bars, facts, indices, at = inputs()
    rules = CartelRules.for_profile("june_2026_image", volume_period=252)
    result = screen_listing(bars, facts, indices, rules, at)
    assert result["metrics"]["liquidityVolume"] is None
    assert next(g for g in result["gates"] if "average volume" in g["label"])["status"] == "unknown"
    bars[-10:] = [b.model_copy(update={"volume": 500000}) for b in bars[-10:]]
    assert not screen_listing(bars, facts, indices, CartelRules.for_profile("june_2026_image"), at)["screenPassed"]


def test_old_snapshot_keeps_its_volume_semantics():
    old = CartelRules.for_profile("june_2026").model_dump(mode="json")
    old.pop("volume_basis")
    old.pop("volume_period")
    restored = CartelRules.model_validate(old)
    assert restored.volume_basis == "last_session"


def test_image_profile_defaults_work_at_json_boundary_without_overwriting_explicit_values():
    direct = CartelRules.model_validate({"profile": "june_2026_image"})
    assert direct == CartelRules.for_profile("june_2026_image")
    changed = CartelRules.model_validate({"profile": "june_2026_image", "volume_period": 20})
    assert changed.volume_period == 20
