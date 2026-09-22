"""Causal funnel attribution for the daily review (2026-09-21 brief, F1). Pure; grants nothing.

The funnel stages are distinct: price touch -> closed-candle confirmation -> contract eligibility ->
submission -> fill. A prior data refusal no longer hides a measured refusal (NTNX 2026-09-21: the 10:30
volume refusal and the 13:00 data warning are separate facts), and a measured refusal never claims that
an earlier unknown window was empty. Recovered data cannot retroactively authorise an order.
"""
from __future__ import annotations

import math

from ...marketstructure.sessions import session_bounds
from .nonemission import minute_set

DATA_DECISIONS = {'missing_bucket', 'untrusted_confirmation', 'unsupported_volume_period', 'no_price_observations'}
STRATEGY_DECISIONS = {'watch_only', 'target_passed', 'invalidated', 'break_unconfirmed'}
CONTRACT_CHECKS = ('entry_contract_quote', 'entry_contract_delta', 'entry_contract_premium', 'entry_contract_spread',
                   'entry_contract_dte', 'fresh_quote', 'two_sided_quote', 'premium_limit', 'fresh_delta',
                   'delta_direction', 'delta_floor', 'affordable_quantity')


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def measured_failures(decision):
    """Every independently failing rule inside one watch_only decision, from its measurements."""
    m = decision.get('measurements') or {}
    out = []
    ratio, required = m.get('volumeRatio'), m.get('requiredVolumeMultiple')
    if _finite(ratio) and _finite(required) and ratio < required:
        out.append({'rule': 'volume', 'measured': ratio, 'required': required,
                    'text': f'volume {ratio:.3f}x of the same-time baseline; {required:g}x required'})
    elif m.get('baselineVolume') is None and 'baseline' in (decision.get('reason') or '').lower():
        out.append({'rule': 'volume', 'measured': None, 'required': required, 'text': 'no same-time volume baseline'})
    location, required = m.get('closeLocation'), m.get('requiredCloseLocation')
    if _finite(location) and _finite(required) and location < required:
        out.append({'rule': 'close_location', 'measured': location, 'required': required,
                    'text': f'close location {location:.3f}; {required:g} required'})
    target_r, required = m.get('firstTargetR'), m.get('requiredTargetR')
    if _finite(target_r) and _finite(required) and target_r < required:
        out.append({'rule': 'target_room', 'measured': target_r, 'required': required,
                    'text': f'first target {target_r:.3f}R from confirmation; {required:g}R required'})
    reason = (decision.get('reason') or '')
    if 'never-chase' in reason:
        out.append({'rule': 'chase', 'measured': m.get('close'), 'required': None, 'text': 'confirmation beyond the never-chase distance'})
    if 'already been reached' in reason:
        out.append({'rule': 'target_reached', 'measured': m.get('close'), 'required': None, 'text': 'first target already reached before entry'})
    if 'session extreme' in reason:
        out.append({'rule': 'stop_coverage', 'measured': None, 'required': None, 'text': 'session-extreme stop undeterminable with missing minutes'})
    if 'No positive entry-to-stop risk' in reason:
        out.append({'rule': 'stop_geometry', 'measured': None, 'required': None, 'text': 'no positive entry-to-stop risk'})
    if not out:
        out.append({'rule': 'unspecified', 'measured': None, 'required': None, 'text': reason or 'refused without measurements'})
    return out


