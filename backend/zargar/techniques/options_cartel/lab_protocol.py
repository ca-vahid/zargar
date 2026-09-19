"""Immutable Practice study contract and conservative review gate, never activation."""
from __future__ import annotations

import datetime as dt
import random
from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...marketstructure.market_calendar import is_trading_day
from ...marketstructure.sessions import session_bounds
from .shadow_entries import digest

VERSION='cartel-method-lab-protocol-v1'


class TrialProtocol(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True,allow_inf_nan=False)
    version: Literal['cartel-method-lab-protocol-v1']=VERSION
    portfolio_id: str = Field(min_length=1)
    frozen_at: int = Field(ge=0)
    first_session: dt.date
    policy_hash: str = Field(min_length=64,max_length=64)
    model_version: Literal['cartel-shadow-entries-v1']='cartel-shadow-entries-v1'
    exit_model: Literal['receipt_minute_close_v1']='receipt_minute_close_v1'
    control: Literal['breakout_5m_v1']='breakout_5m_v1'
    challenger: Literal['undercut_reclaim_5m_v1','pivot_30m_5m_v1']='undercut_reclaim_5m_v1'
    initial_capital: float = Field(gt=0)
    cash_cap: float = Field(gt=0)
    full_debit_risk_pct: float = Field(gt=0,le=100)
    min_sessions: int = Field(default=20,ge=20)
    min_closed_per_variant: int = Field(default=30,ge=30)
    min_regimes: int = Field(default=2,ge=2,le=3)
    max_drawdown_pct: float = Field(default=10,gt=0,le=100)
    max_single_session_profit_share: float = Field(default=.5,gt=0,le=1)
    option_fee_per_contract: float | None = Field(default=None,ge=0)
    share_fee_per_order: float | None = Field(default=None,ge=0)
    stress_cost_multiple: float = Field(default=2,ge=1)
    random_seed: int = 18092026

    @model_validator(mode='after')
    def frozen(self):
        if not is_trading_day(self.first_session) or self.frozen_at>=session_bounds(self.first_session.isoformat())[0]:
            raise ValueError('trial must be frozen before its first exchange session')
        if self.cash_cap>self.initial_capital:
            raise ValueError('trial cash cap exceeds starting capital')
        return self

    @property
    def fingerprint(self):
        return digest(self.model_dump(mode='json'))


class TrialObservation(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True,allow_inf_nan=False)
    protocol_hash: str
    session: dt.date
    closed_session: dt.date | None = None
    candidate_id: str
    variant: str
    regime: Literal['strong','mixed','weak','unknown']
    disposition: Literal['no_signal','not_executable','closed','open','data_missing','quote_missing']
    coverage_complete: bool
    net_pnl: float | None = None
    fees: float | None = Field(default=None,ge=0)
    spread_slippage_cost: float | None = Field(default=None,ge=0)
    cash_debit: float | None = Field(default=None,ge=0)
    peak_exposure: float | None = Field(default=None,ge=0)
    evidence_ids: tuple[str,...] = ()
    # Optional conservative path contribution for intraday/overnight marked drawdown.
    max_adverse_pnl: float | None = Field(default=None,le=0)

    @property
    def complete(self):
        if not self.coverage_complete or not self.evidence_ids:
            return False
        if self.disposition in ('no_signal','not_executable'):
            return self.net_pnl==0 and self.cash_debit==0 and self.peak_exposure==0
        return self.disposition=='closed' and self.closed_session is not None and self.closed_session>=self.session and all(v is not None for v in
            (self.net_pnl,self.fees,self.spread_slippage_cost,self.cash_debit,self.peak_exposure,self.max_adverse_pnl))


