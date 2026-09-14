"""Nearby completed supply/support must survive shorter trigger geometry."""
import datetime as dt

import pytest

from zargar.marketstructure.market_calendar import next_trading_day
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy, automatic_review
from zargar.techniques.options_cartel.data import DailyBar
from zargar.techniques.options_cartel.rules import CartelRules
from zargar.techniques.options_cartel.screen import ListingFacts, screen_listing
from zargar.techniques.options_cartel.setups import SetupParameters, analyze_setups


def general_history(kind='inside_day', direction='long'):
    rows = [(100+i*.1, 102+i*.1, 98+i*.1, 100+i*.1, 2_000_000) for i in range(60)]
    rows += [(107, 109, 106, 107, 1_000_000)]*7
    rows += [(108, 110.2, 107, 108, 1_000_000),
             (109, 110, 108.5, 109, 1_000_000),
             (109, 109.8, 108.8, 109.5, 1_000_000)]
    if kind == 'ma_pullback':
        rows[-1] = (109, 110, 107, 109.5, 1_000_000)
    elif kind == 'breakout_retest':
        rows[-3:] = [(107, 109, 106, 107, 1_000_000),
                     (109, 110.2, 108.9, 109.8, 1_000_000),
                     (109.7, 110, 108.95, 109.5, 1_000_000)]
    bars = daily_rows(rows)
    indices = {symbol: [DailyBar(symbol=symbol, session=b.session, open=100+i*.01,
        high=102+i*.01, low=98+i*.01, close=100+i*.01, volume=2_000_000)
        for i, b in enumerate(bars)] for symbol in ('SPY', 'QQQ')}
    if direction == 'short':
        def mirror(b):
            return b.model_copy(update={'open': 216-b.open, 'high': 216-b.low,
                                        'low': 216-b.high, 'close': 216-b.close})
        bars = [mirror(b) for b in bars]
        indices = {symbol: [mirror(b) for b in values] for symbol, values in indices.items()}
    return bars, indices


def daily_rows(rows):
    bars, day = [], dt.date(2026, 5, 1)
    for opening, high, low, close, volume in rows:
        bars.append(DailyBar(symbol='TEST', session=day, open=opening, high=high,
                             low=low, close=close, volume=volume))
        day = next_trading_day(day)
    return bars


def research(bars, *, direction='long', at=None):
    return {'history': bars, 'as_of_ms': at or bars[-1].closes_at, 'direction': direction}


def general_analysis(bars, indices, direction='long', at=None):
    at = at or bars[-1].closes_at
    rules = CartelRules.for_profile('september_2026', require_industry_rank=False)
    facts = ListingFacts(symbol='TEST', observed_at=at, source='synthetic regression', market_cap=1e9)
    screen = screen_listing(bars, facts, indices, rules, at, direction=direction)
    assert screen['screenPassed']
    result = analyze_setups(bars, indices['SPY'], screen, SetupParameters(), at, direction=direction)
    assert all(c['status'] == 'pass' for c in result['checks'])
    return result


@pytest.mark.parametrize('direction', ['long', 'short'])
@pytest.mark.parametrize('kind', ['inside_day', 'ma_pullback', 'breakout_retest'])
def test_recent_pivot_blocks_shorter_setup_instead_of_inventing_room(kind, direction):
    bars, indices = general_history(kind, direction)
    analysis = general_analysis(bars, indices, direction)
    candidate = next(c for c in analysis['candidates'] if c['setup'] == kind)
    assert candidate['trigger'] == pytest.approx(110 if direction == 'long' else 106)
    assert candidate['targets'] == pytest.approx([110.2 if direction == 'long' else 105.8])
    assert automatic_review(research(bars, direction=direction), {'candidates': [candidate]}, PreparationPolicy()) is None
    selected = automatic_review(research(bars, direction=direction), analysis, PreparationPolicy())
    assert selected is None or selected.setup != kind


def ignition_history(event_high=113.2):
    rows = [(100, 101.5, 98.5, 100, 1_000_000)]*60
    rows += [(104, event_high, 103, 110, 4_000_000)]
    rows += [(109, 113-i*.2, 107, 109, 1_000_000) for i in range(5)]
    return daily_rows(rows)


def ignition_analysis(bars, at=None):
    at = at or bars[-1].closes_at
    screen = {'symbol': 'TEST', 'direction': 'long', 'asOfMs': at,
              'screenPassed': True, 'researchPassed': True}
    return analyze_setups(bars, bars, screen, SetupParameters(family='post_ignition'), at)


def test_confirmed_ignition_high_blocks_fibonacci_room():
    bars = ignition_history()
    analysis = ignition_analysis(bars)
    candidate, = analysis['candidates']
    assert candidate['evidence']['stage'] == 'setup_ready'
    assert candidate['trigger'] == 113
    assert candidate['targets'] == [113.2]
    assert automatic_review(research(bars), analysis, PreparationPolicy(profile='post_ignition_2026_09_11')) is None


