"""Pure economics regressions. No engine/fresh_db fixtures or runtime services."""
import datetime as dt
from copy import deepcopy
from dataclasses import replace

import pytest

from zargar.domain import Bar
from zargar.marketstructure.sessions import session_bounds
from zargar.techniques.options_cartel.entry import read_entry
from zargar.techniques.options_cartel.exits import ExitCampaign, ExitRung
from zargar.techniques.options_cartel.plans import EntryPolicy
from zargar.techniques.options_cartel.research_economics import (
    ResearchCosts,
    _daily_history,
    compare_entry_variants,
    compare_rankings,
    evaluate_exit_variants,
    shares_vs_skip,
    target_diagnostic,
)

from .test_options_cartel_entry import MIN, OPEN, plan, tape


def setup(*, targets=(55., 63.), end=80, close=48.92):
    p = plan(targets=targets, entry=EntryPolicy(timeframe_minutes=5, require_exchange_bars=True,
        baseline_policy='covered_periods', min_target_r=.25), volume_baseline={i: 1000. for i in range(78)})
    bars = [replace(b, source='exchange') for b in tape()]
    bars += [Bar('HOOD', '1m', OPEN+i*MIN, close, close+.02, close-.02, close, 500,
                 source='exchange') for i in range(10, end)]
    signal = read_entry(p, bars, OPEN+10*MIN)['signal']
    return p, ExitCampaign.for_profile('may_2026', list(targets)), bars, signal


def evaluate(p, campaign, bars, signal, *, quantity=4, **kwargs):
    return evaluate_exit_variants(p, campaign, bars, [], signal=signal, quantity=quantity,
        as_of_ms=bars[-1].ts+MIN, costs={'slippage_bps': 0, 'fee_per_unit': 0, 'fee_per_order': 0}, **kwargs)


def variant(result, name):
    return next(r for r in result['variants'] if r['id'] == name)


def test_rankings_preserve_denominator_inputs_and_support_broad_qualified_pool():
    candidates = [{'id': str(i), 'analysisId': str(i), 'symbol': f'S{i}',
        'ranking': {'structuralTargetR': i, 'dailyVolume': 100, 'directionalRelativeStrength': 200-i},
        'leaderEvidence': {'directionalRelativeStrength': 200-i, 'dailyDollarVolume': 1000}}
        for i in range(150)]
    original = deepcopy(candidates)
    result = compare_rankings(candidates, execution_slots=5)
    assert len(result['baselineOrderIds']) == 150 and len(result['baselineIds']) == 5
    assert result['baselineIds'][0] == '149' and result['leaderIds'][0] == '0'
    assert candidates == original and not result['placesOrders']
    assert not any(r['themeKnown'] for r in result['candidates'])


def test_target_diagnostic_preserves_levels_and_marks_dynamic_first_exit_unknown():
    p, campaign, _, _ = setup()
    original = p.model_dump()
    result = target_diagnostic(p, campaign, entry_price=49., stop=48., quantity=1, evidence_at=OPEN)
    assert result['originalTargets'] == [55., 63.]
    assert result['firstExecutableExit']['kind'] == 'ema'
    assert result['campaignTarget']['passes'] is None
    assert all(t['importance'] == 'unknown' for t in result['targetEvidence'])
    assert p.model_dump() == original


def test_campaign_entry_challenger_is_a_distinct_read_without_erasing_original_target():
    p, _, bars, _ = setup(targets=(48.95, 55.))
    campaign = ExitCampaign.for_profile('june_2026', list(p.targets))
    original = p.model_dump()
    comparison = compare_entry_variants(p, campaign, bars, as_of_ms=OPEN+10*MIN, quantity=2)
    assert comparison['baseline']['signal'] is None
    assert comparison['targetOnlyProbe']['status'] == 'target_only_probe'
    assert not comparison['targetOnlyProbe']['eligibleEntry']
    assert comparison['campaignAware']['signal']['at'] == OPEN+10*MIN
    assert comparison['campaignAware']['comparisonTarget'] == 55.
    assert p.model_dump() == original and comparison['originalTargets'] == [48.95, 55.]
    result = evaluate(p, campaign, bars, comparison['campaignAware']['signal'], quantity=2,
        entry_variant='campaign_static_target_v1')
    assert result['entry']['price'] == pytest.approx(48.92)
    assert result['targetDiagnostic']['originalTargets'] == [48.95, 55.]


