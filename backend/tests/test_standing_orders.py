"""Standing orders (2026-11-14): the user's plan, drafted by Claude, armed by the user in one click, executed by
the app through OrderManager/RiskGate on the sim broker here."""
import datetime as dt
import math
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
    svc.start = lambda: None                         # arm() starts the real-clock loop: in market hours it raced the test
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
    d = await svc.create({"portfolioId": _sim_pid(eng), "symbol": "STE", "side": "BUY", "qty": 1,
                          "takeProfitPct": 10, "stopLossPct": 10, "slippagePct": 2})
    await svc.arm(d["id"], confirm_phrase(d["id"]))
    r = await _run_until(svc, d["id"], ("done", "failed"))
    assert r["status"] == "done", r
    assert r["filledQty"] == 1 and r["avgFillPrice"] > 0   # 1 share: the sim price is random and 3 broke the $1k cap
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


async def test_a_sell_never_exceeds_the_shares_the_book_holds(rig):
    """2026-11-16: a standing SELL with no position reached IBKR (XIU.TO) - reduce-only orders skip the entry caps,
    so on a US name the venue would have opened a short. No shares: the order fails before any venue contact."""
    eng, svc = rig
    await _quote(eng, "STK1")
    pid = _sim_pid(eng)
    s = await svc.create({"portfolioId": pid, "symbol": "STK1", "side": "SELL", "qty": 3, "slippagePct": 2})
    await svc.arm(s["id"], confirm_phrase(s["id"]))
    assert (await svc.preflight(s["id"]))["ok"] is False
    await svc.tick(now=OPEN_NOW)
    r = await svc.get(s["id"])
    assert r["status"] == "failed" and "holds no STK1" in (r["note"] or r["lastError"] or ""), r
    async with eng.sf() as session:
        assert not (await session.execute(select(Order).where(Order.symbol == "STK1"))).scalars().all()


# ------------------------------------------------------------------ delegation (2026-11-16)
def _future(hours=8):
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=hours)).isoformat()


async def _delegate(svc, pid, per=1000.0, total=1500.0, hours=8):
    return await svc.create_delegation({"portfolioIds": [pid], "endsAt": _future(hours), "maxOrderNotional": per,
                                        "maxTotalNotional": total}, standing.DELEGATE_PHRASE)


async def test_a_delegation_needs_the_users_phrase_and_sane_caps(rig):
    eng, svc = rig
    pid = _sim_pid(eng)
    with pytest.raises(ValueError):
        await svc.create_delegation({"portfolioIds": [pid], "endsAt": _future(), "maxOrderNotional": 10,
                                     "maxTotalNotional": 20}, "yes")
    with pytest.raises(ValueError):
        await _delegate(svc, pid, per=500, total=100)                       # per-order above total
    with pytest.raises(ValueError):
        await _delegate(svc, pid, hours=24 * 40)                            # longer than 31 days
    d = await _delegate(svc, pid)
    assert d["active"] and d["confirm"] == standing.delegated_phrase(d["id"]) and d["committed"] == 0


async def test_delegated_arms_are_bounded_by_account_and_caps_and_stamped(rig):
    eng, svc = rig
    pid = _sim_pid(eng)
    d = await _delegate(svc, pid, per=1000, total=1500)
    ok = await svc.create({"portfolioId": pid, "symbol": "DLA", "side": "BUY", "qty": 5, "maxPrice": 150})
    armed = await svc.arm(ok["id"], d["confirm"])
    assert armed["status"] == "armed" and armed["armedBy"] == f"claude:delegation:{d['id']}"
    big = await svc.create({"portfolioId": pid, "symbol": "DLB", "side": "BUY", "budget": 1200})
    with pytest.raises(ValueError, match="per-order cap"):
        await svc.arm(big["id"], d["confirm"])
    over = await svc.create({"portfolioId": pid, "symbol": "DLC", "side": "BUY", "budget": 800})
    with pytest.raises(ValueError, match="total cap"):                        # 750 used + 800 > 1500
        await svc.arm(over["id"], d["confirm"])
    loose = await svc.create({"portfolioId": pid, "symbol": "DLD", "side": "BUY", "qty": 1})
    with pytest.raises(ValueError, match="budget or a max price"):
        await svc.arm(loose["id"], d["confirm"])
    sell = await svc.create({"portfolioId": pid, "symbol": "DLE", "side": "SELL", "qty": 1})
    assert (await svc.arm(sell["id"], d["confirm"]))["status"] == "armed"     # sells only need the account


