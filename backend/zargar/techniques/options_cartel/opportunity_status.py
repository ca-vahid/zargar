"""Separate price opportunity from data availability; never grants permission."""
from __future__ import annotations

from collections import Counter

from ...marketstructure.sessions import session_bounds
from .nonemission import minute_set

DATA_DECISIONS = {'missing_bucket', 'untrusted_confirmation', 'unsupported_volume_period', 'no_price_observations'}


def opportunity_status(plan, state, day, cutoff):
    opens, closes = session_bounds(day)
    end=min(closes,cutoff//60000*60000)
    bars=[b for b in state.get('minutes',{}).values()
          if len(b)>6 and b[6]=='exchange' and opens<=b[0]<end]
    proof_times=minute_set(state.get('verifiedIntervals',{}),plan.symbol,cutoff)
    covered={b[0] for b in bars}|{t for t in proof_times if opens<=t<end}
    expected=max(0,(end-opens)//60000)
    gaps=max(0,expected-len(covered))
    touched=any(b[2]>=plan.trigger if plan.direction=='long' else b[3]<=plan.trigger for b in bars)
    trace=[d for d in state.get('decisionHistory',[]) if opens<=d.get('at',0)<=cutoff]
    data=Counter(d['decision'] for d in trace if d.get('decision') in DATA_DECISIONS)
    if touched:
        status='level_reached'
        summary='Recorded exchange prices reached the planned level; entry still requires confirmation and execution checks.'
    elif bars:
        status='level_not_reached' if gaps==0 else 'level_not_observed'
        summary='Recorded exchange prices did not reach the planned level.'
        if gaps: summary+=' Coverage is incomplete; this cannot rule out a touch during a gap.'
    else:
        status='price_unknown';summary='No exchange price evidence is available for this session.'
    return {'status':status,'summary':summary,'trigger':plan.trigger,'direction':plan.direction,
        'high':max((b[2] for b in bars),default=None),'low':min((b[3] for b in bars),default=None),
        'nativeMinutes':len(bars),'expectedMinutes':expected,'unresolvedMinutes':gaps,
        'verifiedIntervals':len(covered-{b[0] for b in bars}),
        'historicalDataRefusals':dict(data),'placesOrders':False,
        'note':'Final coverage does not prove timely delivery. Price touches are not valid entries or missed profits.'}
