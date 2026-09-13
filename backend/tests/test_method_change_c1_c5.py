"""METHOD-CHANGE-PLAN-2026-09-12: C3 gap-day policy, C4 targeted scratch, C5 range break (tracker /
simulator / live-exit knobs, all off by default), C1b pick retry on a wide spread."""
import datetime as dt

from zargar.execution.exits import plan_exit
from zargar.marketstructure.outcome import simulate_plan
from zargar.marketstructure.tracker import TriggerTracker
from zargar.technique.options import pick_for_setup
from zargar.technique.rulebook import Thresholds

from .test_scratch_rule import FakeTrade, _bar as _xbar, _plan
from .test_technique_walkforward import _bar
from .test_tracker_gap_continuation import _session, _trigger

DAY = dt.date(2026, 9, 9)


# --- C3 gap-day policy -----------------------------------------------------------------------------
def test_gap_day_waits_then_continues():
    t = Thresholds(gap_day_pct=0.5, gap_day_wait_minutes=5, gap_day_continuation=True)
    tr = TriggerTracker(_trigger(), thresholds=t, prev_close=100.4)   # opens 99.0 = -1.4%: a gap day
    bars = _session()
    tr.on_bar(bars[0], 0)
    assert tr.gap_day and tr.kind == "breakdown" and tr.status == "waiting"
    for i, b in enumerate(bars[1:], start=1):
        tr.on_bar(b, i)
    assert tr.status == "fired"                        # the 09:37 break is past the 5-minute wait
    assert any(e["event"] == "gap_day" for e in tr.events)


def test_gap_day_wait_blocks_the_first_minutes():
    t = Thresholds(gap_day_pct=0.5, gap_day_wait_minutes=30, gap_day_continuation=True)
    tr = TriggerTracker(_trigger(), thresholds=t, prev_close=100.4)
    for i, b in enumerate(_session()):
        tr.on_bar(b, i)
    assert tr.status in ("waiting", "observed")       # the 09:37 break sits inside the 30-minute wait
    assert any(e["event"] == "break_outside_window" for e in tr.events)


def test_no_gap_day_without_the_knob():
    tr = TriggerTracker(_trigger(), thresholds=Thresholds(), prev_close=100.4)
    tr.on_bar(_session()[0], 0)
    assert tr.gap_day is False and tr.status == "gapped_through"


# --- C5 range break ----------------------------------------------------------------------------------
def _break_trigger():
    return {"id": "k1", "kind": "breakout", "direction": "long", "setupType": "breakout",
            "entry": {"price": 100.0, "basis": "on_break"}, "stop": {"price": 99.4},
            "targets": [{"price": 101.5}, {"price": 102.5}, {"price": 103.5}], "valid": True}


def _squeeze_then_break():
    bars = []
    for i in range(20):                                   # 20 bars of normal 0.40 ranges below the level
        bars.append(_bar(DAY, 9, 30 + i, 99.3, 99.7, 99.3, 99.5, 1000))
    for i in range(6):                                    # 6-bar squeeze: 0.10 total span
        bars.append(_bar(DAY, 9, 50 + i, 99.85, 99.92, 99.82, 99.9, 900))
    bars.append(_bar(DAY, 9, 56, 99.9, 100.3, 99.88, 100.25, 1600))   # the break close
    for i in range(3):
        bars.append(_bar(DAY, 9, 57 + i, 100.25, 100.35, 100.2, 100.3, 1200))
    return bars


def test_range_break_fires_on_the_break_close():
    tr = TriggerTracker(_break_trigger(), thresholds=Thresholds(range_break=True), prev_close=99.5)
    bars = _squeeze_then_break()
    for i, b in enumerate(bars):
        tr.on_bar(b, i)
        if tr.status == "fired":
            break
    assert tr.status == "fired" and tr.fired_ts == bars[26].ts and tr.trigger.get("rangeBreak") is True