async def test_a_revoked_expired_or_foreign_delegation_arms_nothing(rig):
    eng, svc = rig
    pid = _sim_pid(eng)
    d = await _delegate(svc, pid)
    late = await svc.create({"portfolioId": pid, "symbol": "DLF", "side": "BUY", "qty": 1, "maxPrice": 10,
                             "expiresOn": (dt.date.today() + dt.timedelta(days=5)).isoformat()})
    with pytest.raises(ValueError, match="outlives"):
        await svc.arm(late["id"], d["confirm"])
    await svc.revoke_delegation(d["id"])
    o = await svc.create({"portfolioId": pid, "symbol": "DLG", "side": "BUY", "qty": 1, "maxPrice": 10})
    with pytest.raises(ValueError, match="not active"):
        await svc.arm(o["id"], d["confirm"])
    other = next(p["id"] for p in eng.positions.portfolios() if p["id"] != pid)
    d2 = await svc.create_delegation({"portfolioIds": [other], "endsAt": _future(), "maxOrderNotional": 100,
                                      "maxTotalNotional": 100}, standing.DELEGATE_PHRASE)
    with pytest.raises(ValueError, match="not covered"):
        await svc.arm(o["id"], d2["confirm"])
    with pytest.raises(ValueError, match="no such delegation"):
        await svc.arm(o["id"], "DELEGATED 0000")


async def test_a_delegated_plan_arms_all_or_nothing_against_the_total_cap(rig):
    eng, svc = rig
    pid = _sim_pid(eng)
    d = await _delegate(svc, pid, per=1000, total=1500)
    p = await svc.create_plan("ant", [{"portfolioId": pid, "symbol": "DLH", "side": "BUY", "budget": 900},
                                      {"portfolioId": pid, "symbol": "DLI", "side": "BUY", "budget": 900}])
    with pytest.raises(ValueError, match="together exceed"):
        await svc.arm_plan(p["planId"], d["confirm"])
    assert all(o["status"] == "draft" for o in [await svc.get(x["id"]) for x in p["orders"]])
    p2 = await svc.create_plan("ok", [{"portfolioId": pid, "symbol": "DLJ", "side": "BUY", "budget": 700},
                                      {"portfolioId": pid, "symbol": "DLJ", "side": "SELL", "qty": 1}])
    out = await svc.arm_plan(p2["planId"], d["confirm"])
    assert [o["status"] for o in out["armed"]] == ["armed", "armed"]


# ------------------------------------------------------------------ repairs (2026-11-16)
async def _failed_user_order(svc, pid, **kw):
    spec = {"portfolioId": pid, "symbol": "RPA", "side": "BUY", "qty": 2, "maxPrice": 60.0, **kw}
    d = await svc.create(spec)
    await svc.arm(d["id"], confirm_phrase(d["id"]))
    await svc._update(d["id"], status="failed", last_error="refused: venue says no")
    return d


async def test_a_repair_of_a_user_armed_order_is_armed_at_once_inside_the_originals_bounds(rig):
    eng, svc = rig
    pid = _sim_pid(eng)
    orig = await _failed_user_order(svc, pid)
    out = await svc.repair_plan("fix", [{"repairOf": orig["id"], "portfolioId": pid, "symbol": "RPB", "side": "BUY",
                                         "qty": 1, "maxPrice": 50.0}])
    r = out["armed"][0]
    assert r["status"] == "armed" and r["armedBy"] == f"claude:repair:{orig['id']}" and r["repairOf"] == orig["id"]


async def test_a_repair_never_grows_the_order_or_changes_side_or_outlives_it(rig):
    eng, svc = rig
    pid = _sim_pid(eng)
    orig = await _failed_user_order(svc, pid)
    base = {"repairOf": orig["id"], "portfolioId": pid, "symbol": "RPA", "side": "BUY"}
    with pytest.raises(ValueError, match="more shares"):
        await svc.repair_plan("x", [{**base, "qty": 3, "maxPrice": 10}])
    with pytest.raises(ValueError, match="more than the original"):
        await svc.repair_plan("x", [{**base, "qty": 2, "maxPrice": 80}])               # 160 > 120
    with pytest.raises(ValueError, match="side"):
        await svc.repair_plan("x", [{**base, "side": "SELL", "qty": 1}])
    with pytest.raises(ValueError, match="outlives"):
        await svc.repair_plan("x", [{**base, "qty": 1, "maxPrice": 50,
                                     "expiresOn": (dt.date.today() + dt.timedelta(days=3)).isoformat()}])
    other = next(p["id"] for p in eng.positions.portfolios() if p["id"] != pid)
    with pytest.raises(ValueError, match="same broker"):
        await svc.repair_plan("x", [{**base, "portfolioId": other, "qty": 1, "maxPrice": 50}])


