"""Standing orders (2026-11-14): the user's plan, drafted by Claude, armed by the user in one click, executed by
the app through OrderManager/RiskGate on the sim broker here."""
import datetime as dt
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from zargar.engine import Engine
from zargar.execution import standing
from zargar.execution.standing import StandingOrderService, confirm_phrase, exit_policy, limit_for
from zargar.models import Order, StandingOrder
from zargar.signals.service import attach_signal_layer

from .conftest import make_test_config, wait_for

ET = ZoneInfo("America/New_York")
OPEN_NOW = dt.datetime(2026, 11, 10, 11, 0, tzinfo=ET)          # a Tuesday, mid-session


# ------------------------------------------------------------------ pure pricing / sizing
def test_limit_prices_off_the_live_quote_inside_the_users_cap():
    q = SimpleNamespace(bid=99.0, ask=100.0)
    assert limit_for("BUY", q, 0.5, None) == (100.5, "")
    assert limit_for("BUY", q, 0.5, 100.2) == (100.2, "")                     # never above the cap
    assert limit_for("BUY", q, 0.5, 99.5)[0] is None                          # ask above the cap: wait
    assert limit_for("SELL", q, 0.5, None) == (98.5, "")
    assert limit_for("SELL", q, 0.5, 99.5)[0] is None                         # bid below the floor: wait
    assert limit_for("BUY", SimpleNamespace(bid=0, ask=0), 0.5, None)[0] is None


def test_budget_sizes_whole_shares_and_counts_what_is_already_filled():
    row = SimpleNamespace(qty=None, budget=1000.0, filled_qty=0.0, avg_fill_price=None)
    assert standing.size_for(row, 99.5) == 10.0
    row = SimpleNamespace(qty=None, budget=1000.0, filled_qty=4.0, avg_fill_price=100.0)
    assert standing.size_for(row, 100.0) == 6.0
    row = SimpleNamespace(qty=5.0, budget=None, filled_qty=2.0, avg_fill_price=50.0)
    assert standing.size_for(row, 50.0) == 3.0


def test_exit_policy_is_plus_ten_minus_ten_from_the_average_fill():
    pol = exit_policy(80.0, 10, 10)
    assert pol["stop"] == {"kind": "fixed", "price": 72.0}
    assert pol["ladder"] == {"targets": [88.0], "fractions": [1.0]}


# ------------------------------------------------------------------ engine rig
@pytest.fixture
async def rig(fresh_db):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    svc = StandingOrderService(eng)                  # ticks driven by the test (no background loop)
    eng.standing_orders = svc
    try:
        yield eng, svc
    finally:
        await eng.stop()


def _sim_pid(eng) -> str:
    return next(p["id"] for p in eng.positions.portfolios() if p["kind"] == "sim")


async def _quote(eng, sym):
    await eng.ensure_symbol(sym)
    await wait_for(lambda: eng.quotes.get(sym) is not None and eng.quotes.get(sym).ask > 0, timeout=5)
    return eng.quotes.get(sym)


async def _run_until(svc, oid, statuses, timeout=15):
    async def done():
        await svc.tick(now=OPEN_NOW)
        r = await svc.get(oid)
        return r if r["status"] in statuses else None
    return await wait_for(done, timeout=timeout)


async def test_drafts_never_arm_themselves_and_arming_needs_the_users_phrase(rig):
    eng, svc = rig
    d = await svc.create({"portfolioId": _sim_pid(eng), "symbol": "STA", "side": "BUY", "qty": 1})
    assert d["status"] == "draft"
    await svc.tick(now=OPEN_NOW)
    assert (await svc.get(d["id"]))["status"] == "draft"                     # a draft is never acted on
    with pytest.raises(ValueError):
        await svc.arm(d["id"], "yes")
    armed = await svc.arm(d["id"], confirm_phrase(d["id"]))
    assert armed["status"] == "armed"


async def test_real_money_books_need_the_users_allow_live_switch(rig, monkeypatch):
    eng, svc = rig
    monkeypatch.setattr(svc, "_kind", lambda pid: "live")
    d = await svc.create({"portfolioId": _sim_pid(eng), "symbol": "STB", "side": "BUY", "qty": 1})
    with pytest.raises(ValueError, match="allow_live"):
        await svc.arm(d["id"], confirm_phrase(d["id"]))
    p = await svc.create_plan("p", [{"portfolioId": _sim_pid(eng), "symbol": "STB", "side": "BUY", "qty": 1}])
    with pytest.raises(ValueError, match="allow_live"):
        await svc.arm_plan(p["planId"], p["armConfirm"])


async def test_one_click_arms_the_whole_plan(rig):
    eng, svc = rig
    pid = _sim_pid(eng)
    p = await svc.create_plan("monday tests", [
        {"portfolioId": pid, "symbol": "STC", "side": "BUY", "qty": 1},
        {"portfolioId": pid, "symbol": "STD", "side": "BUY", "budget": 500}])
    with pytest.raises(ValueError):
        await svc.arm_plan(p["planId"], "ARM nope")
    out = await svc.arm_plan(p["planId"], p["armConfirm"])
    assert [o["status"] for o in out["armed"]] == ["armed", "armed"]


