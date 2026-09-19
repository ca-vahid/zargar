"""Causal long-side entry experiments. No production plan, order or engine API.

The author's mirrored entry sequence is provisional; all numerical confirmation,
support-zone, depth and expiry choices are explicitly engineering parameters.
These signals have no execution authority and cannot be CartelPlan instances.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...domain import Bar
from ...marketstructure.market_calendar import is_trading_day
from ...marketstructure.sessions import session_bounds
from .nonemission import minute_set

VERSION = 'cartel-shadow-entries-v1'
MINUTE = 60_000


class ShadowEntrySpec(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, allow_inf_nan=False)
    version: Literal['cartel-shadow-entries-v1'] = VERSION
    id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    session: dt.date
    model: Literal['undercut_reclaim', 'pivot_30m']
    direction: Literal['long'] = 'long'
    support: float = Field(gt=0)
    support_kind: Literal['prior_day_low', 'ema8', 'ema21', 'ema50', 'reviewed_pivot']
    source_at: int = Field(ge=0)
    frozen_at: int = Field(ge=0)
    targets: tuple[float, ...] = Field(min_length=1)
    confirmation_minutes: Literal[5, 15] = 5
    volume_baseline: dict[int, float] = Field(default_factory=dict)
    baseline_at: int = Field(ge=0)
    volume_multiple: float = Field(default=1.5, gt=0, le=10)
    min_close_location: float = Field(default=.7, ge=0, le=1)
    min_target_r: float = Field(default=.25, ge=0, le=10)
    max_chase_r: float = Field(default=.5,ge=0,le=10)
    support_tolerance_pct: float = Field(default=.25, ge=0, le=5)
    max_undercut_pct: float = Field(default=3., gt=0, le=20)
    reclaim_window_minutes: int = Field(default=60, ge=5, le=390)
    source_status: Literal['mirrored_unverified', 'verified_author'] = 'mirrored_unverified'
    interpretation: Literal['closed_bar_engineering_v1'] = 'closed_bar_engineering_v1'

    @model_validator(mode='after')
    def causal_spec(self):
        if not is_trading_day(self.session):
            raise ValueError('shadow entries require an exchange session')
        opens,_=session_bounds(self.session.isoformat())
        if not self.source_at<=self.frozen_at<opens or self.baseline_at>self.frozen_at:
            raise ValueError('support, targets and baseline must be frozen before the open')
        if any(not math.isfinite(v) or v<=self.support for v in self.targets) or tuple(sorted(set(self.targets)))!=self.targets:
            raise ValueError('preserve ordered resistance above support')
        if any(k<0 or k>=390//self.confirmation_minutes or not math.isfinite(v) or v<=0
               for k,v in self.volume_baseline.items()):
            raise ValueError('baseline slots must match the confirmation timeframe')
        return self


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _tape(spec, bars, now):
    opens,closes=session_bounds(spec.session.isoformat()); tape={}
    for bar in bars:
        if not opens<=bar.ts<closes or bar.ts+MINUTE>now:
            continue
        if bar.symbol!=spec.symbol or bar.tf!='1m' or bar.ts%MINUTE:
            raise ValueError('shadow input requires matched, aligned minute bars')
        values=(bar.open,bar.high,bar.low,bar.close,bar.volume)
        if not all(math.isfinite(v) for v in values) or min(values[:4])<=0 or bar.volume<0 \
                or bar.high<max(values[:4]) or bar.low>min(values[:4]):
            raise ValueError('invalid shadow candle')
        if bar.ts in tape and tape[bar.ts]!=bar:
            raise ValueError('conflicting shadow minute values')
        tape[bar.ts]=bar
    return tape


def _bucket(tape, verified, start, end):
    expected=range(start,end,MINUTE)
    if any(t not in verified and (t not in tape or tape[t].source!='exchange') for t in expected):
        return None
    values=[tape[t] for t in expected if t in tape and tape[t].source=='exchange']
    if not values: return None  # positive non-emission evidence does not manufacture a candle
    return {'start':start,'end':end,'open':values[0].open,'high':max(b.high for b in values),
            'low':min(b.low for b in values),'close':values[-1].close,'volume':sum(b.volume for b in values)}


def read_shadow_entry(spec: ShadowEntrySpec, bars: list[Bar], now: int, *, entry_after: int,
                      verified_intervals=None):
    """Recompute using only available evidence. At most one signal per spec/session.

    Gaps reset setup state. Stop is the session low known at confirmation, not a
    future daily low. Restarts supply a new entry_after; no prior setup is replayed.
    Market eligibility is an independently captured gate, not inferred here.
    """
    if spec.version!=VERSION: raise ValueError('unsupported frozen shadow entry version')
    opens,closes=session_bounds(spec.session.isoformat())
    tape=_tape(spec,bars,now)
    verified=minute_set(verified_intervals,spec.symbol,now)
    boundary=min(closes,now)
    trace=[];anchor=None;pivot=None;previous=None;signal=None
    fingerprint=digest({'version':VERSION,'spec':spec.model_dump(mode='json'),
        'bars':[[b.ts,b.open,b.high,b.low,b.close,b.volume,b.source] for _,b in sorted(tape.items())],
        'proofs':verified_intervals or {},'asOf':now,'entryAfter':entry_after})
    def event(at,status,**values): trace.append({'at':at,'status':status,**values})
    def result(status):
        return {'version':VERSION,'specId':spec.id,'model':spec.model,'status':status,'signal':signal,
                'trace':trace,'inputSha256':fingerprint,'researchOnly':True,'placesOrders':False,
                'sourceStatus':spec.source_status,'interpretation':spec.interpretation}
    if now<opens: return result('before_session')
    after=max(opens,spec.frozen_at,entry_after)
    step=spec.confirmation_minutes*MINUTE
    for start in range(opens,boundary,step):
        end=start+step
        if end>boundary: break
        candle=_bucket(tape,verified,start,end)
        if candle is None:
            event(end,'data_gap');anchor=pivot=previous=None
            continue
        before=previous if previous is not None else candle['open']
        previous=candle['close']
        if spec.model=='undercut_reclaim' and (spec.support-candle['low'])/spec.support*100>spec.max_undercut_pct:
            event(end,'undercut_too_deep');return result('invalidated')
        if start<after:
            anchor=pivot=None
            continue
        ready=False;level=spec.support
        if spec.model=='undercut_reclaim':
            if candle['low']<spec.support:
                if anchor is None:
                    anchor={'at':start,'low':candle['low']}
                    event(end,'undercut_observed',support=spec.support)
            if anchor and end-anchor['at']>spec.reclaim_window_minutes*MINUTE:
                event(end,'reclaim_expired');return result('expired_setup')
            # A low below support and a later close above prove ordering within
            # the completed candle, without using a future candle or tick path.
            ready=anchor is not None and candle['close']>spec.support and (before<=spec.support or candle['low']<spec.support)
        else:
            if pivot and candle['low']<pivot['low']:
                event(end,'pivot_failed',pivotAt=pivot['end']);return result('invalidated')
            if pivot:
                level=pivot['high']
                ready=start>=pivot['end'] and before<=level<candle['close']
            elif (end-opens)%(30*MINUTE)==0 and end-30*MINUTE>=after:
                candidate=_bucket(tape,verified,end-30*MINUTE,end)
                tolerance=spec.support*spec.support_tolerance_pct/100
                if candidate and candidate['close']>candidate['open'] and candidate['close']>spec.support \
                        and spec.support-tolerance<=candidate['low']<=spec.support+tolerance \
                        and candidate['high']>=spec.support:
                    pivot=candidate
                    event(end,'pivot_observed',pivotHigh=pivot['high'],pivotLow=pivot['low'])
                continue  # the pivot candle cannot confirm its own future break
        if not ready: continue
        if end>=closes:
            event(end,'entry_window_closed');continue
        baseline=spec.volume_baseline.get((start-opens)//step)
        location=(candle['close']-candle['low'])/(candle['high']-candle['low']) if candle['high']>candle['low'] else 0
        session=_bucket(tape,verified,opens,end)
        stop=session['low'] if session else None
        risk=candle['close']-stop if stop is not None else None
        target_r=(spec.targets[0]-candle['close'])/risk if risk and risk>0 else None
        blockers=[]
        if baseline is None: blockers.append('baseline_unavailable')
        elif candle['volume']<baseline*spec.volume_multiple: blockers.append('volume_below_threshold')
        if location<spec.min_close_location: blockers.append('close_quality')
        if session is None: blockers.append('session_stop_coverage')
        elif not risk or risk<=0: blockers.append('nonpositive_risk')
        if stop is not None and candle['close']-level>abs(level-stop)*spec.max_chase_r:
            blockers.append('chase_distance')
        if target_r is not None and target_r<spec.min_target_r: blockers.append('target_room')
        measures={'referencePrice':candle['close'],'trigger':level,'stop':stop,'targetR':target_r,
                  'volumeRatio':candle['volume']/baseline if baseline else None,'closeLocation':location}
        if blockers:
            event(end,'confirmation_refused',blockers=blockers,measurements=measures)
            continue
        signal={'id':f'{spec.id}:{VERSION}:{end}','at':end,'direction':'long','risk':risk,
                'targets':list(spec.targets),'volume':candle['volume'],**measures,
                'researchOnly':True,'placesOrders':False}
        event(end,'research_confirmation',measurements=measures)
        return result('research_confirmation')
    return result('session_closed' if now>=closes else 'waiting')