async def test_repairs_need_a_user_armed_original_and_stop_after_two(rig):
    eng, svc = rig
    pid = _sim_pid(eng)
    draft = await svc.create({"portfolioId": pid, "symbol": "RPC", "side": "BUY", "qty": 1, "maxPrice": 10})
    await svc._update(draft["id"], status="failed")                       # never armed by the user
    with pytest.raises(ValueError, match="user armed"):
        await svc.repair_plan("x", [{"repairOf": draft["id"], "portfolioId": pid, "symbol": "RPC", "side": "BUY",
                                     "qty": 1, "maxPrice": 10}])
    orig = await _failed_user_order(svc, pid)
    prev = orig
    for _ in range(2):
        out = await svc.repair_plan("x", [{"repairOf": prev["id"], "portfolioId": pid, "symbol": "RPA", "side": "BUY",
                                           "qty": 1, "maxPrice": 50}])
        prev = out["armed"][0]
        await svc._update(prev["id"], status="failed")
    with pytest.raises(ValueError, match="already repaired"):
        await svc.repair_plan("x", [{"repairOf": prev["id"], "portfolioId": pid, "symbol": "RPA", "side": "BUY",
                                     "qty": 1, "maxPrice": 50}])


async def test_a_sell_repair_may_change_symbol_only_to_what_the_repair_buys(rig):
    eng, svc = rig
    pid = _sim_pid(eng)
    buy = await _failed_user_order(svc, pid)
    sell = await svc.create({"portfolioId": pid, "symbol": "RPA", "side": "SELL", "qty": 1})
    await svc.arm(sell["id"], confirm_phrase(sell["id"]))
    with pytest.raises(ValueError, match="only to one this repair also buys"):
        await svc.repair_plan("x", [{"repairOf": sell["id"], "portfolioId": pid, "symbol": "RPZ", "side": "SELL", "qty": 1}])
    out = await svc.repair_plan("x", [
        {"repairOf": buy["id"], "portfolioId": pid, "symbol": "RPZ", "side": "BUY", "qty": 1, "maxPrice": 20},
        {"repairOf": sell["id"], "portfolioId": pid, "symbol": "RPZ", "side": "SELL", "qty": 1}])
    assert [o["status"] for o in out["armed"]] == ["armed", "armed"]
    assert (await svc.get(sell["id"]))["status"] == "cancelled"             # the waiting original is replaced


# ------------------------------------------------------------------ spend-all + per-book cap (2026-11-17)
async def test_a_spend_all_buy_waits_for_the_plans_sells_then_sizes_from_cash(rig):
    eng, svc = rig
    pid = _sim_pid(eng)
    q = await _quote(eng, "SPA")
    p = await svc.create_plan("ant", [
        {"portfolioId": pid, "symbol": "SPA", "side": "SELL", "qty": 1, "trigger": "at", "notBefore": "15:00"},
        {"portfolioId": pid, "symbol": "SPB", "side": "BUY", "spendAll": True, "slippagePct": 2}])
    await svc.arm_plan(p["planId"], p["armConfirm"])
    buy = next(o for o in p["orders"] if o["side"] == "BUY")
    await _quote(eng, "SPB")
    await svc.tick(now=OPEN_NOW)
    assert "sells" in ((await svc.get(buy["id"]))["lastError"] or "")       # the sell (no shares) is still open
    sell = next(o for o in p["orders"] if o["side"] == "SELL")
    await svc._update(sell["id"], status="failed")
    row = await svc._load(buy["id"])
    limit = round(eng.quotes.get("SPB").ask * 1.02, 2)
    qty, _ = svc._cash_qty(row, limit)
    cash = float(eng.positions.portfolio(pid)["cash"])
    assert qty == math.floor(cash * 0.97 / limit) and qty >= 1
    assert q.ask > 0


async def test_spend_all_needs_a_live_fx_rate_across_currencies(rig, monkeypatch):
    eng, svc = rig
    pid = _sim_pid(eng)
    d = await svc.create({"portfolioId": pid, "symbol": "SPC", "side": "BUY", "spendAll": True})
    row = await svc._load(d["id"])
    pf = dict(eng.positions.portfolio(pid)); pf["baseCurrency"] = "CAD"
    monkeypatch.setattr(eng.positions, "portfolio", lambda _pid: pf)
    monkeypatch.setattr(eng.positions.fx, "rate", lambda a, b, **k: None)
    qty, why = svc._cash_qty(row, 10.0)
    assert qty is None and "rate" in why
    monkeypatch.setattr(eng.positions.fx, "rate", lambda a, b, **k: 0.7)       # CAD -> USD
    qty, _ = svc._cash_qty(row, 10.0)
    assert qty == math.floor(float(pf["cash"]) * 0.7 * 0.97 / 10.0)


