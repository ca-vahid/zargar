"""Pure, frozen Cartel profitability comparisons. No engine, storage or orders.

Underlying-price diagnostics are not option returns. Integer exit comparisons
require an explicit quantity; net values require explicitly supplied costs.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math

from pydantic import BaseModel, ConfigDict, Field

from ...domain import Bar
from ...marketstructure.market_calendar import is_trading_day
from ...marketstructure.sessions import ET, session_bounds
from .data import DailyBar, completed_daily
from .data_quality import pack, trusted
from .entry import read_entry
from .exits import ExitCampaign, ExitState, allocation_preview, allocations, decide_exits, record_fill
from .plans import CartelPlan
from .premium_replay import PremiumReplayInput, value_campaign
from .replay import next_minute

VERSION = 'cartel-research-economics-1'
DEFINITIONS = (
    {'id': 'baseline_v1', 'label': 'Saved exit campaign', 'rule': 'Original campaign and protective stop.'},
    {'id': 'failed_break_v1', 'label': 'Confirmed failed break',
     'rule': 'Exit remaining units at the next expected minute open after a complete entry-timeframe candle closes back through the original trigger, before the first target trim fills.'},
    {'id': 'time_60m_v1', 'label': '60-minute holding cap',
     'rule': 'Exit remaining units after 60 completed regular-session minutes from entry; next expected minute open.'},
    {'id': 'weak_strength_v1', 'label': 'Weak-environment strength trim',
     'rule': 'Only with weak context known by entry: sell floor(original units / 2) once after a complete entry-timeframe close reaches +0.5 initial R. One unit cannot trim. This sale does not earn target breakeven.'},
)


class ResearchCosts(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, allow_inf_nan=False)
    slippage_bps: float = Field(default=2., ge=0, le=100)
    fee_per_unit: float | None = Field(default=None, ge=0, le=1000)
    fee_per_order: float | None = Field(default=None, ge=0, le=1000)

    @property
    def complete(self):
        return self.fee_per_unit is not None and self.fee_per_order is not None

    def fee(self, qty):
        return self.fee_per_unit*qty+self.fee_per_order if self.complete else None


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def compare_rankings(candidates: list[dict], *, execution_slots=5):
    if not isinstance(execution_slots, int) or isinstance(execution_slots, bool) or not 1 <= execution_slots <= 50:
        raise ValueError('execution slots must be 1–50')
    if len(candidates) > 10000:
        raise ValueError('rank comparison is bounded to 10,000 frozen discovery candidates')
    rows = []
    for candidate in candidates:
        identity = candidate.get('id') or candidate.get('analysisId')
        if not identity or not candidate.get('symbol'):
            raise ValueError('frozen candidate identity and symbol are required')
        ranking, leader, theme = (candidate.get(k) or {} for k in ('ranking', 'leaderEvidence', 'themeEvidence'))
        def number(value):
            return float(value) if _finite(value) else None
        strength = number(leader.get('directionalRelativeStrength'))
        if strength is None:
            strength = number(ranking.get('directionalRelativeStrength'))
        theme_value = number(theme.get('medianRelativeStrength'))
        theme_known = _finite(theme.get('strengthKnown')) and theme['strengthKnown'] >= 3 and theme_value is not None
        source_at=candidate.get('sourceAt')
        history=completed_daily([DailyBar.model_validate(b) for b in candidate.get('daily') or []],source_at) \
            if type(source_at) is int else []
        trigger=number(candidate.get('trigger'))
        distance=(trigger/history[-1].close-1)*100*(1 if candidate.get('direction')=='long' else -1) \
            if history and trigger is not None and candidate.get('direction') in ('long','short') else None
        rows.append({'id': identity, 'analysisId': candidate.get('analysisId'), 'symbol': candidate['symbol'],
            'structuralTargetR': number(ranking.get('structuralTargetR')), 'relativeStrength': strength, 'triggerDistancePct':distance,
            'dailyVolume': number(ranking.get('dailyVolume')), 'dollarVolume': number(leader.get('dailyDollarVolume')),
            'volumeVsPrior20': number(leader.get('volumeVsPrior20')), 'themeKnown': theme_known,
            'themeRelativeStrength': theme_value if theme_known else None})
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('duplicate frozen candidate identities')
    def desc(value):
        return -value if value is not None else math.inf
    baseline = sorted(rows, key=lambda r: (desc(r['structuralTargetR']), desc(r['relativeStrength']),
        desc(r['dailyVolume']), r['symbol'], r['id']))
    leaders = sorted(rows, key=lambda r: (not r['themeKnown'], desc(r['themeRelativeStrength']),
        desc(r['relativeStrength']), desc(r['volumeVsPrior20']), desc(r['dollarVolume']), r['symbol'], r['id']))
    near=sorted([r for r in rows if r['triggerDistancePct'] is not None and r['triggerDistancePct']>=0],key=lambda r:(
        r['triggerDistancePct'],
        desc(r['relativeStrength']),r['symbol'],r['id']))
    liquid=sorted([r for r in rows if r['dollarVolume'] is not None],key=lambda r:(desc(r['dollarVolume']),desc(r['relativeStrength']),r['symbol'],r['id']))
    base_ranks, leader_ranks = ({r['id']: i+1 for i, r in enumerate(order)} for order in (baseline, leaders))
    baseline_ids, leader_ids = ([r['id'] for r in order[:execution_slots]] for order in (baseline, leaders))
    return {'version': VERSION, 'policies': ['structural_r_v1', 'leader_first_v1'],
        'baselineIds': baseline_ids, 'leaderIds': leader_ids,
        'opportunityComparisons':{'version':'cartel-opportunity-ranking-1',
            'nearestUnbrokenIds':[r['id'] for r in near[:execution_slots]],
            'liquidFirstIds':[r['id'] for r in liquid[:execution_slots]],
            'note':'Research only; distance/liquidity ranking does not establish baseline coverage, contract eligibility or profit.'},
        'baselineOrderIds': [r['id'] for r in baseline], 'leaderOrderIds': [r['id'] for r in leaders],
        'overlapIds': [i for i in baseline_ids if i in leader_ids],
        'candidates': [{**r, 'baselineRank': base_ranks[r['id']], 'leaderRank': leader_ranks[r['id']],
            'baselineSelected': r['id'] in baseline_ids, 'leaderSelected': r['id'] in leader_ids} for r in rows],
        'inputSha256': _digest(candidates), 'placesOrders': False, 'automaticPermissionChanged': False,
        'note': 'Frozen diagnostic ranking. Theme evidence needs three observations; unknown evidence stays unknown. Ranking does not override market, entry, contract or capacity checks.'}


def target_diagnostic(plan: CartelPlan, campaign: ExitCampaign, *, entry_price, stop, quantity, evidence_at):
    sign = 1 if plan.direction == 'long' else -1
    if not all(_finite(v) and v > 0 for v in (entry_price, stop)) or (entry_price-stop)*sign <= 0:
        raise ValueError('target diagnostics require positive directional entry risk')
    if not isinstance(evidence_at, int) or evidence_at < plan.created_at:
        raise ValueError('target evidence cannot predate the frozen plan')
    if quantity is not None and (not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0):
        raise ValueError('quantity must be positive whole units or unknown')
    risk = (entry_price-stop)*sign
    original = list(plan.targets)
    nearest_r = (original[0]-entry_price)*sign/risk
    preview = allocation_preview(campaign, quantity) if quantity is not None else None
    first = None
    if preview:
        for rung, allocation in zip(campaign.rungs, preview['rungs']):
            if allocation['reachable']:
                first = {'id': rung.id, 'kind': rung.kind, 'quantity': allocation['quantity'],
                    'price': rung.target if rung.kind == 'target' else None}
                break
    target = first['price'] if first else None
    reward = (target-entry_price)*sign/risk if target is not None else None
    return {'version': 'cartel-target-diagnostic-1', 'evidenceAt': evidence_at, 'originalTargets': original,
        'targetEvidence': [{'price': price, 'importance': 'unknown',
            'reason': 'Saved level has no supplied pre-entry major/minor classification evidence.'} for price in original],
        'nearestTarget': {'price': original[0], 'rewardR': nearest_r,
            'passes': nearest_r > 0 and nearest_r >= plan.entry.min_target_r},
        'firstExecutableExit': first, 'allocation': preview['rungs'] if preview else [],
        'campaignTarget': {'policy': 'first_allocated_static_target_v1', 'price': target, 'rewardR': reward,
            'passes': reward > 0 and reward >= plan.entry.min_target_r if reward is not None else None,
            'reason': 'Static target of the first allocated executable rung; original nearer levels retained.' if target is not None
                else 'Quantity unknown or first executable exit depends on future EMA/ATR evidence; no static target permission inferred.'},
        'minimumRewardR': plan.entry.min_target_r, 'placesOrders': False, 'automaticPermissionChanged': False}


def _campaign_entry_plan(plan, campaign, quantity):
    if quantity is None:
        return None
    sizes = allocations(campaign, quantity)
    first_quantity = sizes[campaign.rungs[0].id]
    for rung in campaign.rungs:
        if not sizes[rung.id] or rung.kind == 'extension' and not first_quantity:
            continue
        if rung.kind != 'target':
            return None  # A dynamic exit cannot grant an unbounded entry target.
        if rung.target not in plan.targets:
            raise ValueError('campaign target must be an original frozen plan level')
        index = plan.targets.index(rung.target)
        # This copy exists only for the explicitly named research entry read.
        # Original levels and the exit campaign remain in the result/digest.
        return plan.model_copy(update={'targets': plan.targets[index:]})
    return None


def _target_only_probe(plan, tape, read):
    sign = 1 if plan.direction == 'long' else -1
    for item in read.get('trace', []):
        measurements = item.get('measurements') or {}
        if item.get('decision') != 'watch_only' or not measurements:
            continue
        at, price = item['at'], measurements['close']
        ratio = measurements.get('volumeRatio')
        if not _finite(ratio) or ratio < plan.entry.volume_multiple \
                or measurements['closeLocation'] < plan.entry.min_close_location \
                or (price-plan.trigger)*sign > abs(plan.trigger-plan.invalidation)*plan.entry.max_chase_r:
            continue
        opens, closes = session_bounds(dt.datetime.fromtimestamp((at-1)/1000, ET).date().isoformat())
        if at >= closes:
            continue
        start = opens if plan.entry.stop_mode == 'session_extreme' else at-plan.entry.timeframe_minutes*60_000
        needed = [tape.get(t) for t in range(start, at, 60_000)]
        if any(b is None or not trusted(b, simulation=plan.entry.allow_simulated_bars) for b in needed):
            continue
        stop = plan.invalidation if plan.entry.stop_mode == 'preplanned' else \
            min(b.low for b in needed) if sign == 1 else max(b.high for b in needed)
        risk = (price-stop)*sign
        if risk <= 0:
            continue
        if (plan.targets[0]-price)*sign > 0 and (plan.targets[0]-price)*sign/risk >= plan.entry.min_target_r:
            continue
        return {'status': 'target_only_probe', 'signal': {'id': f'{plan.id}:entry:{at}', 'at': at,
            'direction': plan.direction, 'referencePrice': price, 'stop': stop, 'risk': risk,
            'targets': list(plan.targets), 'volume': measurements['volume'], 'volumeRatio': ratio,
            'closeLocation': measurements['closeLocation'], 'stopMode': plan.entry.stop_mode},
            'placesOrders': False, 'eligibleEntry': False,
            'reason': 'Non-target confirmation checks passed; target veto remains. Quote research only.'}
    return {'status': 'none', 'signal': None, 'placesOrders': False, 'eligibleEntry': False}


def compare_entry_variants(plan, campaign, minutes, *, as_of_ms, quantity=None, signal_after=None):
    tape = _tape(plan, minutes, as_of_ms)
    baseline = read_entry(plan, list(tape.values()), as_of_ms, entry_after=signal_after)
    alternative = _campaign_entry_plan(plan, campaign, quantity)
    challenger = read_entry(alternative, list(tape.values()), as_of_ms, entry_after=signal_after) if alternative else \
        {'status': 'target_unknown', 'signal': None, 'trace': [],
         'reason': 'Quantity unknown or first executable exit has no static target; no entry inferred.'}
    return {'version': 'cartel-entry-target-comparison-1', 'placesOrders': False,
        'automaticPermissionChanged': False, 'originalTargets': list(plan.targets),
        'baseline': {'variant': 'baseline_v1', **baseline},
        'campaignAware': {'variant': 'campaign_static_target_v1', **challenger,
            'comparisonTarget': alternative.targets[0] if alternative else None},
        'targetOnlyProbe': _target_only_probe(plan, tape, baseline),
        'inputSha256': _digest({'plan': plan.model_dump(mode='json'), 'campaign': campaign.model_dump(mode='json'),
            'minutes': [pack(b) for b in tape.values()], 'quantity': quantity, 'asOfMs': as_of_ms, 'signalAfter': signal_after})}


ENTRY_STUDY_VERSION = 'cartel-entry-policy-diagnostics-v1'


def entry_study_plans(plan):
    return {
        'saved_entry_v1': plan,
        'gap_retest_v1': plan.model_copy(update={'entry': plan.entry.model_copy(update={'mode': 'retest', 'allow_gap_retest': True})}),
        'volume_1x_v1': plan.model_copy(update={'entry': plan.entry.model_copy(update={'volume_multiple': 1.0})}),
    }


def entry_policy_study(plan, minutes, *, as_of_ms, entry_after):
    """Same frozen pool/levels; stock-only diagnostics never confer permission."""
    tape = _tape(plan, minutes, as_of_ms)
    rows = []
    for name, variant in entry_study_plans(plan).items():
        read = read_entry(variant, list(tape.values()), as_of_ms, entry_after=entry_after)
        rows.append({'variant': name, 'policy': variant.entry.model_dump(mode='json'),
            'status': read['status'], 'signal': read.get('signal'), 'checks': read.get('trace', [])[-5:]})
    return {'version': ENTRY_STUDY_VERSION, 'rows': rows, 'placesOrders': False,
        'automaticPermissionChanged': False, 'entryAfter': entry_after,
        'note': 'Stock-only entry diagnostics without a market-permission override. No option fill or profitability claim.',
        'inputSha256': _digest({'plan': plan.model_dump(mode='json'), 'minutes': [pack(b) for b in tape.values()],
            'asOfMs': as_of_ms, 'entryAfter': entry_after, 'version': ENTRY_STUDY_VERSION})}


def _tape(plan, minutes, as_of_ms):
    tape = {}
    for bar in minutes:
        if bar.ts+60_000 > as_of_ms:
            continue
        if bar.symbol != plan.symbol or bar.tf != '1m' or bar.ts % 60_000:
            raise ValueError('symbol-matched aligned minute history is required')
        day = dt.datetime.fromtimestamp(bar.ts/1000, ET).date()
        if not is_trading_day(day):
            continue
        opens, closes = session_bounds(day.isoformat())
        if not opens <= bar.ts < closes:
            continue
        values = (bar.open, bar.high, bar.low, bar.close, bar.volume)
        if not all(_finite(v) for v in values) or min(values[:4]) <= 0 or bar.volume < 0 \
                or bar.high < max(values[:4]) or bar.low > min(values[:4]):
            raise ValueError('invalid research minute')
        if bar.ts in tape and tape[bar.ts] != bar:
            raise ValueError('conflicting research minutes')
        tape[bar.ts] = bar
    return dict(sorted(tape.items()))


def _freeze_entry(plan, tape, signal, as_of_ms, costs, quantity, quantity_basis, instrument,
                  entry_after, observed_at, signal_after, shadow_spec=None, verified_intervals=None):
    at = signal.get('at')
    if not isinstance(at, int) or at > as_of_ms:
        raise ValueError('a causal saved signal timestamp is required')
    if shadow_spec is None:
        actual = read_entry(plan, list(tape.values()), at, entry_after=signal_after).get('signal')
    else:
        from .shadow_entries import read_shadow_entry
        decision_at=observed_at if observed_at is not None else at
        if not at<=decision_at<=at+120000:
            raise ValueError('shadow decision was not observed within its acceptance window')
        actual=read_shadow_entry(shadow_spec,[b for t,b in tape.items() if t<at],decision_at,
            entry_after=signal_after if signal_after is not None else shadow_spec.frozen_at,
            verified_intervals=verified_intervals).get('signal')
    fields = ('id', 'at', 'direction', 'referencePrice', 'stop')
    if actual is None or any(actual.get(k) != signal.get(k) for k in fields):
        raise ValueError('signal does not match the frozen plan and causal minute evidence')
    if at >= session_bounds(plan.last_session.isoformat())[1]:
        return None, 'Entry window closed at confirmation'
    observations = [v for v in (entry_after, observed_at) if v is not None]
    if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in observations):
        raise ValueError('observed entry bounds must be integer timestamps')
    fill_at = ((max([at, *observations])+59_999)//60_000)*60_000
    if fill_at >= session_bounds(plan.last_session.isoformat())[1] or fill_at-at > 120_000:
        return None, 'Signal is stale or outside its entry window by the first observable fill minute'
    bar = tape.get(fill_at)
    if bar is None:
        return None, 'Next expected entry minute is not yet available'
    if not trusted(bar, simulation=plan.entry.allow_simulated_bars):
        return None, 'Next entry minute lacks trusted source evidence'
    sign = 1 if plan.direction == 'long' else -1
    price = bar.open*(1+sign*costs.slippage_bps/10000)
    stop = signal['stop']
    if (price-plan.trigger)*sign < 0 or (price-stop)*sign <= 0 \
            or (price-plan.trigger)*sign > abs(plan.trigger-plan.invalidation)*plan.entry.max_chase_r \
            or (plan.targets[0]-price)*sign <= 0 \
            or (plan.targets[0]-price)*sign/((price-stop)*sign) < plan.entry.min_target_r:
        return None, 'Next-open price no longer satisfies the saved entry geometry'
    return {'at': fill_at, 'signalAt': at, 'observedAt': max([at, *observations]),
        'price': price, 'unadjustedOpen': bar.open, 'stop': stop,
        'quantity': quantity, 'quantityBasis': quantity_basis, 'instrument': instrument,
        'slippageBps': costs.slippage_bps}, None


def _price_path(plan, tape, entry, as_of_ms, *, from_at=None, reference=None):
    start = entry['at'] if from_at is None else from_at
    rows = [b for t, b in tape.items() if t >= start]
    expected, complete = start, bool(rows)
    for bar in rows:
        if bar.ts != expected or not trusted(bar, simulation=plan.entry.allow_simulated_bars):
            complete = False
        expected = next_minute(bar.ts)
    if expected+60_000 <= as_of_ms:
        complete = False
    sign = 1 if plan.direction == 'long' else -1
    risk = abs(entry['price']-entry['stop'])
    ref = entry['price'] if reference is None else reference
    if not complete:
        return {'complete': False, 'reason': 'Missing or untrusted post-entry minutes; no complete path inferred.'}
    favorable = max((b.high-ref)*sign if sign == 1 else (b.low-ref)*sign for b in rows)
    adverse = min((b.low-ref)*sign if sign == 1 else (b.high-ref)*sign for b in rows)
    target_at = next((b.ts for b in rows if (b.high if sign == 1 else b.low)*sign >= plan.targets[0]*sign), None)
    stop_at = next((b.ts+60_000 for b in rows if (b.close-entry['stop'])*sign <= 0), None)
    return {'complete': True, 'basis': 'Underlying observations, not option returns or guaranteed fills.',
        'asOfMs': as_of_ms, 'close': rows[-1].close, 'closeR': (rows[-1].close-ref)*sign/risk,
        'maxFavorableR': favorable/risk, 'maxAdverseR': adverse/risk,
        'firstTargetTouchAt': target_at, 'initialStopCloseAt': stop_at}


def _daily_history(plan, tape, daily, as_of_ms):
    """Keep frozen pre-plan daily inputs; derive later closes only from full tape."""
    history = [b for b in daily if b.closes_at <= plan.created_at]
    if any(b.symbol != plan.symbol for b in history):
        raise ValueError('daily history must match the frozen plan symbol')
    derived, unavailable = [], []
    days = sorted({dt.datetime.fromtimestamp(t/1000, ET).date() for t in tape})
    for day in days:
        opens, closes = session_bounds(day.isoformat())
        if closes <= plan.created_at or closes > as_of_ms:
            continue
        bars = [tape.get(t) for t in range(opens, closes, 60_000)]
        if any(b is None or not trusted(b, simulation=plan.entry.allow_simulated_bars) for b in bars):
            unavailable.append(day.isoformat())
            continue
        history.append(DailyBar(symbol=plan.symbol, session=day, open=bars[0].open,
            high=max(b.high for b in bars), low=min(b.low for b in bars), close=bars[-1].close,
            volume=sum(b.volume for b in bars)))
        derived.append(day.isoformat())
    return sorted(history, key=lambda b: b.session), {'derivedSessions': derived, 'unavailableSessions': unavailable,
        'basis': 'Frozen pre-plan daily history plus complete trusted regular-session minute aggregation, including calendar early closes.'}


def _funding_check(valuation, premium_input, funding, quantity):
    fields = ('cashCapUsd', 'maxAskUsd', 'maxSpreadPct', 'maxContracts', 'displayedAskSize',
              'optionFeePerContractUsd', 'quantity')
    missing = [k for k in fields if not _finite(funding.get(k)) or funding[k] < 0]
    if missing:
        return {'passed': False, 'status': 'unknown', 'reasons': ['Missing/invalid frozen funding fields: '+', '.join(missing)]}
    first = next((f for f in valuation['fills'] if f['kind'] == 'entry'), None)
    if first is None:
        return {'passed': False, 'status': 'unknown', 'reasons': ['No eligible recorded quote at the modeled entry instant.']}
    quote = next((q for q in premium_input.quotes if q.available_at == first['quoteAvailableAt']
        and q.source_at == first['quoteSourceAt']), None)
    if quote is None:
        return {'passed': False, 'status': 'unknown', 'reasons': ['Modeled entry quote identity is unavailable.']}
    debit = quantity*(quote.ask*100+funding['optionFeePerContractUsd'])
    spread = (quote.ask-quote.bid)/((quote.ask+quote.bid)/2)*100
    reasons = []
    if debit > funding['cashCapUsd']+1e-8:
        reasons.append('Modeled entry premium and frozen fees exceed the captured cash cap.')
    if quote.ask > funding['maxAskUsd']+1e-10:
        reasons.append('Modeled entry ask exceeds the saved ask limit.')
    if spread > funding['maxSpreadPct']+1e-10:
        reasons.append('Modeled entry spread exceeds the saved limit.')
    if quantity > min(funding['quantity'], funding['maxContracts'], funding['displayedAskSize']):
        reasons.append('Modeled quantity exceeds captured funding, contract cap or displayed ask size.')
    if 'fee_per_contract' not in premium_input.model_fields_set or \
            abs(premium_input.fee_per_contract-funding['optionFeePerContractUsd']) > 1e-9:
        reasons.append('Option valuation fees do not match the explicit frozen funding assumption.')
    return {'passed': not reasons, 'status': 'passed' if not reasons else 'rejected', 'reasons': reasons,
        'entryDebitUsd': debit, 'cashCapUsd': funding['cashCapUsd'], 'entryAsk': quote.ask,
        'entrySpreadPct': spread, 'quantity': quantity,
        'note': 'Entry-time quote tested against frozen estimated funding; no reservation or broker fill is implied.'}


def _variant(plan, campaign, tape, daily, entry, as_of_ms, definition, costs, weak_known, premium_input, funding):
    quantity = entry['quantity']
    state = ExitState(position_id=f"research:{plan.id}:{definition['id']}", symbol=plan.symbol,
        direction=plan.direction, entry=entry['price'], stop=entry['stop'], initial_qty=quantity, remaining_qty=quantity)
    sign = 1 if plan.direction == 'long' else -1
    fills = [{'kind': 'entry', 'at': entry['at'], 'qty': quantity, 'price': entry['price']}]
    pending, warnings, custom_cuts = [], [], []
    expected, held_minutes, strength_done = entry['at'], 0, False
    gross, exit_fees, last_close, complete = 0., 0., entry['price'], True
    first_size = allocations(campaign, quantity)[campaign.rungs[0].id]
    option = None
    if premium_input is not None:
        from ...options.occ import parse
        option = parse(premium_input.contract_symbol)
    for ts, bar in tape.items():
        if ts < entry['at']:
            continue
        if ts != expected or not trusted(bar, simulation=plan.entry.allow_simulated_bars):
            complete = False
            warnings.append('Missing/untrusted execution minute; no fill or decision inferred across the gap.')
            break
        for index, decision in enumerate(pending):
            qty = min(decision['qty'], state.remaining_qty)
            if not qty:
                continue
            price = bar.open*(1-sign*costs.slippage_bps/10000)
            custom = decision['kind'] in ('failed_break', 'time_60m', 'weak_strength')
            state = record_fill(campaign, state, fill_id=f'{ts}:{index}',
                rung='manual' if custom else decision['kind'], qty=qty)
            fill = {'kind': decision['kind'], 'at': ts, 'qty': qty, 'price': price}
            fills.append(fill)
            if custom:
                custom_cuts.append(fill)
            gross += sign*(price-entry['price'])*qty
            if costs.complete:
                exit_fees += costs.fee(qty)
        pending = []
        if state.remaining_qty == 0:
            break
        last_close = bar.close
        held_minutes += 1
        end = ts+60_000
        day = dt.datetime.fromtimestamp(ts/1000, ET).date()
        daily_close = end == session_bounds(day.isoformat())[1]
        try:
            read = decide_exits(campaign, state, daily, as_of_ms=end, observed_price=bar.close,
                daily_close=daily_close, dte=option.dte(day) if option else None)
        except ValueError as exc:
            complete = False
            warnings.append(str(exc))
            break
        if read['warnings']:
            complete = False
            warnings.extend(read['warnings'])
            break
        protective = [d for d in read['decisions'] if d['rung'] in ('stop', 'expiry')]
        first_filled = first_size > 0 and state.sold.get(campaign.rungs[0].id, 0) >= first_size
        opens, _ = session_bounds(day.isoformat())
        step = plan.entry.timeframe_minutes*60_000
        bucket_start = end-step
        completed_bucket = (end-opens) % step == 0 and bucket_start >= entry['at'] \
            and all(t in tape and trusted(tape[t], simulation=plan.entry.allow_simulated_bars)
                    for t in range(bucket_start, end, 60_000))
        custom = None
        if not protective:
            if definition['id'] == 'failed_break_v1' and completed_bucket and not first_filled \
                    and (bar.close-plan.trigger)*sign < 0:
                custom = {'kind': 'failed_break', 'qty': state.remaining_qty}
            elif definition['id'] == 'time_60m_v1' and held_minutes >= 60:
                custom = {'kind': 'time_60m', 'qty': state.remaining_qty}
            elif definition['id'] == 'weak_strength_v1' and weak_known and not strength_done and completed_bucket \
                    and quantity >= 2 and (bar.close-entry['price'])*sign >= .5*abs(entry['price']-entry['stop']):
                custom = {'kind': 'weak_strength', 'qty': min(quantity//2, state.remaining_qty)}
                strength_done = True
        pending = [custom] if custom else [{'kind': d['rung'], 'qty': d['qty']} for d in read['decisions']]
        expected = next_minute(ts)
    if state.remaining_qty and expected+60_000 <= as_of_ms:
        complete = False
        warnings.append('Execution tape ends before the requested cutoff.')
    remaining = state.remaining_qty
    open_gross = sign*(last_close-entry['price'])*remaining
    entry_fee = costs.fee(quantity)
    fees = entry_fee+exit_fees if costs.complete else None
    realized_net = gross-exit_fees-entry_fee*(quantity-remaining)/quantity if costs.complete else None
    open_net = open_gross-entry_fee*remaining/quantity if costs.complete and complete else None
    if definition['id'] == 'weak_strength_v1' and not weak_known:
        warnings.append('Weak environment was not established by entry; challenger retains baseline decisions.')
    if definition['id'] == 'weak_strength_v1' and quantity == 1:
        warnings.append('One unit cannot make a partial strength trim; baseline retained.')
    if not costs.complete:
        warnings.append('Explicit per-unit and per-order fee assumptions are missing; net underlying P&L is unavailable.')
    premature = []
    for cut in custom_cuts:
        later = _price_path(plan, tape, entry, as_of_ms, from_at=cut['at'], reference=cut['price'])
        premature.append({'exitAt': cut['at'], 'quantity': cut['qty'], **later,
            'possiblePrematureCut': later.get('maxFavorableR', 0) > 0 if later['complete'] else None,
            'foregoneUnderlyingAtCutoff': (later['close']-cut['price'])*sign*cut['qty'] if later['complete'] else None,
            'note': 'Post-cut highs/closes describe opportunity, not a sale or guaranteed recoverable profit.'})
    valuation = None
    if premium_input is not None:
        valuation = value_campaign({'dataComplete': complete, 'quantity': quantity, 'fills': fills,
            'quantityBasis': {'kind': entry['quantityBasis'], 'instrument': entry['instrument']}},
            premium_input, symbol=plan.symbol, direction=plan.direction, as_of_ms=as_of_ms)
        if 'fee_per_contract' not in premium_input.model_fields_set:
            valuation = {**valuation, 'realizedPnl': None, 'openPnl': None, 'totalPnl': None,
                'returnOnDebitPct': None, 'fees': None,
                'warnings': [*valuation['warnings'], 'Explicit option-fee assumptions are missing; net option P&L is unavailable.']}
        if funding is not None:
            check = _funding_check(valuation, premium_input, funding, quantity)
            valuation['fundingCheck'] = check
            if not check['passed']:
                valuation.update(status='incomplete', realizedPnl=None, openPnl=None, totalPnl=None,
                    returnOnDebitPct=None, fees=None)
                valuation['warnings'].extend(check['reasons'])
    return {**definition, 'status': 'incomplete' if not complete else 'closed' if not remaining else 'open',
        'dataComplete': complete, 'firstExit': fills[1] if len(fills) > 1 else None,
        'fills': fills, 'pending': pending, 'remainingQty': remaining, 'fees': fees,
        'activeStop': state.stop, 'breakeven': state.breakeven,
        'grossUnderlyingPnl': gross+open_gross if complete else None,
        'netUnderlyingPnl': gross+open_gross-fees if complete and costs.complete else None,
        'realizedUnderlyingPnl': realized_net, 'openUnderlyingPnl': open_net,
        'grossRealizedUnderlyingPnl': gross, 'grossOpenUnderlyingPnl': open_gross if complete else None,
        'optionValuation': valuation, 'prematureCut': premature, 'warnings': list(dict.fromkeys(warnings))}


def evaluate_exit_variants(plan: CartelPlan, campaign: ExitCampaign, minutes: list[Bar], daily: list[DailyBar], *,
        signal, quantity, as_of_ms, weak_environment=False, weak_environment_at=None, entry_after=None,
        costs=None, premium_input=None, quantity_basis='explicit_hypothetical', instrument='underlying_proxy',
        observed_at=None, signal_after=None, entry_variant='baseline_v1', funding=None,
        shadow_spec=None, verified_intervals=None):
    if quantity is not None and (not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= 1_000_000):
        raise ValueError('explicit whole-unit quantity or unknown is required')
    if instrument not in ('underlying_proxy', 'shares'):
        raise ValueError('underlying path must be labeled underlying_proxy or shares')
    if funding is not None and not isinstance(funding, dict):
        raise ValueError('funding must be a frozen observation dictionary or absent')
    costs = costs if isinstance(costs, ResearchCosts) else ResearchCosts.model_validate(costs or {})
    if premium_input is not None and not isinstance(premium_input, PremiumReplayInput):
        premium_input = PremiumReplayInput.model_validate(premium_input)
    tape = _tape(plan, minutes, as_of_ms)
    if shadow_spec is not None:
        from .shadow_entries import ShadowEntrySpec
        shadow_spec=ShadowEntrySpec.model_validate(shadow_spec)
        if shadow_spec.symbol!=plan.symbol or plan.direction!='long' or tuple(plan.targets)!=tuple(shadow_spec.targets) \
                or plan.created_at!=shadow_spec.frozen_at or plan.first_session!=shadow_spec.session \
                or plan.last_session!=shadow_spec.session or entry_variant!='baseline_v1' \
                or plan.trigger!=signal.get('trigger') or plan.invalidation!=signal.get('stop'):
            raise ValueError('shadow valuation requires matching frozen symbol, direction and resistance')
    history, daily_evidence = _daily_history(plan, tape, daily, as_of_ms)
    if entry_variant not in ('baseline_v1', 'campaign_static_target_v1'):
        raise ValueError('unknown frozen entry comparison variant')
    read_plan = plan if entry_variant == 'baseline_v1' else _campaign_entry_plan(plan, campaign, quantity)
    if read_plan is None:
        entry, problem = None, 'Campaign-aware entry requires an allocated static target'
    else:
        entry, problem = _freeze_entry(read_plan, tape, signal, as_of_ms, costs, quantity, quantity_basis,
            instrument, entry_after, observed_at, signal_after,shadow_spec,verified_intervals)
    output = {'version': VERSION, 'placesOrders': False, 'automaticPermissionChanged': False,
        'status': 'entry_unavailable' if problem else 'quantity_unknown' if quantity is None else 'evaluated',
        'entry': entry, 'targetDiagnostic': None, 'variants': [], 'definitions': [dict(d) for d in DEFINITIONS],
        'dailyEvidence': daily_evidence,
        'warnings': [problem] if problem else [], 'costs': costs.model_dump(mode='json'),
        'funding': dict(funding) if funding is not None else None,
        'valuationBasis': 'Unlevered share scenario' if instrument == 'shares' else
            'Underlying price proxy with integer campaign allocations; dollar values are not option/account P&L.',
        'inputSha256': _digest({'plan': plan.model_dump(mode='json'), 'campaign': campaign.model_dump(mode='json'),
            'minutes': [pack(b) for b in tape.values()], 'daily': [b.model_dump(mode='json') for b in daily],
            'signal': signal, 'quantity': quantity, 'asOfMs': as_of_ms, 'entryAfter': entry_after,
            'observedAt': observed_at, 'signalAfter': signal_after, 'entryVariant': entry_variant,
            'weakEnvironment': weak_environment, 'weakEnvironmentAt': weak_environment_at,
            'costs': costs.model_dump(mode='json'), 'quantityBasis': quantity_basis, 'instrument': instrument,
            'funding': funding,
            'shadowSpec':shadow_spec.model_dump(mode='json') if shadow_spec else None,
            'verifiedIntervals':verified_intervals or {},
            'premiumInput': premium_input.model_dump(mode='json') if premium_input else None})}
    if entry is None:
        return output
    output['targetDiagnostic'] = target_diagnostic(plan, campaign, entry_price=entry['price'], stop=entry['stop'],
        quantity=quantity, evidence_at=entry['at'])
    output['underlyingPath'] = _price_path(plan, tape, entry, as_of_ms)
    if quantity is None:
        output['warnings'].append('Funded/explicit whole-unit quantity is unknown; no integer exit allocation or option return is invented.')
        return output
    weak_known = weak_environment is True and isinstance(weak_environment_at, int) \
        and 0 <= weak_environment_at <= entry['at']
    output['variants'] = [_variant(plan, campaign, tape, history, entry, as_of_ms, definition,
        costs, weak_known, premium_input, funding) for definition in DEFINITIONS]
    return output


def shares_vs_skip(plan, campaign, minutes, daily, *, signal, as_of_ms, cash_budget, option_failures,
        other_checks_passed, entry_after=None, costs=None, signal_after=None, observed_at=None):
    """Affordability-only ordinary-share research, never an execution fallback."""
    output = {'version': 'cartel-shares-versus-skip-1', 'placesOrders': False, 'automaticPermissionChanged': False,
        'status': 'ineligible', 'skip': {'cashBudget': cash_budget, 'netPnl': 0., 'investedCash': 0.},
        'shares': None, 'reason': ''}
    if not _finite(cash_budget) or cash_budget <= 0:
        raise ValueError('positive cash budget is required')
    if plan.direction != 'long' or other_checks_passed is not True or set(option_failures) != {'affordability'}:
        output['reason'] = 'Requires a valid long setup with an option refusal solely for affordability; other failures do not qualify.'
        return output
    costs = costs if isinstance(costs, ResearchCosts) else ResearchCosts.model_validate(costs or {})
    if not costs.complete:
        output.update(status='costs_unknown', reason='Explicit share commissions are needed to preserve the equal cash cap.')
        return output
    preliminary = evaluate_exit_variants(plan, campaign, minutes, daily, signal=signal, quantity=None,
        as_of_ms=as_of_ms, entry_after=entry_after, observed_at=observed_at, signal_after=signal_after,
        costs=costs, instrument='shares')
    if preliminary['entry'] is None:
        output['reason'] = preliminary['warnings'][0]
        return output
    price = preliminary['entry']['price']
    quantity = max(0, math.floor((cash_budget-costs.fee_per_order)/(price+costs.fee_per_unit)))
    if quantity < 1:
        output['reason'] = 'Equal cash cap cannot fund one ordinary share including entry fees.'
        return output
    study = evaluate_exit_variants(plan, campaign, minutes, daily, signal=signal, quantity=quantity,
        as_of_ms=as_of_ms, entry_after=entry_after, observed_at=observed_at, signal_after=signal_after,
        costs=costs, instrument='shares',
        quantity_basis='equal_cash_unlevered_shares')
    invested = quantity*price+costs.fee(quantity)
    output.update(status='evaluated', reason='Conditional unlevered share comparison; options were not repriced or replaced.',
        shares={'quantity': quantity, 'cashBudget': cash_budget, 'investedCash': invested,
            'idleCash': cash_budget-invested, 'leverage': 1, 'initialStopRisk': quantity*abs(price-signal['stop']),
            'study': study})
    return output