def test_target_probe_does_not_relax_volume_or_grant_unknown_quantity_permission():
    p, _, bars, _ = setup(targets=(48.95, 55.))
    campaign = ExitCampaign.for_profile('june_2026', list(p.targets))
    weak = [replace(b, volume=1) if b.ts >= OPEN+5*MIN else b for b in bars]
    read = compare_entry_variants(p, campaign, weak, as_of_ms=OPEN+10*MIN, quantity=None)
    assert read['targetOnlyProbe']['signal'] is None
    assert read['campaignAware']['status'] == 'target_unknown'
    after = compare_entry_variants(p, campaign, bars, as_of_ms=OPEN+10*MIN, quantity=2, signal_after=OPEN+10*MIN)
    assert after['targetOnlyProbe']['signal'] is None and after['campaignAware']['signal'] is None


def test_observed_signal_never_buys_the_earlier_boundary_open():
    p, campaign, bars, signal = setup()
    bars[11] = replace(bars[11], open=49., high=49.02)
    result = evaluate(p, campaign, bars, signal, entry_after=OPEN+10*MIN+5000)
    assert result['entry']['at'] == OPEN+11*MIN
    assert result['entry']['price'] == 49.
    assert all(v['fills'][0]['at'] == OPEN+11*MIN for v in result['variants'])
    late = evaluate(p, campaign, bars, signal, entry_after=OPEN+12*MIN+1)
    assert late['status'] == 'entry_unavailable'


def test_missing_expected_observed_entry_does_not_seek_a_later_convenient_fill():
    p, campaign, bars, signal = setup()
    bars = [b for b in bars if b.ts != OPEN+11*MIN]
    result = evaluate(p, campaign, bars, signal, entry_after=OPEN+10*MIN+5000)
    assert result['status'] == 'entry_unavailable' and not result['variants']


def test_time_cap_uses_next_open_and_preserves_common_entry_cost_accounting():
    p, campaign, bars, signal = setup()
    result = evaluate_exit_variants(p, campaign, bars, [], signal=signal, quantity=4,
        as_of_ms=bars[-1].ts+MIN, costs=ResearchCosts(slippage_bps=2, fee_per_unit=.1, fee_per_order=1))
    baseline, timed = variant(result, 'baseline_v1'), variant(result, 'time_60m_v1')
    assert timed['firstExit']['at'] == OPEN+70*MIN
    assert timed['firstExit']['price'] < 48.92 < timed['fills'][0]['price']
    assert timed['fees'] == pytest.approx(2.8)
    assert timed['netUnderlyingPnl'] == pytest.approx(timed['grossUnderlyingPnl']-2.8)
    assert baseline['remainingQty'] == 4 and timed['remainingQty'] == 0
    assert baseline['fills'][0] == timed['fills'][0]


def test_failed_break_counts_later_opportunity_without_claiming_a_fill():
    p, campaign, bars, signal = setup()
    for i in range(10, 16):
        bars[i] = replace(bars[i], open=48.92 if i == 10 else 48.7, high=48.94, low=48.65, close=48.7)
    for i in range(30, len(bars)):
        bars[i] = replace(bars[i], open=56., high=56.1, low=55.9, close=56.)
    result = evaluate(p, campaign, bars, signal)
    failed = variant(result, 'failed_break_v1')
    assert failed['firstExit']['at'] == OPEN+15*MIN and failed['remainingQty'] == 0
    assert failed['prematureCut'][0]['possiblePrematureCut'] is True
    assert failed['prematureCut'][0]['firstTargetTouchAt'] == OPEN+30*MIN
    assert failed['prematureCut'][0]['foregoneUnderlyingAtCutoff'] > 0


@pytest.mark.parametrize('quantity,expected', [(1, 0), (2, 1), (3, 1)])
def test_weak_strength_trim_is_whole_only_and_does_not_earn_breakeven(quantity, expected):
    p, campaign, bars, signal = setup(close=49.3)
    bars[10] = replace(bars[10], open=48.92, low=48.90)
    result = evaluate(p, campaign, bars, signal, quantity=quantity, weak_environment=True, weak_environment_at=OPEN)
    trimmed = variant(result, 'weak_strength_v1')
    cuts = [f for f in trimmed['fills'] if f['kind'] == 'weak_strength']
    assert sum(f['qty'] for f in cuts) == expected
    assert not trimmed['breakeven'] and trimmed['activeStop'] == signal['stop']
    late = evaluate(p, campaign, bars, signal, quantity=quantity, weak_environment=True,
        weak_environment_at=OPEN+11*MIN)
    assert not [f for f in variant(late, 'weak_strength_v1')['fills'] if f['kind'] == 'weak_strength']