async def test_an_armed_buy_fills_and_hands_its_exits_to_the_position_manager(rig):
    eng, svc = rig
    q = await _quote(eng, "STE")
    d = await svc.create({"portfolioId": _sim_pid(eng), "symbol": "STE", "side": "BUY", "qty": 3,
                          "takeProfitPct": 10, "stopLossPct": 10, "slippagePct": 2})
    await svc.arm(d["id"], confirm_phrase(d["id"]))
    r = await _run_until(svc, d["id"], ("done", "failed"))
    assert r["status"] == "done", r
    assert r["filledQty"] == 3 and r["avgFillPrice"] > 0
    pos = eng.position_manager.get(r["positionId"])
    assert pos is not None and pos.policy["stop"]["price"] == round(r["avgFillPrice"] * 0.9, 2)
    assert pos.policy["ladder"]["targets"] == [round(r["avgFillPrice"] * 1.1, 2)]
    async with eng.sf() as s:
        orders = (await s.execute(select(Order).where(Order.symbol == "STE", Order.side == "BUY"))).scalars().all()
    assert all(f"standing:{d['id']}" in (o.tags or []) for o in orders)
    assert q.ask > 0


async def test_an_armed_sell_is_reduce_only_and_completes(rig):
    eng, svc = rig
    await _quote(eng, "STF")
    pid = _sim_pid(eng)
    b = await svc.create({"portfolioId": pid, "symbol": "STF", "side": "BUY", "qty": 2, "slippagePct": 2})
    await svc.arm(b["id"], confirm_phrase(b["id"]))
    assert (await _run_until(svc, b["id"], ("done", "failed")))["status"] == "done"
    s = await svc.create({"portfolioId": pid, "symbol": "STF", "side": "SELL", "qty": 2, "slippagePct": 2})
    await svc.arm(s["id"], confirm_phrase(s["id"]))
    r = await _run_until(svc, s["id"], ("done", "failed"))
    assert r["status"] == "done" and r["filledQty"] == 2, r
    assert abs(eng.positions.position_qty(pid, "STF", "STK")) < 1e-9


async def test_nothing_fires_outside_the_session(rig):
    eng, svc = rig
    await _quote(eng, "STG")
    d = await svc.create({"portfolioId": _sim_pid(eng), "symbol": "STG", "side": "BUY", "qty": 1})
    await svc.arm(d["id"], confirm_phrase(d["id"]))
    await svc.tick(now=dt.datetime(2026, 11, 10, 8, 0, tzinfo=ET))
    r = await svc.get(d["id"])
    assert r["status"] == "armed" and r["lastError"] == "market closed"


async def test_an_unfilled_order_expires_after_its_date(rig):
    eng, svc = rig
    d = await svc.create({"portfolioId": _sim_pid(eng), "symbol": "STH", "side": "BUY", "qty": 1,
                          "expiresOn": "2026-11-09"})
    async with eng.sf() as s:
        row = await s.get(StandingOrder, d["id"])
        row.status = "armed"
        await s.commit()
    await svc.tick(now=OPEN_NOW)
    assert (await svc.get(d["id"]))["status"] == "expired"


async def test_a_crash_mid_placement_is_reconciled_from_the_order_tag_never_resent(rig):
    eng, svc = rig
    await _quote(eng, "STI")
    d = await svc.create({"portfolioId": _sim_pid(eng), "symbol": "STI", "side": "BUY", "qty": 1, "slippagePct": 2})
    row = await svc._update(d["id"], status="armed")
    q = eng.quotes.get("STI")
    res = await eng.orders.place(svc._intent(row, 1, round(q.ask * 1.02, 2)))   # the call that "crashed"
    await svc._update(d["id"], status="placing")
    await svc.tick(now=OPEN_NOW)
    r = await svc.get(d["id"])
    assert r["orderId"] == res["id"] and r["status"] in ("working", "armed", "done")
    async with eng.sf() as s:
        n = len((await s.execute(select(Order).where(Order.symbol == "STI"))).scalars().all())
    assert n == 1                                                               # nothing re-sent


async def test_a_due_order_on_a_stale_quote_asks_the_feed_for_a_fresh_one(rig, monkeypatch):
    """2026-11-16: XIU.TO's only source (the Yahoo poll) ran 20-40 s behind the 10 s freshness rule; a due order
    now asks the feed for one fresh quote instead of waiting on the sweep."""
    eng, svc = rig
    await _quote(eng, "STJ")
    calls = []
    real_age = eng.quotes.age_seconds
    monkeypatch.setattr(eng.quotes, "age_seconds", lambda s: real_age(s) if calls else 60.0)

    async def refresh(symbol):
        calls.append(symbol)
        return True
    monkeypatch.setattr(eng.feed, "refresh", refresh, raising=False)
    d = await svc.create({"portfolioId": _sim_pid(eng), "symbol": "STJ", "side": "BUY", "qty": 1, "slippagePct": 2,
                          "trigger": "at", "notBefore": "12:00"})
    await svc.arm(d["id"], confirm_phrase(d["id"]))
    await svc.tick(now=OPEN_NOW)                                   # 11:00 - not due: no refresh asked for
    assert calls == [] and (await svc.get(d["id"]))["lastError"] == "waiting for 12:00 ET"
    due = dt.datetime(2026, 11, 10, 12, 1, tzinfo=ET)
    await svc.tick(now=due)
    assert calls == ["STJ"]
    assert (await svc.get(d["id"]))["status"] in ("placing", "working", "done")