def test_range_break_off_waits_for_confirmation():
    tr = TriggerTracker(_break_trigger(), thresholds=Thresholds(), prev_close=99.5)
    bars = _squeeze_then_break()
    for i, b in enumerate(bars):
        tr.on_bar(b, i)
    assert tr.fired_ts != bars[26].ts                  # the follow-through wait still applies without the knob


# --- C4 targeted scratch -----------------------------------------------------------------------------
def _up_then_back():
    return [_xbar(0, 100, 100.2, 99.8, 100), _xbar(1, 100, 100.6, 99.9, 100.5), _xbar(2, 100.5, 101.2, 100.3, 101.0),
            _xbar(3, 101, 101.1, 100.2, 100.3), _xbar(4, 100.3, 100.4, 99.6, 99.7), _xbar(5, 99.7, 99.8, 98.7, 98.8)]


def test_targeted_scratch_applies_only_when_tp1_is_far():
    far = simulate_plan(_up_then_back(), 0, _plan(), entry_window=1, horizon=60, stop_on="close",
                        scratch_r=0.75, scratch_only_far_tp1=True, far_tp1_r=3.0)     # TP1 = 5R away
    assert far["scratched"] is True and far["outcome"] == "scratched"
    plan = _plan(); plan["targets"] = [{"price": 101.5}, {"price": 108.0}, {"price": 111.0}]   # TP1 = 1.5R
    near = simulate_plan(_up_then_back(), 0, plan, entry_window=1, horizon=60, stop_on="close",
                         scratch_r=0.75, scratch_only_far_tp1=True, far_tp1_r=3.0)
    assert near["scratched"] is False and near["outcome"] == "stopped"


def test_live_targeted_scratch_matches_the_simulator():
    near = FakeTrade(remaining=10, filled_qty=10, trims_done=0, targets=[101.5, 108, 111], stop=99.0)
    assert plan_exit(near, _xbar(1, 100, 100.9, 99.9, 100.8), close_ms=10**12, flatten_minutes=5, stop_on="close",
                     scratch_r=0.75, scratch_only_far_tp1=True) is None
    far = FakeTrade(remaining=10, filled_qty=10, trims_done=0, targets=[105, 108, 111], stop=99.0)
    d = plan_exit(far, _xbar(1, 100, 100.9, 99.9, 100.8), close_ms=10**12, flatten_minutes=5, stop_on="close",
                  scratch_r=0.75, scratch_only_far_tp1=True)
    assert d is not None and d.kind == "scratch"


# --- C1b pick retry ------------------------------------------------------------------------------------
class _Client:
    name = "fake"

    async def expirations(self, symbol):
        return ["2026-09-18", "2026-09-25"]

    async def chain(self, symbol, expiry):
        wide = expiry == "2026-09-18"
        rows = []
        for k in (100, 101, 102, 103):
            bid, ask = (1.0, 1.6) if (wide and k == 101) else (1.0, 1.08)
            rows.append({"symbol": f"T{expiry.replace('-', '')[2:]}C{int(k * 1000):08d}", "strike": float(k),
                         "option_type": "call", "bid": bid, "ask": ask, "mid": (bid + ask) / 2, "openInterest": 5000,
                         "volume": 500, "delta": 0.45, "iv": 0.4, "expiry": expiry})
        return rows


async def test_pick_retry_takes_the_tighter_neighbour():
    c = _Client()
    d = await pick_for_setup(c, "T", 100.5, "long", today=dt.date(2026, 9, 14), max_spread_pct=10.0)
    assert d.get("pickRetry") and d["pickRetry"]["took"] in ("next_strike", "next_expiry"), d
    assert float(d["spreadPct"]) < 10.0
    d2 = await pick_for_setup(c, "T", 100.5, "long", today=dt.date(2026, 9, 14), retry_wide=False)
    assert d2.get("pickRetry") is None and float(d2["strike"]) == 101.0
