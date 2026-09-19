import datetime as dt
from dataclasses import replace

import pytest

from zargar.domain import Bar
from zargar.marketstructure.sessions import session_bounds
from zargar.techniques.options_cartel.shadow_entries import ShadowEntrySpec, read_shadow_entry

DAY='2026-05-05'
OPEN,CLOSE=session_bounds(DAY)
MIN=60000


def spec(**changes):
    return ShadowEntrySpec(**{'id':'shadow','symbol':'TEST','session':dt.date.fromisoformat(DAY),
        'model':'undercut_reclaim','support':10,'support_kind':'prior_day_low',
        'source_at':OPEN-86400000,'frozen_at':OPEN-1000,'baseline_at':OPEN-2000,
        'targets':(11,12),'max_chase_r':2,'volume_baseline':{i:500 for i in range(78)},**changes})


def bar(i,opening=10.1,high=10.2,low=9.8,close=10.15,volume=200,source='exchange'):
    return Bar('TEST','1m',OPEN+i*MIN,opening,high,low,close,volume,source=source)


def test_reclaim_uses_closed_evidence_and_session_low_not_future_low():
    s=spec();tape=[bar(i) for i in range(5)]
    assert read_shadow_entry(s,tape,OPEN+4*MIN,entry_after=OPEN)['signal'] is None
    r=read_shadow_entry(s,tape+[bar(5,low=1)],OPEN+5*MIN,entry_after=OPEN)
    assert r['status']=='research_confirmation' and r['placesOrders'] is False
    assert r['signal']['stop']==9.8 and r['signal']['at']==OPEN+5*MIN
    assert r['signal']['referencePrice']==10.15


def test_pivot_is_not_its_own_breakout_and_following_candle_is_required():
    s=spec(model='pivot_30m',support_kind='ema8')
    tape=[bar(i,opening=9.99,high=10.1,low=9.98,close=10.05) for i in range(30)]
    r=read_shadow_entry(s,tape,OPEN+30*MIN,entry_after=OPEN)
    assert r['signal'] is None and r['trace'][-1]['status']=='pivot_observed'
    tape += [bar(i,opening=10.06,high=10.3,low=10,close=10.25) for i in range(30,35)]
    r=read_shadow_entry(s,tape,OPEN+35*MIN,entry_after=OPEN)
    assert r['signal']['trigger']==10.1 and r['signal']['stop']==9.98
    assert r['signal']['at']==OPEN+35*MIN


def test_gap_resets_sequence_and_untrusted_prices_cannot_create_reclaim():
    tape=[bar(i,close=9.95,opening=9.95) for i in range(5)]
    tape += [bar(i,opening=9.98,low=9.97,close=10.15) for i in range(5,10)]
    incomplete=tape[:2]+tape[3:]
    r=read_shadow_entry(spec(),incomplete,OPEN+10*MIN,entry_after=OPEN)
    assert r['signal'] is None
    assert 'session_stop_coverage' in r['trace'][-1]['blockers']
    sampled=[replace(b,source='sampled') for b in tape]
    assert read_shadow_entry(spec(),sampled,OPEN+10*MIN,entry_after=OPEN)['signal'] is None


def test_restart_does_not_replay_old_reclaim_and_duplicates_are_stable():
    tape=[bar(i) for i in range(5)]
    first=read_shadow_entry(spec(),tape,OPEN+5*MIN,entry_after=OPEN)
    assert read_shadow_entry(spec(),tape+tape,OPEN+5*MIN,entry_after=OPEN)==first
    assert read_shadow_entry(spec(),tape,OPEN+6*MIN,entry_after=OPEN+5*MIN)['signal'] is None
    with pytest.raises(ValueError,match='conflicting'):
        read_shadow_entry(spec(),tape+[replace(tape[0],volume=201)],OPEN+5*MIN,entry_after=OPEN)


def test_numeric_confirmations_and_near_resistance_remain_explicit_blockers():
    tape=[bar(i,volume=1) for i in range(5)]
    r=read_shadow_entry(spec(targets=(10.16,12)),tape,OPEN+5*MIN,entry_after=OPEN)
    assert r['signal'] is None
    assert set(r['trace'][-1]['blockers'])=={'volume_below_threshold','target_room'}
    assert r['trace'][-1]['measurements']['stop']==9.8


def test_pivot_low_break_invalidates_instead_of_selecting_later_winner():
    s=spec(model='pivot_30m',support_kind='ema8')
    tape=[bar(i,opening=9.99,high=10.1,low=9.98,close=10.05) for i in range(30)]
    tape += [bar(i,opening=10.06,high=10.3,low=9.8,close=10.25) for i in range(30,35)]
    r=read_shadow_entry(s,tape,OPEN+35*MIN,entry_after=OPEN)
    assert r['status']=='invalidated' and r['signal'] is None


def test_future_spec_and_bearish_mirror_are_not_silently_accepted():
    with pytest.raises(ValueError,match='before the open'): spec(frozen_at=OPEN)
    with pytest.raises(ValueError): spec(direction='short')
    with pytest.raises(ValueError,match='baseline'): spec(volume_baseline={78:100})


def test_reclaim_horizon_and_depth_are_enforced():
    low=[bar(i,opening=9.9,close=9.95) for i in range(5)]
    later=[bar(i,opening=9.99,low=9.98,close=10.15) for i in range(5,10)]
    r=read_shadow_entry(spec(reclaim_window_minutes=5),low+later,OPEN+10*MIN,entry_after=OPEN)
    assert r['status']=='expired_setup'
    assert read_shadow_entry(spec(),[bar(i,low=9) for i in range(5)],OPEN+5*MIN,entry_after=OPEN)['status']=='invalidated'


def test_no_entry_at_closing_bell_or_from_wrong_symbol():
    tape=[bar(i,opening=10.1,low=10.05,close=10.15) for i in range(390)]
    tape[-5:]=[bar(i) for i in range(385,390)]
    r=read_shadow_entry(spec(),tape,CLOSE,entry_after=OPEN)
    assert r['signal'] is None and r['trace'][-1]['status']=='entry_window_closed'
    with pytest.raises(ValueError,match='matched'):
        read_shadow_entry(spec(),[replace(bar(0),symbol='OTHER')],OPEN+MIN,entry_after=OPEN)
