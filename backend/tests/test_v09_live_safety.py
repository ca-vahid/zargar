"""Tips v0.9 workstream V1 - live safety (2026-10-05; plan docs/techniques/tip/research/2026-10-04-v09/PLAN.md, findings
R1-money-path.md). V1.1 armed fires size through the bound book; V1.2 catch-up before the account sync; V1.3 cash lag
after a buy; V1.4 a partial entry is protected at once; V1.5 a failed hand-off marks the card failed; V1.6 the cancel /
replace race on real books; V1.7 the good-faith guard. No LLM calls."""
from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import select

from zargar.brokers import ibkr as ib_mod
from zargar.engine import Engine
from zargar.execution import goodfaith as gf
from zargar.execution.positions import PositionManager
from zargar.models import Event, Execution, Order, Portfolio, Proposal
from zargar.orders import SubmitUncertain
from zargar.signals.service import attach_signal_layer

from .conftest import make_test_config, wait_for
from .test_ibkr_adapter import FakeIB, _fill
from .test_tip_runner import _ingest_tip, _quote, tip_rig  # noqa: F401  (fixture)


@pytest.fixture
async def eng(fresh_db):
    e = Engine(make_test_config())
    await e.start()
    await attach_signal_layer(e)
    try:
        yield e
    finally:
        e.ibkr = None
        await e.stop()


async def _book(e, kind="paper", cash=7_000.0) -> str:
    p = Portfolio(id=uuid.uuid4().hex, name=f"T {kind} {uuid.uuid4().hex[:4]}", kind=kind, starting_cash=cash,
                  cash=cash)
    async with e.sf() as s:
        s.add(p)
        await s.commit()
    e.positions.register_portfolio(p)
    return p.id


async def _events(e, kind: str) -> list[dict]:
    async with e.sf() as s:
        return list((await s.execute(select(Event.payload).where(Event.type == kind))).scalars().all())


# ================================================================== V1.1 armed fires use the book's sizing
async def test_base_hook_keeps_other_desks_sizing():
    from zargar.execution.planrunner import PlanRunner
    assert await PlanRunner.size_entry_shares(None, NS(), NS(), 7.0, 10.0) == (7.0, None)


async def test_armed_fire_on_a_bound_live_book_sizes_through_the_book(eng):
    from zargar.techniques.tip.runner import TipRunner
    pid = await _book(eng, "paper", 7_000.0)
    await eng.settings.set("techniques.tip.books", [
        {"portfolioId": pid, "role": "live", "budgetPerTip": 500, "capitalCap": 3000, "maxOpenPositions": 3,
         "riskPct": 1.0, "armAtLevel": True}], journal=False)
    r = TipRunner(eng)
    try:
        ap = NS(config=NS(portfolio_id=pid), plan={"context": {"source": "TestRoom"}}, run_id="no-run", symbol="XYZ")
        # budget $500 at $100 -> 5 sh; risk 1% of $7,000 = $70 over a $2 stop -> 35: the budget binds
        q, why = await r.size_entry_shares(ap, NS(stop=98.0, trigger_id="t1"), 100.0, 100.0)
        assert q == 5 and why
        # a $20 stop: $70 / $20 -> 3 shares (the book's risk %, never the source's budget)
        q, _ = await r.size_entry_shares(ap, NS(stop=80.0, trigger_id="t1"), 100.0, 100.0)
        assert q == 3
        # no stop below the entry: nothing to size the risk against -> refused (live books always risk-size)
        q, why = await r.size_entry_shares(ap, NS(stop=None, trigger_id="t1"), 100.0, 100.0)
        assert q == 0 and "stop" in why
        # a resting entry order of $2,600 is already committed: $400 left under the $3,000 cap -> 4 sh
        async with eng.sf() as s:
            s.add(Order(id=uuid.uuid4().hex, portfolio_id=pid, symbol="ABC", sec_type="STK", side="BUY", qty=26,
                        order_type="LMT", limit_price=100.0, status="ACCEPTED", filled_qty=0, source="technique"))
            await s.commit()
        q, _ = await r.size_entry_shares(ap, NS(stop=98.0, trigger_id="t1"), 100.0, 100.0)
        assert q == 4
        async with eng.sf() as s:
            s.add(Order(id=uuid.uuid4().hex, portfolio_id=pid, symbol="DEF", sec_type="STK", side="BUY", qty=4,
                        order_type="LMT", limit_price=95.0, status="ACCEPTED", filled_qty=0, source="technique"))
            await s.commit()
        q, why = await r.size_entry_shares(ap, NS(stop=98.0, trigger_id="t1"), 100.0, 100.0)
        assert q == 0 and "capital cap" in why
        assert await _events(eng, "TipArmedFireSized")
    finally:
        await r.stop()


