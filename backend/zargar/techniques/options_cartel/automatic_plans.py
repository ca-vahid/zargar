"""Explicit automatic review policy for Cartel's workspace-scoped preparation workflow."""
from __future__ import annotations

import datetime as dt
import math
import re
from typing import Literal

from pydantic import Field, model_validator

from ...options.occ import parse
from .contracts import ContractSelectionInput, SelectionEconomics, contract_economics
from .data import DailyBar, completed_daily
from .cadence import VolumeExperiment
from .exits import ExitCampaign
from .plans import EntryPolicy
from .quality import target_room
from .rules import ScreenProfile
from .service import PlanInput, WireModel
from .setups import SetupParameters, _targets


class PreparationPolicy(WireModel):
    enabled: bool = False
    workspace: Literal['practice', 'live'] = 'practice'
    allow_live: bool = False
    overnight_ack: bool = False
    portfolio_id: str | None = Field(default=None, max_length=64)
    profile: ScreenProfile = 'september_2026'
    market_alignment: Literal['strict', 'moderate'] = 'strict'
    research_direction: Literal['long', 'short'] = 'long'
    industry_policy: Literal['context', 'strict'] = 'context'
    reviewed_etfs: tuple[str, ...] = ('DRAM',)
    comparison_symbols: tuple[str, ...] = ('MU', 'SNDK', 'NVDA', 'INTC', 'SMCI', 'AMD', 'ALAB', 'TEM', 'MRNA', 'DELL', 'HPE', 'NTAP', 'DRAM')
    comparison_source: str = Field(default='Historical reference: Sean weekly watchlist, 2026-09-07, https://x.com/SRxTrades/status/2097097587828707793 (comparison only; not a live signal)', max_length=2000)
    native_daily_batch: bool = False  # explicit provider/session switch, not a silent speed optimization
    require_exchange_history: bool = True
    coverage_policy: Literal['legacy', 'opening_and_broad', 'full_session'] = 'opening_and_broad'
    ignition_research: bool = True
    auto_resume: bool = True
    scan_all: bool = True
    history_concurrency: int = Field(default=6, ge=1, le=12)
    history_batch_size: int = Field(default=25, ge=1, le=50)
    history_limit: int = Field(default=200, ge=1, le=10000)
    request_interval_seconds: float = Field(default=.25, ge=0, le=5)
    baseline_readiness: Literal['full_session', 'covered_periods'] = 'covered_periods'
    shortlist_ranking: Literal['quality', 'volume'] = 'quality'
    min_target_distance_pct: float = Field(default=0.5, ge=0, le=10)
    min_entry_target_r: float = Field(default=0.25, ge=0, le=10)
    # P3 (2026-09-22): do not ARM a plan whose first target offers less than this many R from the trigger
    # at the planned stop. 0 = off (legacy). Nearby resistance is never skipped to raise the ratio; the
    # plan is simply not armed and the refusal is recorded.
    min_arm_target_r: float = Field(default=0, ge=0, le=10)
    focus_count: int = Field(default=5, ge=1, le=20)
    horizon_sessions: int = Field(default=1, ge=1, le=20)
    budget: float = Field(default=500, gt=0, le=100000)
    risk_pct: float = Field(default=10, gt=0, le=10)
    max_contracts: int = Field(default=10, ge=1, le=1000)
    entry: EntryPolicy = Field(default_factory=lambda: EntryPolicy(allow_gap_retest=True))
    setups: SetupParameters = Field(default_factory=SetupParameters)
    exit_profile: Literal['september_2026', 'june_2026', 'may_2026'] = 'september_2026'
    exit_allocation_policy: Literal['legacy', 'whole_contracts_v2'] = 'legacy'
    # Engineering allocation, displayed as configuration; not attributed to Sean.
    september_fractions: tuple[float, float, float, float, float] = (.25, .25, .20, .20, .10)
    allow_fibonacci_targets: bool = True
    contract_policy: ContractSelectionInput = Field(default_factory=lambda: ContractSelectionInput(
        dte_min=21, dte_max=90, target_dte=45, target_abs_delta=.5, max_ask=5,
        max_spread_pct=20, min_open_interest=100, refresh_limit=6))
    # F4 (2026-09-21, R2 2026-09-21 review): the explicit, versioned entry cadence. A saved policy
    # that predates the label keeps its behaviour: an unlabelled 15-minute entry IS the incumbent
    # ``breakout_15m_v1``; any other unlabelled timeframe (a saved Live or Practice 5m/30m entry) is
    # ``legacy_timeframe`` - the pre-existing read, no control, no pilot semantics, valid in every
    # workspace. Only the EXPLICIT ``breakout_5m_v1`` label opts into the Practice-only experiment.
    entry_cadence: Literal['breakout_15m_v1', 'breakout_5m_v1', 'legacy_timeframe'] = 'breakout_15m_v1'
    volume_experiment: VolumeExperiment = Field(default_factory=VolumeExperiment)

    @model_validator(mode='before')
    @classmethod
    def workspace_risk_default(cls, values):
        if isinstance(values, dict) and values.get('workspace') == 'live':
            values = dict(values)
            if 'coverage_policy' not in values and 'coveragePolicy' not in values:
                values['coverage_policy'] = 'full_session'
            if 'risk_pct' not in values and 'riskPct' not in values:
                values['risk_pct'] = 1
            if 'baseline_readiness' not in values and 'baselineReadiness' not in values:
                values['baseline_readiness'] = 'full_session'
        if isinstance(values, dict) and 'entry_cadence' not in values and 'entryCadence' not in values:
            entry = values.get('entry')
            minutes = (entry.get('timeframe_minutes', entry.get('timeframeMinutes', 15)) if isinstance(entry, dict)
                       else getattr(entry, 'timeframe_minutes', 15))
            values = dict(values)
            values['entry_cadence'] = 'breakout_15m_v1' if minutes == 15 else 'legacy_timeframe'
        return values

    @model_validator(mode='after')
    def cadence_consistency(self):
        expected = {'breakout_15m_v1': 15, 'breakout_5m_v1': 5}.get(self.entry_cadence)
        if expected is not None and self.entry.timeframe_minutes != expected:
            raise ValueError(f'{self.entry_cadence} requires entry.timeframe_minutes={expected}')
        if self.entry_cadence == 'breakout_5m_v1' and self.workspace != 'practice':
            raise ValueError('breakout_5m_v1 is a Practice-only entry-cadence experiment')
        if self.volume_experiment.version != 'off' and self.workspace != 'practice':
            raise ValueError('the volume grid experiment is Practice-only and replay-only')
        return self

    @model_validator(mode='after')
    def valid_exit_policy(self):
        if self.workspace == 'live' and not self.require_exchange_history:
            raise ValueError('New Live preparation requires verified exchange history')
        if self.profile == 'post_ignition_2026_09_11' and self.workspace != 'practice':
            raise ValueError('Post-ignition pilot is Practice-only; Live retains established profiles')
        if self.workspace == 'live' and self.exit_allocation_policy != 'legacy':
            raise ValueError('Whole-contract exit allocation v2 is a Practice-only experiment')

        if self.workspace == 'live' and self.market_alignment != 'strict':
            raise ValueError('Moderate market alignment is a Practice-only experiment; Live requires strict alignment')
        if self.enabled and self.workspace == 'live' and not (self.allow_live and self.overnight_ack):
            raise ValueError('Live preparation requires live execution and overnight-protection acknowledgements')
        for symbols in (self.reviewed_etfs, self.comparison_symbols):
            if len(symbols) > 50 or len(set(symbols)) != len(symbols) or any(not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,11}', v) for v in symbols):
                raise ValueError('Use up to 50 unique uppercase symbols')
        if self.comparison_symbols and not self.comparison_source.strip():
            raise ValueError('Comparison watchlist requires a dated source or rationale')
        ExitCampaign.for_profile(self.exit_profile, [1., 2.], september_fractions=self.september_fractions,
                                 allocation_policy=self.exit_allocation_policy)
        return self


