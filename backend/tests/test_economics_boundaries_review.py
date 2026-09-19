import datetime as dt
from zargar.tools import tip_entry_horizons as eh
from zargar.signals.service import SignalService as SignalsService
from .test_tip_review_gate import _svc, _intake, CONTENT, OUT, DISCARD_MGMT

def test_morning_print_is_not_next_session_close():
    t0 = dt.datetime(2026, 9, 17, 10, 0, tzinfo=eh.ET)
    prints = [(dt.datetime(2026, 9, 18, 9, 31, tzinfo=eh.ET), 0.50)]
    assert eh.score(t0, 1.0, prints)['pnext'] is None

def test_close_print_before_decision_is_not_forward_outcome():
    t0 = dt.datetime(2026, 9, 17, 15, 55, tzinfo=eh.ET)
    prints = [(dt.datetime(2026, 9, 17, 15, 40, tzinfo=eh.ET), 0.50)]
    assert eh.score(t0, 1.0, prints)['pclose'] is None

async def test_absent_desk_components_keep_review_under_enforce():
    svc, _ = _svc('enforce')
    svc.engine.position_manager = None
    svc.engine.tip_runner = None
    assert await SignalsService._review_gate(svc, _intake(), CONTENT, OUT, DISCARD_MGMT, path='discarded') is True