async def test_armed_fire_on_a_bound_practice_book_takes_the_book_budget(tip_rig):  # noqa: F811
    """End to end through the PlanRunner: the fired entry's quantity comes from the bound book's budget."""
    from zargar.domain import Bar
    from zargar.marketstructure.sessions import ET as REAL_ET
    eng, sim = tip_rig
    await eng.settings.set("techniques.tip.books", [
        {"portfolioId": sim["id"], "role": "practice", "primary": True, "budgetPerTip": 300}], journal=False)
    sid = await _ingest_tip(eng)
    snap = await eng.tip_runner.arm_signal(sid, {"portfolioId": sim["id"], "mode": "auto", "instrument": "shares",
                                                 "qty": 5, "dailyLossLimit": 200.0})
    run_id = snap["runId"]
    await _quote(eng, 99.6)
    y, m, d = (int(x) for x in snap["planFor"].split("-"))
    ts0 = int(dt.datetime(y, m, d, 10, 0, tzinfo=REAL_ET).timestamp() * 1000)
    if snap.get("lastBarTs"):
        ts0 = max(ts0, int(snap["lastBarTs"]) + 60_000)
    await eng.tip_runner.on_bar(run_id, Bar(symbol="TEST", tf="1m", ts=ts0, open=100.0, high=100.2, low=99.8,
                                            close=100.0, volume=0))
    await _quote(eng, 99.5)
    s2 = await eng.tip_runner.on_bar(run_id, Bar(symbol="TEST", tf="1m", ts=ts0 + 60_000, open=99.8, high=99.9,
                                                 low=99.4, close=99.6, volume=0))
    trade = s2["trades"][0]
    assert trade["entryOrderId"], trade
    async with eng.sf() as s:
        order = await s.get(Order, trade["entryOrderId"])
    assert order.qty == 3, "a $300 book budget at ~$99.6 buys 3 shares, not the arm's 5"


# ================================================================== V1.2 catch-up before the sync
async def test_reconnect_replays_executions_before_the_account_sync():
    seq = []
    fake = FakeIB(executions=[_fill("X1", commission=1.0, ref="o1")])
    b = None

    async def on_state(kind, data):
        seq.append(("state", kind, b.caught_up))

    async def seen(x):
        return False
    b = ib_mod.IBKRBroker("h", 1, 1, on_quote=lambda q: None, ib_factory=lambda: fake, exec_seen=seen,
                          on_state=on_state)

    async def on_report(r):
        seq.append(("fill", r.exec_id, b.caught_up))
    b.on_report = on_report
    await b.start()
    kinds = [x[:2] for x in seq]
    assert kinds.index(("state", "connected")) < kinds.index(("fill", "ibkr:X1")) < kinds.index(("state", "ready"))
    assert seq[kinds.index(("state", "connected"))][2] is False and seq[-1] == ("state", "ready", True)
    b._stopping = True
    b._on_disconnected()
    assert b.caught_up is False
    await b.stop()


