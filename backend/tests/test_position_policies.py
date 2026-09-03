"""Phase 2b — the pure policy engine (execution/policies.py). Every exit-policy
kind the techniques research asked for, evaluated deterministically."""
from __future__ import annotations

from zargar.domain import Bar
from zargar.execution.policies import Decision, PolicyState, PositionView, apply_moves, evaluate, validate_policy


def bar(ts: int, o: float, h: float, l: float, c: float, v: int = 1000) -> Bar:
    return Bar(symbol="X", tf="5m", ts=ts, open=o, high=h, low=l, close=c, volume=v)


def view(b: Bar, *, direction="long", entry=100.0, risk=1.0, **kw) -> PositionView:
    return PositionView(direction=direction, entry=entry, risk=risk, bar=b, bars=[b], **kw)


def test_stop_on_close_and_direction():
    pol = {"stop": {"kind": "fixed", "price": 99.0}}
    d, _ = evaluate(pol, PolicyState(), view(bar(1, 100, 100.5, 98.5, 99.4)))
    assert d == []                                                   # wick through, close held
    d, _ = evaluate(pol, PolicyState(), view(bar(2, 100, 100.5, 98.5, 98.9)))
    assert d and d[0].kind == "stop" and d[0].fraction == 1.0
    pol_s = {"stop": {"kind": "fixed", "price": 101.0}}
    d, _ = evaluate(pol_s, PolicyState(), view(bar(3, 100, 101.4, 99.8, 101.2), direction="short"))
    assert d and d[0].kind == "stop"


def test_no_stop_requires_declared_guard():
    assert validate_policy({"stop": {"kind": "none"}})               # rejected
    assert validate_policy({"stop": {"kind": "none", "guard": "sized 1% + daily loss halt"}}) == []


def test_ladder_trims_fractions_of_remaining():
    pol = {"ladder": {"targets": [101.0, 102.0], "fractions": [0.5, 0.5]}}
    st = PolicyState()
    d, m = evaluate(pol, st, view(bar(1, 100, 101.2, 99.9, 101.1)))
    assert d[0].kind == "trim" and abs(d[0].fraction - 0.5) < 1e-9   # 50% of remaining
    st = apply_moves(st, view(bar(1, 100, 101.2, 99.9, 101.1)), d, m)
    assert st.trims_done == 1
    d, _ = evaluate(pol, st, view(bar(2, 101, 102.3, 100.9, 102.1)))
    assert d[0].kind == "trim" and abs(d[0].fraction - 1.0) < 1e-9   # the remaining half = all that's left


def test_time_stop_counts_trading_sessions():
    pol = {"time_stop_sessions": 3}
    d, _ = evaluate(pol, PolicyState(), view(bar(1, 100, 100.5, 99.5, 100.2), sessions_held=2))
    assert d == []
    d, _ = evaluate(pol, PolicyState(), view(bar(2, 100, 100.5, 99.5, 100.2), sessions_held=3))
    assert d and d[0].kind == "time"


def test_dte_close_respects_platform_floor():
    pol = {"dte_close": 0}                                           # a technique trying to hold to expiry
    d, _ = evaluate(pol, PolicyState(), view(bar(1, 100, 101, 99, 100.5), dte_min=1, min_dte_floor=1))
    assert d and d[0].kind == "dte"                                  # the floor clamps it up
    d, _ = evaluate({"dte_close": 7}, PolicyState(), view(bar(2, 100, 101, 99, 100.5), dte_min=8, min_dte_floor=1))
    assert d == []


def test_flatten_before_event():
    pol = {"flatten_before": {"event": "earnings", "days": 1}}
    d, _ = evaluate(pol, PolicyState(), view(bar(1, 100, 101, 99, 100.5), days_to_event=1))
    assert d and d[0].kind == "event" and "earnings" in d[0].reason
    d, _ = evaluate(pol, PolicyState(), view(bar(2, 100, 101, 99, 100.5), days_to_event=None))
    assert d == []                                                   # unknown calendar never fires the exit


