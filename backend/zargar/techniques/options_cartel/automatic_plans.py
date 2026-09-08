"""Explicit automatic review policy for Cartel's workspace-scoped preparation workflow."""
from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, model_validator

from ...options.occ import parse
from .contracts import ContractSelectionInput
from .data import DailyBar, completed_daily
from .exits import ExitCampaign
from .plans import EntryPolicy
from .rules import ScreenProfile
from .service import PlanInput, WireModel
from .setups import SetupParameters


class PreparationPolicy(WireModel):
    enabled: bool = False
    workspace: Literal['practice', 'live'] = 'practice'
    allow_live: bool = False
    overnight_ack: bool = False
    portfolio_id: str | None = Field(default=None, max_length=64)
    profile: ScreenProfile = 'september_2026'
    scan_all: bool = True
    history_limit: int = Field(default=200, ge=1, le=10000)
    request_interval_seconds: float = Field(default=.25, ge=0, le=5)
    focus_count: int = Field(default=5, ge=1, le=20)
    horizon_sessions: int = Field(default=1, ge=1, le=20)
    budget: float = Field(default=500, gt=0, le=100000)
    risk_pct: float = Field(default=1, gt=0, le=5)
    max_contracts: int = Field(default=10, ge=1, le=1000)
    entry: EntryPolicy = Field(default_factory=lambda: EntryPolicy(allow_gap_retest=True))
    setups: SetupParameters = Field(default_factory=SetupParameters)
    exit_profile: Literal['september_2026', 'june_2026', 'may_2026'] = 'september_2026'
    # Engineering allocation, displayed as configuration; not attributed to Sean.
    september_fractions: tuple[float, float, float, float, float] = (.25, .25, .20, .20, .10)
    allow_fibonacci_targets: bool = True
    contract_policy: ContractSelectionInput = Field(default_factory=lambda: ContractSelectionInput(
        dte_min=21, dte_max=90, target_dte=45, target_abs_delta=.5, max_ask=5,
        max_spread_pct=20, min_open_interest=100, refresh_limit=6))

    @model_validator(mode='after')
    def valid_exit_policy(self):
        if self.enabled and self.workspace == 'live' and not (self.allow_live and self.overnight_ack):
            raise ValueError('Live preparation requires live execution and overnight-protection acknowledgements')
        ExitCampaign.for_profile(self.exit_profile, [1., 2.], september_fractions=self.september_fractions)
        return self


def automatic_review(research, analysis, policy: PreparationPolicy):
    history = completed_daily([DailyBar.model_validate(b) for b in research['history']], research['as_of_ms'])
    direction = research['direction']
    sign = 1 if direction == 'long' else -1
    choices = []
    for candidate in analysis['candidates']:
        if not candidate['contextPassed']:
            continue
        trigger, stop = candidate['trigger'], candidate['invalidation']
        if not math.isfinite(trigger) or not math.isfinite(stop) or (trigger-stop)*sign <= 0:
            continue
        targets = list(candidate['targets'])
        source = 'Confirmed historical price pivots from completed daily bars'
        if not targets and policy.allow_fibonacci_targets:
            prior = history[:-policy.setups.base_sessions][-60:]
            if len(prior) < 20:
                continue
            anchor = min(b.low for b in prior) if sign == 1 else max(b.high for b in prior)
            span = (trigger-anchor)*sign
            if span <= 0:
                continue
            targets = [trigger+sign*span*ratio for ratio in (.272, .618, 1.)]
            targets = [t for t in targets if t > 0]
            source = ('Engineering Fibonacci anchors: directional extreme of the 60 completed sessions preceding '
                      'the measured base, to its trigger; extensions 1.272/1.618/2.0. Not an author-specified anchor algorithm.')
        if not targets:
            continue
        try:
            campaign = ExitCampaign.for_profile(policy.exit_profile, targets,
                september_fractions=policy.september_fractions)
        except ValueError:
            continue
        ratio = abs(targets[0]-trigger)/abs(trigger-stop)
        specificity = candidate['setup'] != 'base'
        choices.append((specificity, ratio, candidate['setup'], candidate, targets, source, campaign))
    if not choices:
        return None
    _, ratio, _, candidate, targets, source, campaign = max(choices, key=lambda c: c[:3])
    note = (f'Automatic rule-based Cartel review: all market, listing, weekly/daily structure and relative-strength '
            f'checks passed. Selected {candidate["setup"]}; first target / structural risk {ratio:.2f}. '
            'Live entry and risk checks remain mandatory. Exit allocations and geometry thresholds are configured engineering choices.')
    return PlanInput(setup=candidate['setup'], horizon_sessions=policy.horizon_sessions,
        entry_policy=policy.entry, reviewed_targets=tuple(targets), review_note=note,
        target_source=source, exit_campaign=campaign)