async def test_the_sync_waits_for_the_catch_up(eng):
    pid = await _book(eng, "paper", 1_000.0)
    await eng.settings.set("ibkr.portfolio_id", pid, journal=False)
    calls = []

    async def account_state(cash_currency="USD"):
        calls.append(1)
        return {"account": "DU1", "cash": 2000.0, "settledCash": None, "cashByCurrency": {"USD": 2000.0},
                "positions": []}
    eng.ibkr = NS(connected=True, caught_up=False, account_state=account_state)
    assert await eng.sync_ibkr_account() is None and not calls
    eng.ibkr.caught_up = True
    assert (await eng.sync_ibkr_account())["spendable"] == 2000.0


# ================================================================== V1.3 cash lag after a buy
async def test_a_buy_the_summary_has_not_seen_is_not_spendable(eng):
    pid = await _book(eng, "paper", 7_000.0)
    await eng.settings.set("ibkr.portfolio_id", pid, journal=False)
    state = {"cash": 7000.0}

    async def account_state(cash_currency="USD"):
        return {"account": "DU1", "cash": state["cash"], "settledCash": None,
                "cashByCurrency": {"USD": state["cash"]}, "positions": []}
    eng.ibkr = NS(connected=True, caught_up=True, account_state=account_state)
    assert (await eng.sync_ibkr_account())["spendable"] == 7000.0
    oid = uuid.uuid4().hex
    async with eng.sf() as s:
        s.add(Order(id=oid, portfolio_id=pid, symbol="XYZ", sec_type="STK", side="BUY", qty=10, order_type="LMT",
                    limit_price=100.0, status="FILLED", filled_qty=10, source="signal"))
        await s.flush()
        s.add(Execution(id=f"ibkr:{oid[:8]}", order_id=oid, portfolio_id=pid, symbol="XYZ", side="BUY", qty=10,
                        price=100.0, commission=1.0))
        await s.commit()
    # the summary still shows the pre-buy $7,000: the $1,001 buy is taken out
    st = await eng.sync_ibkr_account()
    assert st["spendable"] == pytest.approx(5999.0) and st["unreflectedBuys"] == pytest.approx(1001.0)
    assert eng.positions.portfolio(pid)["cash"] == pytest.approx(5999.0)
    # the summary moved (it now contains the buy): no double subtraction
    state["cash"] = 5999.0
    st = await eng.sync_ibkr_account()
    assert st["spendable"] == pytest.approx(5999.0) and not st.get("unreflectedBuys")


# ================================================================== V1.4 a partial entry is protected at once
async def test_a_partial_entry_is_adopted_at_once_and_grows(tip_rig, monkeypatch):  # noqa: F811
    import zargar.techniques.tip.lifecycle as lc
    eng, sim = tip_rig
    monkeypatch.setattr(lc, "POLL_S", 0.05)
    oid = uuid.uuid4().hex
    async with eng.sf() as s:
        s.add(Order(id=oid, portfolio_id=sim["id"], symbol="TEST", sec_type="STK", side="BUY", qty=5.0,
                    order_type="LMT", status="PARTIALLY_FILLED", filled_qty=2.0, avg_fill_price=99.5))
        await s.commit()
    proposal = {"id": uuid.uuid4().hex, "portfolioId": sim["id"], "symbol": "TEST", "secType": "STK", "qty": 5.0,
                "limitPrice": 99.5,
                "context": {"techniqueId": "tip", "sourceName": "TestRoom", "vehicle": {"kind": "shares"},
                            "signalPrices": {"entry": 99.5, "stop": 98.0},
                            "exitPlan": {"targets": [103.0], "underlyingStop": 98.0, "maxHoldSessions": 5}}}
    task = asyncio.create_task(lc.adopt_when_filled(eng, proposal, {"id": oid}))
    mgr = eng.position_manager

    def mine():
        for p in mgr.positions():
            if any(l.get("entryOrderId") == oid for l in p.get("legs") or []):
                return p
        return None
    pos = await wait_for(mine, timeout=10)
    assert sum(l["qty"] for l in pos["legs"]) == 2.0 and not task.done(), "adopted while the remainder rests"
    p = await wait_for(lambda: (mgr.get(pos["id"]) if mgr.get(pos["id"]) is not None
                                and mgr.get(pos["id"]).venue_stop_order_id else None), timeout=10)
    assert float(p.venue_stop_qty) == 2.0 and not task.done(), "the filled part has its venue stop now"
    async with eng.sf() as s:
        o = await s.get(Order, oid)
        o.filled_qty, o.avg_fill_price, o.status = 5.0, 99.6, "FILLED"
        await s.commit()
    out = await asyncio.wait_for(task, timeout=10)
    assert out["id"] == pos["id"]
    p = mgr.get(pos["id"])
    assert sum(abs(l.qty) for l in p.legs) == 5.0 and len(p.legs) == 1
    assert float(p.venue_stop_qty) == 5.0, "the venue stop follows the grown quantity"
    assert await _events(eng, "TipPartialFillAdopted") and await _events(eng, "TipPartialFillGrown")