def test_profit_target_pct_of_credit():
    pol = {"profit_target_pct_of_credit": 60}
    v = view(bar(1, 100, 101, 99, 100.5), entry_mark=-1.00, net_mark=0.35)   # credit 1.00, buy-back 0.35
    d, _ = evaluate(pol, PolicyState(), v)
    assert d and d[0].kind == "credit_target"                        # 65% captured >= 60%
    v = view(bar(2, 100, 101, 99, 100.5), entry_mark=-1.00, net_mark=0.55)
    assert evaluate(pol, PolicyState(), v)[0] == []


def test_premium_stop_debit_and_credit():
    pol = {"premium_stop_pct": 50}
    v = view(bar(1, 100, 101, 99, 100.5), entry_mark=2.00, net_mark=0.9)     # long premium bled 55%
    d, _ = evaluate(pol, PolicyState(), v)
    assert d and d[0].kind == "premium_stop"
    v = view(bar(2, 100, 101, 99, 100.5), entry_mark=-1.00, net_mark=1.60)   # short credit: buy-back 60% past
    d, _ = evaluate(pol, PolicyState(), v)
    assert d and d[0].kind == "premium_stop"


def test_breakeven_and_trail_after_r():
    pol = {"stop": {"kind": "fixed", "price": 99.0}, "breakeven_after_r": 1.0,
           "trailing": {"mode": "pct", "value": 1.0, "after_r": 2.0}}
    st = PolicyState()
    v1 = view(bar(1, 100, 101.2, 99.9, 101.1))                       # +1.1R: breakeven arms, trail not yet
    d, m = evaluate(pol, st, v1)
    st = apply_moves(st, v1, d, m)
    assert st.stop == 100.0 and st.breakeven_done and not st.trailing_active
    v2 = view(bar(2, 101, 102.4, 100.9, 102.2))                      # +2.2R: trailing activates
    d, m = evaluate(pol, st, v2)
    st = apply_moves(st, v2, d, m)
    assert st.trailing_active and st.stop is not None and st.stop > 100.0
    # the stop only tightens: a pullback never loosens it
    v3 = view(bar(3, 102, 102.1, 101.0, 101.2))
    d, m = evaluate(pol, st, v3)
    st2 = apply_moves(st, v3, d, m)
    assert st2.stop >= st.stop


def test_one_exit_decision_per_bar():
    pol = {"stop": {"kind": "fixed", "price": 99.0}, "ladder": {"targets": [101.0], "fractions": [1.0]}}
    d, _ = evaluate(pol, PolicyState(), view(bar(1, 100, 101.5, 98.5, 98.8)))
    assert len(d) == 1 and d[0].kind == "stop"                       # protection outranks profit


# --- monetize campaign (research 2026-09-04: take+trail, ratchet floors, tightenings)

def _mon_pol(**over):
    pol = {"stop": {"kind": "none", "guard": "premium campaign"},
           "monetize": {"take_at_pct": 100, "take_fraction": 0.5,
                        "floors": [[50, 15], [100, 50], [200, 120]]},
           "premium_watch": True}
    pol["monetize"].update(over)
    return pol


def _mon_step(pol, st, mark, *, entry=1.0, dte=30, iv_ratio=None):
    """One evaluate+advance cycle on the CONTRACT mark, the way both the bar
    path and the quote loop run it."""
    from zargar.execution.policies import advance_premium_state, apply_premium_decision, evaluate_premium
    d = evaluate_premium(pol, st, mark, entry, dte=dte, iv_ratio=iv_ratio)
    st = apply_premium_decision(pol, st, d, entry)
    st = advance_premium_state(pol, st, mark, entry, dte=dte, iv_ratio=iv_ratio)
    return d, st