def price_touch(plan, state, day, cutoff):
    """Intrabar touch versus closed-bucket crossing, from the arm's final tape (exchange bars only)."""
    opens, closes = session_bounds(day)
    end = min(closes, cutoff//60000*60000)
    bars = sorted((b for b in state.get('minutes', {}).values() if len(b) > 6 and b[6] == 'exchange' and opens <= b[0] < end),
                  key=lambda b: b[0])
    sign = 1 if plan.direction == 'long' else -1
    touched = [b for b in bars if (b[2]-plan.trigger)*sign >= 0] if sign == 1 else [b for b in bars if (b[3]-plan.trigger)*sign >= 0]
    step = plan.entry.timeframe_minutes*60000
    closes_beyond = []
    for start in range(opens, end, step):
        bucket = [b for b in bars if start <= b[0] < start+step]
        if bucket and start+step <= end and (bucket[-1][4]-plan.trigger)*sign > 0:
            closes_beyond.append(start+step)
    high = max((b[2] for b in bars), default=None)
    low = min((b[3] for b in bars), default=None)
    if not bars:
        return {'touched': None, 'wickOnly': None, 'firstTouchAt': None, 'closedBucketsBeyond': [],
                'explanation': 'No exchange price evidence for this session.'}
    if not touched:
        extreme = high if sign == 1 else low
        distance = (plan.trigger-extreme)*sign/plan.trigger*100 if extreme else None
        return {'touched': False, 'wickOnly': False, 'firstTouchAt': None, 'closedBucketsBeyond': [],
                'explanation': (f"No level touch: the session {'high' if sign == 1 else 'low'} {extreme:g} stayed "
                                f"{distance:.2f}% {'below' if sign == 1 else 'above'} the planned {plan.trigger:g} trigger.")}
    first = touched[0][0]
    if not closes_beyond:
        return {'touched': True, 'wickOnly': True, 'firstTouchAt': first, 'closedBucketsBeyond': [],
                'explanation': (f"Wick only: a 1-minute {'high' if sign == 1 else 'low'} crossed {plan.trigger:g} but no completed "
                                f"{plan.entry.timeframe_minutes}-minute candle closed beyond it, so no eligible confirmation existed.")}
    return {'touched': True, 'wickOnly': False, 'firstTouchAt': first, 'closedBucketsBeyond': closes_beyond,
            'explanation': (f"Closed {plan.entry.timeframe_minutes}-minute candle(s) ended beyond {plan.trigger:g}; "
                            "confirmation rules and execution checks decided the rest.")}


def selection_coverage(state, checks, cutoff):
    """not_attempted | incomplete | exhausted | eligible_expression_found, from records only."""
    signal = state.get('signal') or {}
    signalled = 0 < signal.get('at', 0) <= cutoff
    passed_contract = [c for c in checks if c.get('at', 0) <= cutoff and c.get('passed')]
    reselection = state.get('contractReselection') or {}
    if passed_contract or state.get('orderId'):
        return {'status': 'eligible_expression_found', 'basis': 'a preflight passed every contract and account check' if passed_contract else 'an entry order was recorded'}
    contract_failures = [c for c in checks if c.get('at', 0) <= cutoff and any(f.get('name') in CONTRACT_CHECKS for f in c.get('checks', []))]
    if reselection and reselection.get('startedAt', 0) <= cutoff:
        selection = reselection.get('selection') or {}
        if reselection.get('status') == 'selected':
            return {'status': 'eligible_expression_found', 'basis': 'bounded alternative search selected a contract within the saved limits',
                    'selectionVersion': reselection.get('selectionVersion', 'legacy')}
        complete = selection.get('searchComplete')
        return {'status': 'exhausted' if complete is True else 'incomplete',
                'basis': ('every refreshable candidate in the reviewed range was judged' if complete is True else
                          'the bounded alternative search did not cover every candidate; an unrefreshed contract may still have qualified'),
                'selectionVersion': reselection.get('selectionVersion', 'legacy'),
                'searchedExpiries': selection.get('searchedExpiries'), 'refreshedCandidates': selection.get('refreshedCandidates'),
                'structuralCandidates': selection.get('structuralCandidates'), 'incompleteReasons': selection.get('incompleteReasons')}
    if contract_failures:
        return {'status': 'incomplete', 'basis': 'only the saved contract was judged at entry; no alternative search record'}
    if not signalled:
        return {'status': 'not_attempted', 'basis': 'no confirmation signal, so no entry-time contract search took place'}
    return {'status': 'not_attempted', 'basis': 'a signal exists but no contract judgement was recorded by this cutoff'}


def actual_outcome(state, assets, cutoff):
    """no_order | submitted | unfilled | partially_filled | held | closed, from recorded orders and fills."""
    remaining = sum(a.get('remainingQty', 0) for a in assets)
    if assets and remaining > 0:
        requested = state.get('requestedQty') or (state.get('signal') or {}).get('quantity')
        filled = sum(a.get('filledQty', 0) or 0 for a in assets)
        return 'partially_filled' if _finite(requested) and 0 < filled < requested else 'held'
    if assets:
        return 'closed'
    if state.get('orderId') or state.get('attemptTag'):
        return 'unfilled' if state.get('phase') in ('closed', 'disarmed', 'cancelled') else 'submitted'
    return 'no_order'


def attribute(plan, state, day, cutoff, *, checks=(), assets=(), opportunity=None):
    opens, closes = session_bounds(day)
    trace = sorted((d for d in state.get('decisionHistory', []) if opens <= d.get('at', 0) <= cutoff), key=lambda d: (d.get('at', 0), d.get('decision', '')))
    touch = price_touch(plan, state, day, cutoff)
    blockers, incomplete = [], []
    for d in trace:
        kind = d.get('decision')
        window = {'end': d.get('at'), 'timeframeMinutes': plan.entry.timeframe_minutes}
        if kind in DATA_DECISIONS:
            known = d.get('known') or {}
            incomplete.append({'at': d.get('at'), 'decision': kind, 'rule': d.get('rule'), 'window': window,
                               'minutesMissing': known.get('minutesMissing'), 'minutesUntrusted': known.get('minutesUntrusted'),
                               'minutesPresent': known.get('minutesPresent'), 'partial': {k: known.get(k) for k in ('partialHigh', 'partialLow', 'partialVolume', 'lastKnownClose')},
                               'evidenceAvailableAtTime': False, 'inputHash': known.get('bucketInputHash'),
                               'note': 'This window was incomplete when judged; it may have hidden an opportunity. Later recovery cannot authorise a timely order.'})
        elif kind == 'watch_only':
            for f in measured_failures(d):
                blockers.append({'at': d.get('at'), 'decision': kind, 'rule': f['rule'], 'text': f['text'], 'measured': f['measured'],
                                 'required': f['required'], 'window': window, 'inputHash': d.get('bucketInputHash'),
                                 'measurements': d.get('measurements'), 'stage': 'confirmation'})
        elif kind in ('invalidated', 'target_passed', 'break_unconfirmed'):
            blockers.append({'at': d.get('at'), 'decision': kind, 'rule': d.get('rule'), 'text': d.get('reason'), 'measured': None,
                             'required': None, 'window': window, 'inputHash': d.get('bucketInputHash'), 'measurements': None, 'stage': 'confirmation'})
    for c in checks:
        if c.get('at', 0) <= cutoff and c.get('passed') is False:
            for f in c.get('checks', []):
                blockers.append({'at': c['at'], 'decision': 'execution_check', 'rule': f.get('name'), 'text': f.get('reason'), 'measured': None,
                                 'required': None, 'window': None, 'inputHash': None, 'measurements': c.get('expression'),
                                 'stage': 'contract' if f.get('name') in CONTRACT_CHECKS else 'execution'})
    blockers.sort(key=lambda b: (b['at'], b['stage'], b['rule'] or ''))
    first = blockers[0] if blockers else None
    others = []
    for b in blockers[1:]:
        same_window = first is not None and b['at'] == first['at'] and b['stage'] == first['stage']
        others.append({**b, 'sameWindowAsFirst': same_window,
                       'remainsIfFirstRemoved': True,   # every listed blocker is an independently measured refusal
                       'independentBecause': 'different rule in the same window' if same_window else 'later window or later stage'})
    earlier_unknown = [w for w in incomplete if first is not None and w['at'] < first['at']]
    for w in incomplete:
        w['beforeFirstKnownBlocker'] = first is not None and w['at'] < first['at']
    signal = state.get('signal') or {}
    signalled = 0 < signal.get('at', 0) <= cutoff or any(d.get('decision') == 'triggered' for d in trace)
    selection = selection_coverage(state, list(checks), cutoff)
    outcome = actual_outcome(state, list(assets), cutoff)
    decision_time = [{'at': w['at'], 'minutesPresent': w['minutesPresent'], 'minutesMissing': w['minutesMissing'],
                      'minutesUntrusted': w['minutesUntrusted']} for w in incomplete]
    final = None
    if opportunity:
        final = {k: opportunity.get(k) for k in ('nativeMinutes', 'expectedMinutes', 'unresolvedMinutes', 'verifiedIntervals')}
        final['note'] = 'Final coverage after recoveries; it does not prove the data was available at decision time.'
    economics = {'actualFees': sum(a.get('feesPaidToday', 0) for a in assets) if assets else 0.,
                 'actualNetRealized': sum(a.get('netRealized', 0) for a in assets) if assets else 0.,
                 'actualBasis': 'recorded executions and fees' if assets else 'no executions: actual P&L is zero, not unknown',
                 'modeled': None, 'modeledBasis': 'no modeled outcome is attached here; research models live in Validation'}
    if first is None and not signalled and not incomplete and touch.get('touched') is False:
        primary = 'no_level_touch'
    elif first is None and not signalled and touch.get('wickOnly'):
        primary = 'wick_only'
    elif first is None and incomplete and not signalled:
        primary = 'data_incomplete'
    elif first is not None:
        primary = first['stage']+'_refused'
    elif outcome != 'no_order':
        primary = 'executed'
    elif signalled:
        primary = 'signalled_no_record'
    else:
        primary = 'no_signal'
    funnel = {'priceTouch': touch.get('touched'), 'confirmation': signalled,
              'contractEligibility': selection['status'] == 'eligible_expression_found',
              'submission': outcome not in ('no_order',), 'fill': outcome in ('partially_filled', 'held', 'closed')}
    return {'actualOutcome': outcome, 'primaryKnownCause': primary, 'firstKnownBlocker': first,
            'otherIndependentBlockers': others, 'incompleteWindows': incomplete,
            'earlierUnknownWindows': len(earlier_unknown),
            'coverage': {'decisionTime': decision_time, 'final': final},
            'selectionCoverage': selection, 'priceTouch': touch, 'economics': economics, 'funnel': funnel,
            'placesOrders': False,
            'note': ('The primary cause is the first KNOWN blocker; incomplete windows listed before it remain unknown, '
                     'not cleared. Price touch, confirmation, contract eligibility, submission and fill are distinct stages.')}


def category_from(attribution, opportunity, kinds, related):
    """The review row's category, consistent with the attribution's primary known cause."""
    if related and any(a.get('remainingQty') for a in related):
        return 'open'
    if related:
        return 'closed'
    if 'invalidated' in kinds:
        return 'invalidated'
    primary = attribution['primaryKnownCause']
    if primary in ('confirmation_refused',):
        return 'strategy_rejected'
    if primary in ('contract_refused', 'execution_refused'):
        return 'execution_rejected'
    if primary == 'data_incomplete':
        return 'data_limited'
    if attribution['actualOutcome'] in ('submitted', 'unfilled'):
        return 'unfilled'
    if primary in ('signalled_no_record',):
        return 'signalled'
    return 'no_trigger'