# ================================================================== V1.5 a failed hand-off marks the card failed
async def _pending_proposal(e, pid, *, tip=False) -> str:
    prop_id = uuid.uuid4().hex
    async with e.sf() as s:
        s.add(Proposal(id=prop_id, portfolio_id=pid, symbol="AAPL", sec_type="STK", side="BUY", qty=1.0,
                       order_type="LMT", limit_price=100.0, status="pending",
                       context=({"techniqueId": "tip", "vehicle": {"kind": "shares", "underlying": "AAPL"}}
                                if tip else {}),
                       expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)))
        await s.commit()
    return prop_id


@pytest.mark.parametrize("uncertain", [True, False])
async def test_a_failed_venue_handoff_marks_the_proposal_failed(eng, monkeypatch, uncertain):
    pid = next(p for p in eng.positions.portfolios() if p["kind"] == "sim")["id"]
    prop_id = await _pending_proposal(eng, pid)

    async def boom(intent, **kw):
        if uncertain:
            raise SubmitUncertain("ord-lost", ConnectionError("Not connected"))
        raise RuntimeError("gateway gone")
    monkeypatch.setattr(eng.orders, "place", boom)
    out = await eng.proposals.approve(prop_id, via="app")
    assert out["proposal"]["status"] == "failed"
    async with eng.sf() as s:
        row = await s.get(Proposal, prop_id)
    assert row.status == "failed" and row.context["handoff"]["uncertain"] is uncertain
    assert row.order_id == ("ord-lost" if uncertain else None)
    ev = await _events(eng, "ProposalHandoffFailed")
    assert ev and ev[-1]["uncertain"] is uncertain
    with pytest.raises(ValueError):
        await eng.proposals.approve(prop_id, via="app")       # never approvable twice


async def test_an_uncertain_tip_handoff_keeps_watching_for_the_fill(eng):
    pid = next(p for p in eng.positions.portfolios() if p["kind"] == "sim")["id"]
    prop_id = await _pending_proposal(eng, pid, tip=True)
    async with eng.sf() as s:
        from zargar.approvals.proposals import proposal_dict
        pdict = proposal_dict(await s.get(Proposal, prop_id))
    out = await eng.proposals._handoff_failed(prop_id, pdict, SubmitUncertain("o-x", TimeoutError()), via="auto")
    assert out["proposal"]["status"] == "failed" and out["order"]["id"] == "o-x"
    t = eng.proposals._adopt_tasks.get(prop_id)
    assert t is not None, "a fill the venue did take is still adopted and protected"
    t.cancel()