def test_protective_stop_precedes_challenger_and_untrusted_minute_stays_unscorable():
    p, campaign, bars, signal = setup()
    bars[14] = replace(bars[14], close=48., low=47.9)
    result = evaluate(p, campaign, bars, signal)
    assert variant(result, 'failed_break_v1')['firstExit']['kind'] == 'stop'
    broken = [replace(b, source='sampled') if b.ts == OPEN+12*MIN else b for b in bars]
    missing = evaluate(p, campaign, broken, signal)
    assert all(v['status'] == 'incomplete' and v['netUnderlyingPnl'] is None for v in missing['variants'])


def test_missing_costs_or_quantity_do_not_manufacture_net_option_profits():
    p, campaign, bars, signal = setup()
    result = evaluate_exit_variants(p, campaign, bars, [], signal=signal, quantity=4, as_of_ms=bars[-1].ts+MIN)
    assert all(v['netUnderlyingPnl'] is None and v['optionValuation'] is None for v in result['variants'])
    unknown = evaluate(p, campaign, bars, signal, quantity=None)
    assert unknown['status'] == 'quantity_unknown' and unknown['variants'] == []
    assert unknown['underlyingPath']['complete']


def test_equal_cash_shares_only_for_affordability_refusal_including_fees():
    p, campaign, bars, signal = setup()
    kwargs = {'signal': signal, 'as_of_ms': bars[-1].ts+MIN, 'cash_budget': 100,
        'costs': {'slippage_bps': 0, 'fee_per_unit': 0, 'fee_per_order': 1}, 'other_checks_passed': True}
    result = shares_vs_skip(p, campaign, bars, [], option_failures=['affordability'], **kwargs)
    assert result['status'] == 'evaluated' and result['shares']['quantity'] == 2
    assert result['shares']['investedCash'] == pytest.approx(98.84)
    assert result['shares']['idleCash'] == pytest.approx(1.16)
    assert result['skip']['netPnl'] == 0 and not result['placesOrders']
    assert shares_vs_skip(p, campaign, bars, [], option_failures=['affordability', 'spread'], **kwargs)['status'] == 'ineligible'
    assert shares_vs_skip(p, campaign, bars, [], option_failures=['market'], **kwargs)['status'] == 'ineligible'


def test_current_daily_close_comes_only_from_full_trusted_session():
    p, _, bars, signal = setup(end=390)
    campaign = ExitCampaign(profile='reviewed', source_refs=('fixture',), allocation_note='Test EMA1 close',
        rungs=(ExitRung(id='target1', kind='target', fraction=.25, target=55),
               ExitRung(id='ema1', kind='ema', fraction=.75, ema_period=1)))
    result = evaluate(p, campaign, bars, signal, quantity=1)
    assert result['dailyEvidence']['derivedSessions'] == ['2026-05-05']
    assert variant(result, 'baseline_v1')['dataComplete']
    table = {b.ts: b for b in bars}
    table[OPEN+100*MIN] = replace(table[OPEN+100*MIN], source='sampled')
    daily, evidence = _daily_history(p, table, [], OPEN+390*MIN)
    assert not daily and evidence['unavailableSessions'] == ['2026-05-05']
    daily, evidence = _daily_history(p, {b.ts: b for b in bars}, [], OPEN+390*MIN-1)
    assert not daily and not evidence['derivedSessions']


def test_daily_aggregation_respects_calendar_early_close():
    day = dt.date(2026, 11, 27)
    opens, closes = session_bounds(day.isoformat())
    p = plan(first_session=day, last_session=day, created_at=opens-MIN, baseline_as_of=opens-MIN)
    table = {t: Bar('HOOD', '1m', t, 49, 50, 48, 49, 10, source='exchange')
        for t in range(opens, closes, MIN)}
    history, evidence = _daily_history(p, table, [], closes)
    assert len(table) == 210
    assert history[0].volume == 2100 and history[0].closes_at == closes
    assert evidence['derivedSessions'] == [day.isoformat()]