async def planning_contract(engine, plan, policy: ContractSelectionInput):
    """Choose a draft contract from chain evidence; never treats it as a fresh execution quote."""
    if engine.options is None:
        raise ValueError('Options provider is unavailable')
    import datetime as dt
    provider = engine.options.provider()
    try:
        available = await provider.expirations(plan.symbol)
    except Exception as exc:  # noqa: BLE001 - missing provider data must remain pending, never eligible
        return {'selected': None, 'candidates': [], 'errors': [f'Expiry data unavailable: {type(exc).__name__}'],
                'pendingReason': 'Option provider unavailable; contract selection will retry during its activation window.',
                'planningOnly': True}
    expiries = [e for e in available
                if policy.dte_min <= (dt.date.fromisoformat(e)-plan.first_session).days <= policy.dte_max]
    expiries.sort(key=lambda e: (abs((dt.date.fromisoformat(e)-plan.first_session).days-policy.target_dte), e))
    candidates, errors = [], []
    rejected = {k: 0 for k in ('identity', 'quotes', 'delta', 'spread', 'open_interest', 'premium')}
    examined = checked = 0
    lowest_ask = None
    best_distance = None
    for expiry in expiries:
        distance = abs((dt.date.fromisoformat(expiry)-plan.first_session).days-policy.target_dte)
        if best_distance is not None and distance > best_distance:
            break  # Later expiries cannot improve the primary DTE ranking.
        checked += 1
        try:
            rows = await provider.chain(plan.symbol, expiry)
        except Exception as exc:  # noqa: BLE001 - preserve per-expiry provider failure
            errors.append(f'{expiry}: {type(exc).__name__}')
            continue
        for row in rows:
            examined += 1
            option = parse(row.get('symbol'))
            if option is None or option.underlying != plan.symbol or option.expiry.isoformat() != expiry or option.right != ('C' if plan.direction == 'long' else 'P'):
                rejected['identity'] += 1
                continue
            bid, ask, delta = row.get('bid'), row.get('ask'), (row.get('greeks') or {}).get('delta')
            oi = row.get('open_interest')
            numeric = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            if not numeric(bid) or not numeric(ask) or not 0 < bid <= ask:
                rejected['quotes'] += 1
                continue
            if not numeric(delta) or not policy.min_abs_delta <= abs(delta) <= 1 or delta*(1 if plan.direction == 'long' else -1) <= 0:
                rejected['delta'] += 1
                continue
            spread = (ask-bid)/((ask+bid)/2)*100
            if spread > policy.max_spread_pct:
                rejected['spread'] += 1
                continue
            if policy.min_open_interest and (not numeric(oi) or oi < policy.min_open_interest):
                rejected['open_interest'] += 1
                continue
            lowest_ask = ask if lowest_ask is None else min(lowest_ask, ask)
            if ask > policy.max_ask:
                rejected['premium'] += 1
                continue
            dte = (option.expiry-plan.first_session).days
            candidates.append({'symbol': option.symbol, 'expiry': expiry, 'delta': delta, 'bid': bid, 'ask': ask,
                'openInterest': oi, 'spreadPct': spread, 'dte': dte})
            best_distance = distance
    candidates.sort(key=lambda c: (abs(c['dte']-policy.target_dte), abs(abs(c['delta'])-policy.target_abs_delta), c['spreadPct'], c['symbol']))
    audit = {'expiriesInRange': len(expiries), 'expiriesChecked': checked, 'rowsExamined': examined,
             'eligible': len(candidates), 'rejections': rejected, 'effectiveMaxAsk': policy.max_ask,
             'maxDebitUsd': round(100*policy.max_ask, 2), 'lowestOtherwiseEligibleAsk': lowest_ask,
             'searchComplete': not errors and (bool(candidates) or checked == len(expiries)),
             'note': 'Rejection counts use the first failing filter for each inspected contract. Provider failures remain separate.'}
    reason = None if candidates else ('No expiries fall inside the configured DTE range.' if not expiries else
        f'No eligible contract in {checked} checked expiry dates. Maximum ask ${policy.max_ask:.2f} (${100*policy.max_ask:.2f} per contract before fees).')
    return {'selected': candidates[0] if candidates else None, 'candidates': candidates[:10], 'errors': errors,
            'pendingReason': reason, 'audit': audit, 'planningOnly': True,
            'note': 'Chain evidence selects the planned expression; fresh quotes/Greeks are required again before execution.'}