def test_monetize_house_money_take_then_ratchet_floor_banks_the_round_trip():
    # the GOOGL/RKLB shape: run up, give it all back — the campaign banks it
    pol = _mon_pol()
    st = PolicyState()
    d, st = _mon_step(pol, st, 1.20)                     # +20%: nothing
    assert d is None and st.premium_floor_gain is None
    d, st = _mon_step(pol, st, 1.60)                     # +60%: first rung arms
    assert d is None and st.premium_floor_gain == 15.0
    d, st = _mon_step(pol, st, 2.10)                     # +110%: the take fires
    assert d is not None and d.kind == "premium_take" and d.fraction == 0.5
    assert st.premium_take_done and st.premium_floor == 1.0   # rest can never go red
    d, st = _mon_step(pol, st, 2.10)                     # same mark again: no double take
    assert d is None and st.premium_floor_gain == 50.0   # +100 rung locked +50
    d, st = _mon_step(pol, st, 1.45)                     # gives back through the floor
    assert d is not None and d.kind == "premium_stop" and "ratchet floor" in d.reason


def test_monetize_fresh_high_never_stops_out_on_its_own_mark():
    pol = _mon_pol()
    st = PolicyState()
    d, st = _mon_step(pol, st, 3.10, entry=1.0)          # straight to +210%
    assert d is not None and d.kind == "premium_take"    # the take fires on the spike itself
    # the floor from THIS peak (120) is armed for the NEXT mark, not this one
    assert st.premium_floor_gain == 120.0
    d, st = _mon_step(pol, st, 3.05)                     # +205% still above the floor
    assert d is None
    d, st = _mon_step(pol, st, 2.15)                     # +115% < floor +120
    assert d is not None and d.kind == "premium_stop"


def test_monetize_floor_extends_beyond_the_top_rung():
    pol = _mon_pol()
    st = PolicyState(premium_take_done=True)
    for mark in (1.6, 2.2, 3.2, 4.2, 5.2):               # peak +420%
        _, st = _mon_step(pol, st, mark)
    assert st.premium_floor_gain == 320.0                # (200 + 2x100) - 80


def test_monetize_dte_and_iv_tightening():
    from zargar.execution.policies import advance_premium_state
    pol = _mon_pol()
    st = PolicyState(premium_take_done=True)
    _, st = _mon_step(pol, st, 1.60, dte=30)
    assert st.premium_floor_gain == 15.0
    st2 = advance_premium_state(pol, st, 1.60, 1.0, dte=5)          # inside 7 DTE: +17pp
    assert st2.premium_floor_gain == 32.0
    st3 = advance_premium_state(pol, st, 1.60, 1.0, dte=30, iv_ratio=1.5)   # vega-driven: +17pp
    assert st3.premium_floor_gain == 32.0
    st4 = advance_premium_state(pol, st, 1.60, 1.0, dte=1)          # stall zone: chase peak-25pp
    assert abs(st4.premium_floor_gain - 35.0) < 1e-6                 # max(15+17, 60-25)
    # the floor can never exceed the peak gain itself
    st5 = advance_premium_state(pol, PolicyState(premium_take_done=True), 1.10, 1.0, dte=1)
    assert st5.premium_floor_gain is None or st5.premium_floor_gain <= 10.0


def test_monetize_floor_never_ratchets_down():
    pol = _mon_pol()
    st = PolicyState(premium_take_done=True)
    _, st = _mon_step(pol, st, 1.60, dte=5)              # tightened floor 32
    assert st.premium_floor_gain == 32.0
    from zargar.execution.policies import advance_premium_state
    st2 = advance_premium_state(pol, st, 1.60, 1.0, dte=30)   # tightening condition gone
    assert st2.premium_floor_gain == 32.0                # stays — floors only climb


def test_monetize_validates():
    assert validate_policy(_mon_pol()) == []
    bad = _mon_pol(floors=[[50, 60]])                    # floor above its arming gain
    assert any("below its arming gain" in w for w in validate_policy(bad))
