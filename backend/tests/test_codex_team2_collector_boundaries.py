"""Offline collector boundary probes: no DB/network/orders."""
from .test_team2_selection_study import rec, sel, ms, quote, DAY
from .test_codex_team2_data_eod import rig
from zargar.techniques.team2 import selection_study as ss, diagnostics as diag


def test_entry_rechecks_required_bid_in_real_candidate_output():
    T = ms(10, 12)
    raw = {'symbol': 'TEST', 'strike': 100, 'bid': None, 'ask': .6, 'eligible': True,
           'source': 'opra', 'quoteTs': T+1000, 'collectedTs': T+1100}
    selected = diag.candidate_rows([raw], {}, 'TEST', floor=.2, band_hi=.9, spot=100,
                                   quote_ts=T+1100)[0]
    assert selected['priceKnown']  # legacy diagnostic denominator accepts ask-only
    r = rec(T, T+1000, selected=selected)
    assert not r['entryQuote']['valid'], 'S1 requires positive bid AND ask at both ends'


def test_future_source_time_is_not_study_evidence():
    T = ms(10, 12); r = rec(T, T+1000)
    due = r['schedule'][1]['dueTs']
    out = ss.observe(r, 30, due+1000, quote(due+3000))
    assert not out['valid'], 'shared helper clock tolerance is weaker than frozen S1 no-future rule'


def test_removed_plan_cannot_hold_capacity_forever(monkeypatch):
    runner, ap = rig(); ap.plan_for = DAY
    monkeypatch.setattr(runner, 'rt', lambda k,d=None: 'collect' if k=='selection_study' else d)
    r = rec(ms(10,12), ms(10,12,3))
    runner._study_of(ap.run_id)['records'][r['opportunityId']] = r
    runner._armed.pop(ap.run_id)
    runner._study_tick(ms(12,0))
    assert runner._study_pending() == 0, 'retired/disarmed records consume capacity but are never ticked'