# ================================================================== V1.6 / V1.7 real-book exits
class DbOrders:
    """Order layer for a paper book: every placed order is a DB row (the venue's view); cancels confirm only when
    told to (IBKR confirms asynchronously)."""

    def __init__(self, eng, pid):
        self.eng, self.pid = eng, pid
        self.placed: list = []
        self.cancelled: list[str] = []
        self.confirm = True
        self.fill_on_cancel = False

    async def place(self, intent, **kw):
        oid = uuid.uuid4().hex
        async with self.eng.sf() as s:
            s.add(Order(id=oid, portfolio_id=intent.portfolio_id, symbol=intent.symbol, sec_type=intent.sec_type,
                        side=intent.side, qty=intent.qty, order_type=intent.order_type,
                        limit_price=intent.limit_price, stop_price=intent.stop_price, status="ACCEPTED",
                        filled_qty=0, source="technique"))
            await s.commit()
        self.placed.append(intent)
        return {"id": oid, "status": "ACCEPTED", "symbol": intent.symbol, "filledQty": 0.0}

    async def cancel(self, order_id):
        self.cancelled.append(order_id)
        if self.confirm or self.fill_on_cancel:
            async with self.eng.sf() as s:
                o = await s.get(Order, order_id)
                if o is not None:
                    o.status = "FILLED" if self.fill_on_cancel else "CANCELLED"
                    if self.fill_on_cancel:
                        o.filled_qty = o.qty
                    await s.commit()
        return {"id": order_id}

    async def set_status(self, order_id, status):
        async with self.eng.sf() as s:
            o = await s.get(Order, order_id)
            o.status = status
            await s.commit()


def _spec(pid, qty=10, entry_order=None):
    return {"portfolioId": pid, "symbol": "AAPL", "direction": "long", "techniqueId": "tip", "entry": 100.0,
            "risk": 2.0, "overnight": "venue_stop",
            "policy": {"timeframe": "5m", "stop": {"kind": "fixed", "price": 98.0},
                       "ladder": {"targets": [104.0], "fractions": [0.5]}},
            "legs": [{"symbol": "AAPL", "secType": "STK", "qty": qty, "avgFill": 100.0,
                      **({"entryOrderId": entry_order} if entry_order else {})}]}


async def _real_rig(eng, cash=7_000.0):
    pid = await _book(eng, "paper", cash)
    fo = DbOrders(eng, pid)
    eng.orders = fo
    pm = PositionManager(eng)
    await eng.settings.set("execution.cancel_confirm_seconds", 0.3, journal=False)
    return pid, fo, pm


async def test_a_replacement_stop_waits_for_the_cancel_confirmation(eng):
    pid, fo, pm = await _real_rig(eng)
    d = await pm.adopt(_spec(pid))
    p = pm.get(d["id"])
    s1 = p.venue_stop_order_id
    assert s1 and len(fo.placed) == 1
    fo.confirm = False
    p.state = replace(p.state, stop=99.0)
    await pm._ensure_venue_stop(p)
    assert len(fo.placed) == 1, "no second sell rests while the first one's cancel is unconfirmed"
    assert p.id in pm._stop_replace_pending
    await pm._ensure_venue_stop(p)
    assert len(fo.placed) == 1
    await fo.set_status(s1, "CANCELLED")                    # the venue confirms
    await pm.on_order_update({"id": s1, "status": "CANCELLED", "symbol": "AAPL", "filledQty": 0})
    assert len(fo.placed) == 2 and fo.placed[-1].qty == 10 and fo.placed[-1].stop_price == 99.0
    assert p.id not in pm._stop_replace_pending
    await pm.stop()


async def test_a_stop_that_fills_during_the_replace_is_booked_not_doubled(eng):
    pid, fo, pm = await _real_rig(eng)
    d = await pm.adopt(_spec(pid))
    p = pm.get(d["id"])
    s1 = p.venue_stop_order_id
    fo.fill_on_cancel = True
    p.state = replace(p.state, stop=99.0)
    await pm._ensure_venue_stop(p)
    assert len(fo.placed) == 1, "the old stop executed - nothing new rests on top of it"
    await pm.on_order_update({"id": s1, "status": "FILLED", "symbol": "AAPL", "filledQty": 10.0,
                              "avgFillPrice": 98.0})
    assert pm.get(d["id"]) is None or pm.get(d["id"]).status == "closed", "the fill closed the position"
    await pm.stop()