def trial_review(protocol: TrialProtocol, observations: list[TrialObservation]):
    """Session-cluster paired bootstrap. A green result only requests human review.

    Missing pairs, open/unmarked outcomes or cap violations prevent readiness.
    The drawdown bound includes adverse excursion conservatively, not only closes.
    Shared trade/session correlations are not turned into independent samples.
    """
    variants=(protocol.control,protocol.challenger)
    rows={};invalid=[]
    for r in observations:
        if r.protocol_hash!=protocol.fingerprint or r.variant not in variants or r.session<protocol.first_session:
            invalid.append('foreign_or_pretrial_observation');continue
        key=(r.session,r.candidate_id,r.variant)
        if key in rows:
            invalid.append('duplicate_observation');continue
        rows[key]=r
    population=sorted({(d,c) for d,c,_ in rows})
    paired=[];missing=0
    for day,candidate in population:
        pair=[rows.get((day,candidate,v)) for v in variants]
        if any(r is None or not r.complete for r in pair):
            missing+=1;continue
        if pair[0].regime!=pair[1].regime or pair[0].regime=='unknown':
            missing+=1;continue
        paired.append(pair)
    entry_days=sorted({pair[0].session for pair in paired})
    last=max((r.closed_session or r.session for pair in paired for r in pair),default=protocol.first_session)
    days=[];day=protocol.first_session
    while day<=last:
        if is_trading_day(day): days.append(day)
        day+=dt.timedelta(days=1)
    by_day={v:defaultdict(float) for v in variants};costs={v:0. for v in variants}
    by_entry={v:defaultdict(float) for v in variants}
    counts={v:0 for v in variants};risk_violations=[];adverse={v:defaultdict(float) for v in variants}
    exposure={v:defaultdict(float) for v in variants}
    for pair in paired:
        for r in pair:
            by_day[r.variant][r.closed_session or r.session]+=r.net_pnl
            by_entry[r.variant][r.session]+=r.net_pnl
            costs[r.variant]+=(r.fees or 0)+(r.spread_slippage_cost or 0)
            counts[r.variant]+=r.disposition=='closed'
            for day in days:
                if r.session<=day<=(r.closed_session or r.session):
                    adverse[r.variant][day]+=r.max_adverse_pnl or 0
                    exposure[r.variant][day]+=r.peak_exposure or 0
            if (r.cash_debit or 0)>min(protocol.cash_cap,protocol.initial_capital*protocol.full_debit_risk_pct/100):
                risk_violations.append(f'{r.session}:{r.candidate_id}:{r.variant}:debit_cap')
    metrics={}
    for v in variants:
        equity=peak=protocol.initial_capital;dd=0
        for day in days:
            dd=max(dd,(peak-(equity+adverse[v][day]))/peak*100)
            equity+=by_day[v][day];peak=max(peak,equity)
            dd=max(dd,(peak-equity)/peak*100)
            if exposure[v][day]>protocol.initial_capital:
                risk_violations.append(f'{day}:{v}:aggregate_exposure_upper_bound')
        positives=[max(0,by_day[v][day]) for day in days];gross_positive=sum(positives)
        metrics[v]={'netPnl':sum(by_day[v].values()),'closedTrades':counts[v],
            'netPerClosedTrade':sum(by_day[v].values())/counts[v] if counts[v] else None,
            'conservativeDrawdownPct':dd,'measuredCosts':costs[v],
            'stressNetPnl':sum(by_day[v].values())-(protocol.stress_cost_multiple-1)*costs[v],
            'maxSingleSessionProfitShare':max(positives)/gross_positive if gross_positive else None,
            'peakSessionExposureUpperBound':max(exposure[v].values(),default=0)}
    deltas=[by_entry[protocol.challenger][day]-by_entry[protocol.control][day] for day in entry_days]
    interval=None
    if len(deltas)>=2:
        rng=random.Random(protocol.random_seed)
        means=sorted(sum(rng.choice(deltas) for _ in deltas)/len(deltas) for _ in range(2000))
        interval={'low':means[49],'high':means[1949],'unit':'net dollars per paired session','method':'paired session bootstrap, 2000 draws'}
    regimes={p[0].regime for p in paired}
    failures=list(dict.fromkeys(invalid))
    if missing: failures.append('incomplete_or_unmatched_population')
    if len(entry_days)<protocol.min_sessions: failures.append('insufficient_sessions')
    if any(counts[v]<protocol.min_closed_per_variant for v in variants): failures.append('insufficient_closed_trades')
    if len(regimes)<protocol.min_regimes: failures.append('insufficient_regimes')
    if risk_violations: failures.append('risk_or_exposure_violation')
    if interval is None or interval['low']<=0: failures.append('incremental_benefit_unproven')
    challenger=metrics[protocol.challenger]
    if challenger['netPnl']<=0 or challenger['stressNetPnl']<=0 \
            or challenger['stressNetPnl']<=metrics[protocol.control]['stressNetPnl']:
        failures.append('cost_stress_benefit_unproven')
    if challenger['conservativeDrawdownPct']>protocol.max_drawdown_pct: failures.append('drawdown_limit')
    if (challenger['maxSingleSessionProfitShare'] or 0)>protocol.max_single_session_profit_share:
        failures.append('session_concentration')
    return {'version':VERSION,'protocolHash':protocol.fingerprint,'status':'review_ready' if not failures else 'not_ready',
        'failures':failures,'sessions':len(entry_days),'regimes':sorted(regimes),'population':len(population),
        'completePairs':len(paired),'incompletePairs':missing,'metrics':metrics,'incrementalNet95Interval':interval,
        'riskViolations':risk_violations,'placesOrders':False,'activationAllowed':False,
        'note':'Review readiness is not proof of future profitability or permission to trade. Exposure/drawdown use conservative sums; unknown and open outcomes prevent promotion.'}