async def test_spend_all_is_for_buys_without_a_qty(rig):
    eng, svc = rig
    pid = _sim_pid(eng)
    with pytest.raises(ValueError, match="for buys"):
        await svc.create({"portfolioId": pid, "symbol": "SPD", "side": "SELL", "qty": 1, "spendAll": True})
    with pytest.raises(ValueError, match="no qty"):
        await svc.create({"portfolioId": pid, "symbol": "SPD", "side": "BUY", "qty": 1, "spendAll": True})
    d = await svc.create({"portfolioId": pid, "symbol": "SPD", "side": "BUY", "spendAll": True, "budget": 500})
    assert d["spendAll"] is True and d["budget"] == 500


async def test_a_per_book_position_cap_beats_the_global_one(rig):
    eng, svc = rig
    pid = _sim_pid(eng)
    await _quote(eng, "CAPX")
    eq = float(await eng.positions.equity(pid))
    px = eng.quotes.get("CAPX").ask
    qty = max(1, int(eq * 0.6 / px))                          # ~60% of the book
    await eng.settings.set_many({"risk.max_position_pct": 50.0, "risk.max_position_notional": 10_000_000.0,
                               "risk.max_gross_exposure_pct": 1000.0, "risk.sim_require_cash": False})
    from zargar.orders import OrderIntent
    intent = lambda: OrderIntent(portfolio_id=pid, symbol="CAPX", sec_type="STK", side="BUY", qty=qty,
                                 order_type="LMT", limit_price=round(px * 1.01, 2), tif="DAY", dry_run=True)
    res = await eng.orders.place(intent())
    assert any(c["name"] == "max_position_pct" and not c["passed"] for c in res["risk"]["checks"])
    await eng.settings.set_many({"risk.max_position_pct_by_portfolio": {pid: 100.0}})
    res = await eng.orders.place(intent())
    assert all(c["passed"] for c in res["risk"]["checks"] if c["name"] == "max_position_pct")


async def test_an_order_with_a_start_date_waits_for_that_day(rig):
    """2026-11-17: the ANT plan is armed two days ahead - its 'now' sells must not fire on the day in between."""
    eng, svc = rig
    await _quote(eng, "SOD")
    d = await svc.create({"portfolioId": _sim_pid(eng), "symbol": "SOD", "side": "BUY", "qty": 1, "slippagePct": 2,
                          "startsOn": "2026-11-12", "expiresOn": "2099-01-01"})
    await svc.arm(d["id"], confirm_phrase(d["id"]))
    await svc.tick(now=OPEN_NOW)                                   # 2026-11-10, two days early
    r = await svc.get(d["id"])
    assert r["status"] == "armed" and r["lastError"] == "waiting for 2026-11-12" and r["startsOn"] == "2026-11-12"
    with pytest.raises(ValueError, match="after expiresOn"):
        await svc.create({"portfolioId": _sim_pid(eng), "symbol": "SOD", "side": "BUY", "qty": 1,
                          "startsOn": "2026-11-13", "expiresOn": "2026-11-12"})


def test_the_api_spec_carries_spend_all_and_starts_on():
    from zargar.api.routes_standing import StandingOrderSpec, _spec
    s = _spec(StandingOrderSpec(portfolioId="p", symbol="ANT", side="BUY", spendAll=True, startsOn="2026-11-19"))
    assert s["spendAll"] is True and s["startsOn"] == "2026-11-19"


async def test_the_tick_resubscribes_armed_symbols_after_a_restart(rig, monkeypatch):
    """2026-11-19: after a restart only arm() had subscribed - the ANT buys read "no quote yet" until a manual
    preflight. The tick now ensures every open order's symbol once per process."""
    eng, svc = rig
    d = await svc.create({"portfolioId": _sim_pid(eng), "symbol": "RSUB", "side": "BUY", "qty": 1})
    await svc.arm(d["id"], confirm_phrase(d["id"]))
    seen = []
    real = eng.ensure_symbol

    async def spy(sym):
        seen.append(sym)
        return await real(sym)
    monkeypatch.setattr(eng, "ensure_symbol", spy)
    fresh = StandingOrderService(eng)                    # a new process: nothing watched yet
    fresh.start = lambda: None
    await fresh.tick(now=OPEN_NOW)
    await fresh.tick(now=OPEN_NOW)
    assert seen.count("RSUB") == 1