def test_option_costs_are_separate_and_missing_option_fees_stay_unknown():
    p, campaign, bars, signal = setup()
    body = {'contract_symbol': 'HOOD260515C00050000', 'source': 'Synthetic explicit evidence',
        'quotes': [{'available_at': OPEN+10*MIN, 'source_at': OPEN+10*MIN, 'bid': .9, 'ask': 1},
                   {'available_at': OPEN+80*MIN, 'source_at': OPEN+80*MIN, 'bid': 1.1, 'ask': 1.2}]}
    result = evaluate(p, campaign, bars, signal, premium_input=body)
    assert variant(result, 'baseline_v1')['optionValuation']['totalPnl'] is None
    priced = evaluate(p, campaign, bars, signal, premium_input={**body, 'fee_per_contract': 1.04})
    valuation = variant(priced, 'baseline_v1')['optionValuation']
    assert valuation['totalPnl'] == pytest.approx(35.84)
    assert valuation['fees'] == pytest.approx(4.16)  # Entry fees only; no assumed future exit fee.


def test_short_campaign_target_probe_preserves_direction_and_share_study_refuses_shorts():
    p = plan(direction='short', invalidation=49.3, targets=(48.7, 46.),
        entry=EntryPolicy(timeframe_minutes=5, require_exchange_bars=True, min_target_r=.25),
        volume_baseline={0: 1000., 1: 1000.})
    bars = [Bar('HOOD', '1m', OPEN+i*MIN, 48.98, 49.1, 48.9, 49., 500, source='exchange') for i in range(5)]
    bars += [Bar('HOOD', '1m', OPEN+i*MIN, 49., 49.02, 48.6, 48.65, 500, source='exchange') for i in range(5, 10)]
    campaign = ExitCampaign.for_profile('june_2026', list(p.targets))
    result = compare_entry_variants(p, campaign, bars, as_of_ms=OPEN+10*MIN, quantity=2)
    assert result['baseline']['signal'] is None
    assert result['campaignAware']['signal']['direction'] == 'short'
    assert result['targetOnlyProbe']['signal']['stop'] == 49.1
    assert shares_vs_skip(p, campaign, bars, [], signal=result['campaignAware']['signal'], as_of_ms=OPEN+10*MIN,
        cash_budget=100, option_failures=['affordability'], other_checks_passed=True)['status'] == 'ineligible'


def funding_case(*, ask=1.5, bid=1.45, funding_changes=None):
    p, campaign, bars, signal = setup()
    funding = {'quantity': 4, 'cashCapUsd': 500, 'maxAskUsd': 5, 'maxSpreadPct': 20,
        'maxContracts': 10, 'displayedAskSize': 10, 'optionFeePerContractUsd': 1.04,
        'optionAsk': 1.2, **(funding_changes or {})}
    body = {'contract_symbol': 'HOOD260515C00050000', 'source': 'Synthetic prospective observations',
        'fee_per_contract': 1.04, 'quotes': [
            {'available_at': OPEN+10*MIN+5000, 'source_at': OPEN+10*MIN+5000, 'bid': 1.1, 'ask': 1.2},
            {'available_at': OPEN+11*MIN, 'source_at': OPEN+11*MIN, 'bid': bid, 'ask': ask},
            {'available_at': OPEN+80*MIN, 'source_at': OPEN+80*MIN, 'bid': 1.6, 'ask': 1.7}]}
    return evaluate(p, campaign, bars, signal, entry_after=OPEN+10*MIN+5000,
        quantity_basis='current_funding_estimate', premium_input=body, funding=funding)


def test_later_entry_quote_cannot_spend_more_than_captured_option_cash_cap():
    result = funding_case()
    for row in result['variants']:
        valuation = row['optionValuation']
        assert valuation['totalPnl'] is None and valuation['status'] == 'incomplete'
        assert valuation['fundingCheck']['entryDebitUsd'] == pytest.approx(604.16)
        assert not valuation['fundingCheck']['passed']
        assert row['fills'][0]['qty'] == 4  # No silent per-variant resizing.


@pytest.mark.parametrize('change', [{'maxAskUsd': 1.1}, {'maxSpreadPct': 1},
    {'maxContracts': 3}, {'displayedAskSize': 3}, {'quantity': 3}, {'cashCapUsd': None}])
def test_modeled_option_entry_retains_every_frozen_funding_bound(change):
    result = funding_case(ask=1.21, bid=1.16, funding_changes=change)
    valuation = variant(result, 'baseline_v1')['optionValuation']
    assert valuation['totalPnl'] is None and not valuation['fundingCheck']['passed']


def test_funded_entry_quote_can_be_valued_with_explicit_matching_costs():
    result = funding_case(ask=1.21, bid=1.16)
    valuation = variant(result, 'baseline_v1')['optionValuation']
    assert valuation['fundingCheck']['passed']
    assert valuation['fundingCheck']['entryDebitUsd'] == pytest.approx(488.16)
    assert valuation['totalPnl'] == pytest.approx((1.6-1.21)*400-4.16)
