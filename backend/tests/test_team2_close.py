"""Post-close findings of 2026-09-04 (TRADING-RULES F40/F43): a plan disarmed with a flatten in
flight keeps listening until the fill lands, and Team2 scores its own day — on the disarm path too."""
from __future__ import annotations

from zargar.execution.planrunner import Trade
from zargar.marketdata import persist_bars
from zargar.marketstructure import filter_session

from .test_team2_runner import rig  # noqa: F401
from .test_team2_session import DAY, prev_day_bars, trend_day


async def _armed_plan(eng):
    prev = prev_day_bars()
    today, _ = trend_day(prev)
    await persist_bars(eng.sf, prev)
    await persist_bars(eng.sf, filter_session(today, "pre"))
    out = await eng.team2.nightly_plans(DAY.isoformat(), arm=True)
    return eng.team2_runner, eng.team2_runner.get(out["armed"][0])


async def test_disarmed_plan_still_books_its_flatten_fill(rig, monkeypatch):
    eng, sim = rig
    runner, ap = await _armed_plan(eng)
    await runner.set_mode(ap.run_id, "auto")
    tr = Trade(trigger_id="scenario_1@09:30#1", kind="scenario_1", fired_ts=1, window="team2", entry=570.0, stop=569.0,
               targets=[], status="open", setup_id="scenario_1@09:30", entry_order_id="entry-1", filled_qty=18, remaining=18,
               avg_fill=0.59, instrument="options", order_symbol="QQQ260904P00717000", multiplier=100.0)
    ap.trades[tr.trigger_id] = tr

    async def fake_exit(ap_, t, kind, qty, *, journal, force_market=False, reason=""):
        # the flatten is SUBMITTED; its fill arrives later on the orders topic
        t.exits.append({"kind": kind, "qty": qty, "orderId": "flat-1", "status": "SUBMITTED", "filledQty": 0.0, "price": None})
        t.exit_order_ids.append("flat-1")
        runner.register_order("flat-1", (ap_.run_id, t.trigger_id))

    monkeypatch.setattr(runner, "_exit", fake_exit)
    assert await runner.disarm(ap.run_id, reason="loss halt", flatten=True)
    assert ap.run_id not in runner._armed and ap.run_id in runner._closing          # F40: still listening
    assert tr.remaining == 18 and tr.status == "open"
    await runner.on_order_update({"id": "flat-1", "status": "FILLED", "filledQty": 18.0, "avgFillPrice": 0.5599})
    assert tr.status == "closed" and tr.remaining == 0
    assert tr.realized_pnl < 0                                                       # (0.5599 - 0.59) x 18 x 100
    assert ap.run_id not in runner._closing                                          # settled → record final
    # the disarm path scored the day (F43): one real trade, no model trade, net of fees
    assert ap.scorecard and ap.scorecard["actualFires"] == 1 and ap.scorecard["basis"] == "session-read vs book"
    assert ap.scorecard["stopReason"] is None or "loss halt" in ap.scorecard["stopReason"]


async def test_team2_scorecard_compares_the_read_with_the_book(rig):
    eng, sim = rig
    runner, ap = await _armed_plan(eng)
    runner._last_sim[ap.run_id] = {"trades": [
        {"setup": "pm_break_down@10:30", "entryTs": 1000, "entryKind": "level", "strike": 768, "entryPremium": 0.39, "pnlPct": 62.3, "exitReason": "target", "win": True},
        {"setup": "pm_break_down@10:30", "entryTs": 5000, "entryKind": "ema", "strike": 768, "entryPremium": 0.51, "pnlPct": -12.2, "exitReason": "stop", "win": False},
    ], "setups": [], "bias": {"label": "bounce PDL"}}
    ap.trades["t1"] = Trade(trigger_id="pm_break_down@10:30#1", kind="pm_break_down", fired_ts=1100, window="team2", entry=770.5,
                            stop=771.0, targets=[], status="closed", setup_id="pm_break_down@10:30", filled_qty=10, avg_fill=0.40,
                            realized_pnl=250.0, instrument="options", order_symbol="SPY260904P00768000", multiplier=100.0)
    ap.events.append({"event": "skip_no_trade_zone"}); ap.events.append({"event": "skip_no_trade_zone"})
    sc = runner._score_execution(ap)
    assert sc["theoreticalFires"] == 2 and sc["actualFires"] == 1 and sc["matched"] == 1
    assert sc["rows"][0]["trigger"] == "pm_break_down@10:30#1" and sc["rows"][1]["status"] == "not taken"
    assert sc["realizedPnl"] < sc["realizedPnlGross"] == 250.0                      # fees counted
    assert sc["skips"] == {"skip_no_trade_zone": 2} and sc["bias"] == "bounce PDL"


async def test_clock_flatten_sells_the_book_at_flatten_time_whatever_the_read_says(rig, monkeypatch):
    """Post-close audit 2026-09-04: the read's position can be gone while the book still holds a 0DTE
    contract; the shared clock close is 16:05, after expiry. Team2 flattens the BOOK at flatten_min."""
    eng, sim = rig
    runner, ap = await _armed_plan(eng)
    await runner.set_mode(ap.run_id, "auto")
    rules = runner.rules()
    tr = Trade(trigger_id="pm_break_down@13:30#1", kind="pm_break_down", fired_ts=1, window="team2", entry=717.0, stop=717.4,
               targets=[], status="open", setup_id="pm_break_down@13:30", entry_order_id="e1", filled_qty=18, remaining=18,
               avg_fill=0.59, instrument="options", order_symbol="QQQ260904P00717000", multiplier=100.0)
    working = Trade(trigger_id="pm_break_down@13:30#2", kind="pm_break_down", fired_ts=2, window="team2", entry=717.0, stop=717.4,
                    targets=[], status="working", setup_id="pm_break_down@13:30", entry_order_id="e2", instrument="options")
    ap.trades[tr.trigger_id] = tr
    ap.trades[working.trigger_id] = working
    calls: list[tuple] = []

    async def fake_exit(ap_, t, kind, qty, *, journal, force_market=False, reason=""):
        calls.append((t.trigger_id, kind, qty, force_market))
        t.exits.append({"kind": kind, "qty": qty, "orderId": "f", "status": "SUBMITTED", "filledQty": 0.0})

    async def fake_cancel(oid):
        calls.append(("cancel", oid))

    monkeypatch.setattr(runner, "_exit", fake_exit)
    monkeypatch.setattr(eng.orders, "cancel", fake_cancel)
    await runner._clock_flatten(ap, rules)
    assert ("cancel", "e2") in calls and working.status == "cancelled"
    assert any(c[0] == tr.trigger_id and c[1] == "flatten" and c[2] == 18 and c[3] for c in calls)
    assert any(e["event"] == "clock_flatten" for e in ap.events)
    # a second pass does not double-sell: the flatten is already pending
    n = len(calls)
    await runner._clock_flatten(ap, rules)
    assert len(calls) == n