@pytest.mark.parametrize('family', ['general', 'ignition'])
def test_saved_truncated_candidate_cannot_hide_nearer_pivot(family):
    if family == 'general':
        bars, indices = general_history()
        analysis = general_analysis(bars, indices)
        candidate = next(c for c in analysis['candidates'] if c['setup'] == 'inside_day')
    else:
        bars = ignition_history()
        candidate, = ignition_analysis(bars)['candidates']
    saved = {**candidate, 'targets': [], 'evidence': {k: v for k, v in candidate['evidence'].items()
                                                   if k != 'targetBaseStart'}}
    assert automatic_review(research(bars), {'candidates': [saved]}, PreparationPolicy()) is None
    # An older measured distant pivot cannot conceal the newly recovered nearer one.
    assert automatic_review(research(bars), {'candidates': [{**saved, 'targets': [150.]}]}, PreparationPolicy()) is None


@pytest.mark.parametrize('legacy_evidence', [False, True])
def test_ignition_anchor_uses_actual_consolidation_boundary(legacy_evidence):
    bars = ignition_history(event_high=113)
    bars[0] = bars[0].model_copy(update={'low': 90})
    analysis = ignition_analysis(bars)
    candidate, = analysis['candidates']
    assert candidate['targets'] == []
    assert candidate['evidence']['targetBaseStart'] == bars[61].session.isoformat()
    if legacy_evidence:
        candidate['evidence'].pop('targetBaseStart')
    # The 60 bars before consolidation exclude the old 90 low. A generic
    # 10-session truncation would retain it and exaggerate all three targets.
    for generic_base_sessions in (3, 10, 20):
        policy = PreparationPolicy(profile='post_ignition_2026_09_11',
                                   setups=SetupParameters(base_sessions=generic_base_sessions))
        review = automatic_review(research(bars), analysis, policy)
        assert review.reviewed_targets == pytest.approx((116.944, 121.961, 127.5))


@pytest.mark.parametrize('kind,offset', [('base', 10), ('inside_day', 2), ('ma_pullback', 1), ('breakout_retest', 1)])
def test_candidate_records_its_actual_target_anchor_boundary(kind, offset):
    bars, indices = general_history(kind)
    candidate = next(c for c in general_analysis(bars, indices)['candidates'] if c['setup'] == kind)
    assert candidate['evidence']['targetBaseStart'] == bars[-offset].session.isoformat()


def test_inside_day_fallback_excludes_older_extreme_outside_its_anchor_window():
    bars, indices = general_history()
    bars[-3] = bars[-3].model_copy(update={'high': 109})
    candidate = next(c for c in general_analysis(bars, indices)['candidates'] if c['setup'] == 'inside_day')
    assert candidate['targets'] == []
    review = automatic_review(research(bars), {'candidates': [candidate]}, PreparationPolicy())
    # Sixty sessions before the mother begin at index 8, whose low is 98.8.
    assert review.reviewed_targets == pytest.approx((113.0464, 116.9216, 121.2))


@pytest.mark.parametrize('family', ['general', 'ignition'])
def test_future_candles_cannot_change_targets_or_anchor_boundary(family):
    if family == 'general':
        bars, indices = general_history()
        before = general_analysis(bars, indices)
    else:
        bars = ignition_history()
        before = ignition_analysis(bars)
    at = bars[-1].closes_at
    future = bars[-1].model_copy(update={'session': next_trading_day(bars[-1].session),
                                       'open': 200., 'high': 1000., 'low': .01, 'close': 200.})
    after = general_analysis(bars+[future], indices, at=at) if family == 'general' else ignition_analysis(bars+[future], at)
    assert after == before
    assert automatic_review(research(bars+[future], at=at), before, PreparationPolicy()) == automatic_review(
        research(bars, at=at), before, PreparationPolicy())


def test_future_right_neighbor_cannot_confirm_the_current_last_bar_pivot():
    bars = ignition_history(event_high=113)
    bars[-1] = bars[-1].model_copy(update={'high': 113.2})
    candidate = {'setup': 'base', 'trigger': 113., 'invalidation': 107., 'targets': [], 'contextPassed': True}
    at = bars[-1].closes_at
    future = bars[-1].model_copy(update={'session': next_trading_day(bars[-1].session), 'high': 113.1})
    before = automatic_review(research(bars, at=at), {'candidates': [candidate]}, PreparationPolicy())
    assert before is not None and before.reviewed_targets[0] > 113.2
    assert automatic_review(research(bars+[future], at=at), {'candidates': [candidate]}, PreparationPolicy()) == before
    assert automatic_review(research(bars+[future]), {'candidates': [candidate]}, PreparationPolicy()) is None


def test_whole_contract_allocation_policy_is_explicit_and_practice_only():
    assert PreparationPolicy().exit_allocation_policy == 'legacy'
    assert PreparationPolicy(exit_allocation_policy='whole_contracts_v2').exit_allocation_policy == 'whole_contracts_v2'
    with pytest.raises(ValueError, match='Practice-only'):
        PreparationPolicy(workspace='live', exit_allocation_policy='whole_contracts_v2')
    bars = ignition_history(event_high=113)
    review = automatic_review(research(bars), ignition_analysis(bars),
                              PreparationPolicy(exit_allocation_policy='whole_contracts_v2'))
    assert review.exit_campaign.allocation_policy == 'whole_contracts_v2'