def _anchor_history(history, candidate, base_sessions):
    """Anchor before this candidate's geometry, including saved older analyses."""
    evidence = candidate.get('evidence') or {}
    boundary = evidence.get('targetBaseStart')
    if boundary is not None:
        start = dt.date.fromisoformat(boundary)
    elif candidate['setup'] == 'post_ignition':
        event = evidence.get('eventSession')
        following = [b for b in history if event and b.session.isoformat() > event]
        if not following:
            return []
        start = following[0].session
    elif candidate['setup'] in ('inside_day', 'ma_pullback', 'breakout_retest'):
        offset = 2 if candidate['setup'] == 'inside_day' else 1
        if len(history) < offset:
            return []
        start = history[-offset].session
    elif evidence.get('baseStart'):
        start = dt.date.fromisoformat(evidence['baseStart'])
    elif len(history) >= base_sessions:
        start = history[-base_sessions].session
    else:
        return []
    return [b for b in history if b.session < start][-60:]


def automatic_review(research, analysis, policy: PreparationPolicy, *, research_only=False):
    history = completed_daily([DailyBar.model_validate(b) for b in research['history']], research['as_of_ms'])
    direction = research['direction']
    sign = 1 if direction == 'long' else -1
    choices = []
    for candidate in analysis['candidates']:
        if not candidate.get('researchContextPassed' if research_only else 'contextPassed', False):
            continue
        trigger, stop = candidate['trigger'], candidate['invalidation']
        if not math.isfinite(trigger) or not math.isfinite(stop) or (trigger-stop)*sign <= 0:
            continue
        targets = _targets(history, trigger, direction, policy.setups.touch_tolerance_pct,
                           existing=candidate['targets'])
        source = 'Confirmed historical price pivots from completed daily bars'
        if not targets and policy.allow_fibonacci_targets:
            prior = _anchor_history(history, candidate, policy.setups.base_sessions)
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
        if target_room(trigger, stop, targets[0])['firstTargetPct'] < policy.min_target_distance_pct:
            continue
        try:
            campaign = ExitCampaign.for_profile(policy.exit_profile, targets,
                september_fractions=policy.september_fractions, allocation_policy=policy.exit_allocation_policy)
        except ValueError:
            continue
        ratio = abs(targets[0]-trigger)/abs(trigger-stop)
        if policy.min_arm_target_r and ratio < policy.min_arm_target_r:
            continue
        specificity = candidate['setup'] != 'base'
        choices.append((ratio, specificity, candidate['setup'], candidate, targets, source, campaign))
    if not choices:
        return None
    ratio, _, _, candidate, targets, source, campaign = max(choices, key=lambda c: c[:3])
    note = (f'Automatic rule-based Cartel review: all market, listing, weekly/daily structure and relative-strength '
            f'checks passed. Selected {candidate["setup"]}; first target / structural risk {ratio:.2f}. '
            f'Minimum target distance {policy.min_target_distance_pct:g}%; minimum entry-to-target R {policy.min_entry_target_r:g}. Live entry and risk checks remain mandatory. Exit allocations and geometry thresholds are configured engineering choices.')
    if candidate['setup'] == 'post_ignition':
        note = 'Practice post-ignition pilot: verified event, quiet consolidation and prospective breakout. Geometry is experimental; closed-bar, data, contract and risk gates remain mandatory.'
    if research_only:
        note = 'Research candidate only: market alignment blocks arming. Rebuild with fresh aligned market evidence before execution.'
    entry_updates = {"min_target_r": policy.min_entry_target_r, "baseline_policy": policy.baseline_readiness, "require_exchange_bars": policy.require_exchange_history}
    cadence = policy.entry_cadence
    if cadence == 'breakout_5m_v1' and direction != 'long':
        # R3 (2026-09-21 review): the 5-minute pilot is scoped to LONG Practice plans. A bearish
        # executable plan keeps the incumbent 15-minute cadence and label; nothing else changes.
        entry_updates["timeframe_minutes"] = 15
        cadence = 'breakout_15m_v1'
    return PlanInput(setup=candidate['setup'], horizon_sessions=policy.horizon_sessions,
        entry_policy=policy.entry.model_copy(update=entry_updates), reviewed_targets=tuple(targets), review_note=note,
        target_source=source, exit_campaign=campaign, cadence_version=cadence)


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
    rejected_details = []
    rejected = {k: 0 for k in ('identity', 'quotes', 'delta', 'spread', 'open_interest', 'premium')}
    examined = checked = 0
    lowest_ask = None
    best_distance = None
    for expiry in expiries:
        distance = abs((dt.date.fromisoformat(expiry)-plan.first_session).days-policy.target_dte)
        if best_distance is not None and distance > best_distance and policy.ranking_version == 'legacy':
            break  # Later expiries cannot improve the legacy primary DTE ranking; cost ranking examines the whole range.
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
            failures = []
            valid_quotes = numeric(bid) and numeric(ask) and 0 < bid <= ask
            if not valid_quotes: failures.append('quotes')
            if not numeric(delta) or not policy.min_abs_delta <= abs(delta) <= 1 or delta*(1 if plan.direction == 'long' else -1) <= 0: failures.append('delta')
            if valid_quotes and (ask-bid)/((ask+bid)/2)*100 > policy.max_spread_pct: failures.append('spread')
            if policy.min_open_interest and (not numeric(oi) or oi < policy.min_open_interest): failures.append('open_interest')
            if numeric(ask) and ask > policy.max_ask: failures.append('premium')
            if failures:
                rejected_details.append({'symbol':option.symbol,'expiry':expiry,'ask':ask if numeric(ask) else None,'reasons':failures})
                rejected_details.sort(key=lambda c:(len(c['reasons']), abs((dt.date.fromisoformat(c['expiry'])-plan.first_session).days-policy.target_dte), abs((c['ask'] if c['ask'] is not None else 1e9)-policy.max_ask), c['symbol']))
                del rejected_details[30:]
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
    legacy_key = lambda c: (abs(c['dte']-policy.target_dte), abs(abs(c['delta'])-policy.target_abs_delta), c['spreadPct'], c['symbol'])
    candidates.sort(key=legacy_key)
    legacy_selected = candidates[0]['symbol'] if candidates else None
    ranking = 'legacy: distance to reviewed DTE, delta distance, spread, symbol'
    if policy.ranking_version in ('executable_cost_v1', 'executable_cost_v2'):
        # F3 on delayed chain rows: friction per contract only (no displayed size, no quantity);
        # the same tuple is re-applied on fresh quotes at the actual entry.
        fee = engine.settings.get('options.fee_per_contract', .99)
        regulatory = engine.settings.get('sim.reg_fee_per_contract', .05)
        economics = SelectionEconomics(entry_fee_per_contract_usd=fee+regulatory, exit_fee_per_contract_usd=fee+regulatory,
            basis='Delayed chain bid/ask with the Practice simulator fee schedule; sizes and quantity unknown pre-open')
        for c in candidates:
            c['economics'] = contract_economics(c['bid'], c['ask'], None, economics)
        cost = lambda c: (c['economics']['frictionPctOfDebit'], abs(c['dte']-policy.target_dte),
                          abs(abs(c['delta'])-policy.target_abs_delta), c['symbol'])
        if policy.ranking_version == 'executable_cost_v2':
            # Cost decides only inside the reviewed delta window; outside it keeps legacy order after every in-band row.
            from .contracts import in_delta_band
            candidates.sort(key=lambda c: (0, cost(c)) if in_delta_band(c['delta'], policy) else (1, legacy_key(c)))
            ranking = (f'executable_cost_v2 (planning basis): inside |delta| {policy.target_abs_delta-policy.cost_delta_band:.2f}-'
                       f'{policy.target_abs_delta+policy.cost_delta_band:.2f} by (crossing spread + round-trip fees) / entry debit on '
                       'delayed chain prices, then DTE and delta distance; outside the window legacy order')
        else:
            candidates.sort(key=cost)
            ranking = ('executable_cost_v1 (planning basis): (crossing spread + round-trip fees) / entry debit on delayed chain '
                       'prices, then distance to reviewed DTE, delta distance, symbol; displayed size unknown pre-open')
    audit = {'expiriesInRange': len(expiries), 'expiriesChecked': checked, 'rowsExamined': examined,
             'rankingVersion': policy.ranking_version, 'ranking': ranking, 'legacySelected': legacy_selected,
             'selectionChangedFromLegacy': bool(candidates) and candidates[0]['symbol'] != legacy_selected,
             'rejectedCandidates': rejected_details, 'eligible': len(candidates), 'rejections': rejected, 'effectiveMaxAsk': policy.max_ask,
             'maxDebitUsd': round(100*policy.max_ask, 2), 'lowestOtherwiseEligibleAsk': lowest_ask,
             'searchComplete': not errors and checked == len(expiries),
             'selectionComplete': not errors and (bool(candidates) or checked == len(expiries)),
             'note': 'Rejection counts use the first failing filter for each inspected contract. Provider failures remain separate.'}
    reason = None if candidates else ('No expiries fall inside the configured DTE range.' if not expiries else
        f'No eligible contract in {checked} checked expiry dates. Maximum ask ${policy.max_ask:.2f} (${100*policy.max_ask:.2f} per contract before fees).')
    return {'selected': candidates[0] if candidates else None, 'candidates': candidates[:10], 'errors': errors,
            'pendingReason': reason, 'audit': audit, 'planningOnly': True,
            'note': 'Chain evidence selects the planned expression; fresh quotes/Greeks are required again before execution.'}
