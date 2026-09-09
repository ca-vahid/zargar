"""Restart readiness + restoration check (2026-09-09): "no open positions" is not the test."""
from __future__ import annotations

import httpx

from zargar.execution.planrunner import Trade
from zargar.ops import compare_states, readiness_from_state, restart_readiness, restart_state

from .test_team2_runner import rig  # noqa: F401
from .test_team2_session import DAY, prev_day_bars, trend_day


async def _armed(eng):
    from zargar.marketdata import persist_bars
    from zargar.marketstructure import filter_session
    prev = prev_day_bars()
    today, _ = trend_day(prev)
    await persist_bars(eng.sf, prev)
    await persist_bars(eng.sf, filter_session(today, "pre"))
    out = await eng.team2.nightly_plans(DAY.isoformat(), arm=True)
    return eng.team2_runner.get(out["armed"][0])


def _trade(status: str, **kw) -> Trade:
    t = Trade(trigger_id="scenario_1@09:30#1", kind="scenario_1", fired_ts=1, window="team2", entry=570.0, stop=569.5,
              targets=[571.0], status=status, setup_id="scenario_1@09:30", instrument="options",
              order_symbol="SPY260909C00571000", multiplier=100.0, direction="long", **kw)
    return t


async def test_idle_desk_is_safe_and_an_open_trade_or_pending_exit_blocks(rig):
    eng, sim = rig
    ap = await _armed(eng)
    st = await restart_state(eng)
    assert any(x.endswith(ap.run_id) for x in st["armed"]) and st["openTrades"] == [] and st["inflightOrders"] == []
    assert readiness_from_state(st)["safe"]
    # an open trade in a money mode
    await eng.team2_runner.set_mode(ap.run_id, "auto")
    ap.trades["scenario_1@09:30#1"] = _trade("open", filled_qty=3, remaining=3, avg_fill=0.6)
    rd = await restart_readiness(eng, caller="test")
    assert not rd["safe"] and any("open technique trade" in r for r in rd["reasons"])
    # a pending exit on it
    ap.trades["scenario_1@09:30#1"].exits.append({"kind": "tp1", "qty": 1, "orderId": "x1", "status": "SUBMITTED", "filledQty": 0.0})
    rd = await restart_readiness(eng, journal=False)
    assert any("exit order" in r for r in rd["reasons"])
    # a working entry
    ap.trades["scenario_1@09:30#1"] = _trade("working")
    rd = await restart_readiness(eng, journal=False)
    assert any("entry order" in r for r in rd["reasons"])
    # closed: safe again
    ap.trades["scenario_1@09:30#1"] = _trade("closed")
    assert (await restart_readiness(eng, journal=False))["safe"]


async def test_restore_check_compares_ids_not_counts():
    before = {"armed": ["team2:a", "team2:b"], "openTrades": ["team2:SPY:x"], "pendingExits": [], "restingOrders": ["o1:GOOGL"], "inflightOrders": []}
    same = compare_states(before, {"armed": ["team2:b", "team2:a"], "openTrades": ["team2:SPY:x"], "pendingExits": [], "restingOrders": ["o1:GOOGL"], "inflightOrders": []})
    assert same["ok"] and same["counts"]["armed"] == "2/2" and same["counts"]["restingOrders"] == "1/1"
    swapped = compare_states(before, {"armed": ["team2:a", "team2:c"], "openTrades": [], "pendingExits": [], "restingOrders": [], "inflightOrders": []})
    assert not swapped["ok"] and swapped["missing"] == {"armed": ["team2:b"], "openTrades": ["team2:SPY:x"], "restingOrders": ["o1:GOOGL"]}
    # a resting venue order never blocks; an in-flight one does
    assert readiness_from_state({"restingOrders": ["o1:GOOGL"], "inflightOrders": []})["safe"]
    assert not readiness_from_state({"restingOrders": [], "inflightOrders": ["o2:AMZN"]})["safe"]


async def test_the_endpoints_answer_local_callers_only(rig):
    eng, sim = rig
    from zargar.api.app import create_app
    app = create_app(eng.config, eng)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 5555)), base_url="http://t") as c:
        r = await c.get("/api/ops/restart-check?caller=test")
        assert r.status_code == 200 and r.json()["safe"] is True and "state" in r.json()
        st = (await c.get("/api/ops/state")).json()
        r = await c.post("/api/ops/restore-check", json=st)
        assert r.status_code == 200 and r.json()["ok"] is True
        r = await c.get("/api/ops/state", headers={"x-forwarded-for": "10.0.0.9"})
        assert r.status_code == 403