async def test_a_close_never_sells_beside_an_unconfirmed_stop(eng):
    pid, fo, pm = await _real_rig(eng)
    d = await pm.adopt(_spec(pid))
    s1 = pm.get(d["id"]).venue_stop_order_id
    fo.confirm = False
    await pm.close(d["id"], fraction=1.0, reason="stop", kind="stop", force_market=True)
    assert [i.order_type for i in fo.placed] == ["STP"], "the MKT waits: the stop may still be resting"
    await fo.set_status(s1, "CANCELLED")
    await pm.close(d["id"], fraction=1.0, reason="stop", kind="stop", force_market=True)
    assert fo.placed[-1].order_type == "MKT" and fo.placed[-1].qty == 10
    await pm.stop()


# ---------------------------------------------------------------- V1.7 good faith
def test_unsettled_funded_pure():
    ex = [{"orderId": "s", "side": "SELL", "qty": 20, "price": 100.0, "ts": 1},
          {"orderId": "b", "side": "BUY", "qty": 25, "price": 100.0, "ts": 2}]
    # day started with $1,000: the $2,500 buy used $1,500 of the morning sale's (unsettled) proceeds
    assert gf.unsettled_funded(ex, cash_now=500.0) == {"b": pytest.approx(1500.0)}
    # day started with $5,000: the buy was paid from settled cash
    assert gf.unsettled_funded(ex, cash_now=4500.0) == {}
    # no sale before the buy: nothing unsettled could fund it
    assert gf.unsettled_funded([{**ex[1], "ts": 0}, {**ex[0], "ts": 5}], cash_now=500.0) == {}
    assert gf.is_protective("stop") and gf.is_protective("premium_stop") and gf.is_protective("close", "manual close")
    assert not gf.is_protective("trim") and not gf.is_protective("time") and not gf.is_protective("close", "source sold")


async def test_good_faith_defers_a_trim_but_never_a_stop(eng):
    pid, fo, pm = await _real_rig(eng, cash=500.0)
    sell_id, buy_id = uuid.uuid4().hex, uuid.uuid4().hex
    now = dt.datetime.now(dt.timezone.utc)
    async with eng.sf() as s:
        for oid, side, q in ((sell_id, "SELL", 20), (buy_id, "BUY", 25)):
            s.add(Order(id=oid, portfolio_id=pid, symbol="AAPL" if side == "BUY" else "MSFT", sec_type="STK",
                        side=side, qty=q, order_type="LMT", limit_price=100.0, status="FILLED", filled_qty=q,
                        source="signal"))
        await s.flush()
        s.add(Execution(id=f"x:{sell_id[:8]}", order_id=sell_id, portfolio_id=pid, symbol="MSFT", side="SELL",
                        qty=20, price=100.0, commission=0.0, ts=now - dt.timedelta(seconds=60)))
        s.add(Execution(id=f"x:{buy_id[:8]}", order_id=buy_id, portfolio_id=pid, symbol="AAPL", side="BUY",
                        qty=25, price=100.0, commission=0.0, ts=now - dt.timedelta(seconds=30)))
        await s.commit()
    d = await pm.adopt(_spec(pid, qty=25, entry_order=buy_id))
    n0 = len(fo.placed)
    await pm.close(d["id"], fraction=0.5, reason="TP1 104 reached", kind="trim")
    assert len(fo.placed) == n0, "the trim waits for settlement (T+1)"
    dfr = await _events(eng, "TipGoodFaithDeferred")
    assert dfr and dfr[-1]["kind"] == "trim" and dfr[-1]["unsettledFunded"] == pytest.approx(1500.0)
    await pm.close(d["id"], fraction=1.0, reason="bar closed through the stop", kind="stop", force_market=True)
    assert fo.placed[-1].side == "SELL" and fo.placed[-1].order_type == "MKT", "a protective stop always goes"
    assert await _events(eng, "TipGoodFaithStopSent")
    await pm.stop()
