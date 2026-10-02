"""IBKR adapter (real-money hardening, 2026-10-02) against a fake gateway, plus the Tips live-book rules."""
import asyncio
from types import SimpleNamespace as NS

import pytest

from zargar.brokers import ibkr as ib_mod
from zargar.brokers.base import BrokerOrder
from zargar.domain import OrderSide, OrderType, TimeInForce


class Ev:
    def __init__(self):
        self.h = []

    def __iadd__(self, f):
        self.h.append(f)
        return self

    def emit(self, *a):
        for f in self.h:
            f(*a)


class FakeIB:
    def __init__(self, executions=None, open_trades=None):
        self.orderStatusEvent, self.execDetailsEvent = Ev(), Ev()
        self.commissionReportEvent, self.errorEvent, self.disconnectedEvent = Ev(), Ev(), Ev()
        self.pendingTickersEvent = Ev()
        self._connected = False
        self.placed, self.cancelled = [], []
        self._executions = executions or []
        self._open = open_trades or []
        self._next_id = 100

    async def connectAsync(self, host, port, clientId=None, timeout=None):
        self._connected = True

    def isConnected(self):
        return self._connected

    def disconnect(self):
        self._connected = False

    def managedAccounts(self):
        return ["DU123"]

    def reqMarketDataType(self, t):
        pass

    async def qualifyContractsAsync(self, c):
        return [c]

    def placeOrder(self, contract, order):
        self._next_id += 1
        order.orderId = self._next_id
        t = NS(order=order, contract=contract, orderStatus=NS(status="Submitted"), log=[])
        self.placed.append(t)
        return t

    def cancelOrder(self, order):
        self.cancelled.append(order.orderRef)

    def openTrades(self):
        return list(self._open)

    async def reqExecutionsAsync(self, execFilter=None):
        return list(self._executions)

    async def accountSummaryAsync(self, account=""):
        return [NS(account="DU123", tag="CashBalance", value="3000.50", currency="USD"),
                NS(account="DU123", tag="CashBalance", value="100", currency="CAD"),
                NS(account="DU123", tag="CashBalance", value="3070", currency="BASE"),
                NS(account="DU123", tag="SettledCash", value="2900", currency="USD")]

    def positions(self):
        return [NS(contract=NS(secType="STK", symbol="KWEB", primaryExchange="ARCA", currency="USD"),
                   position=80.0, avgCost=24.74),
                NS(contract=NS(secType="OPT", symbol="KWEB", primaryExchange="", currency="USD"),
                   position=1.0, avgCost=50.0)]


def _fill(exec_id, qty=10, price=100.0, ref="o1", commission=None):
    rep = NS(execId=exec_id if commission is not None else "", commission=commission if commission is not None else 0.0)
    return NS(execution=NS(execId=exec_id, shares=qty, price=price, orderRef=ref, acctNumber="DU123"),
              commissionReport=rep)


async def _broker(fake, seen=None):
    reports = []
    b = ib_mod.IBKRBroker("127.0.0.1", 4002, 17, on_quote=lambda q: None, ib_factory=lambda: fake,
                          exec_seen=(seen or (lambda x: _false())))

    async def on_report(r):
        reports.append(r)
    b.on_report = on_report
    await b.start()
    return b, reports


async def _false():
    return False


def _order(oid="o1", sec="STK", side=OrderSide.BUY, ot=OrderType.LMT):
    return BrokerOrder(id=oid, symbol="KWEB", sec_type=sec, side=side, qty=10, order_type=ot,
                       limit_price=24.7, stop_price=None, tif=TimeInForce.DAY)


async def test_shares_are_routed_and_options_or_a_dead_gateway_are_refused():
    fake = FakeIB()
    b, rep = await _broker(fake)
    await b.submit(_order())
    assert rep[-1].kind == "accepted" and fake.placed[-1].order.orderRef == "o1"
    assert fake.placed[-1].order.outsideRth is False
    await b.submit(_order("o2", sec="OPT"))
    assert rep[-1].kind == "rejected" and "shares only" in rep[-1].reason
    fake.disconnect()
    await b.submit(_order("o3"))
    assert rep[-1].kind == "rejected" and "not connected" in rep[-1].reason
    await b.stop()


async def test_a_fill_carries_its_commission_and_is_applied_once():
    fake = FakeIB()
    b, rep = await _broker(fake)
    await b.submit(_order())
    trade = fake.placed[-1]
    f = _fill("X1")
    fake.execDetailsEvent.emit(trade, f)
    await asyncio.sleep(0)
    assert not [r for r in rep if r.kind == "fill"]               # waits for the commission report
    f2 = _fill("X1", commission=1.05)
    fake.commissionReportEvent.emit(trade, f2, f2.commissionReport)
    await asyncio.sleep(0.01)
    fills = [r for r in rep if r.kind == "fill"]
    assert len(fills) == 1 and fills[0].exec_id == "ibkr:X1" and fills[0].commission == 1.05
    fake.commissionReportEvent.emit(trade, f2, f2.commissionReport)   # re-delivered
    fake.execDetailsEvent.emit(trade, f2)
    await asyncio.sleep(0.01)
    assert len([r for r in rep if r.kind == "fill"]) == 1
    await b.stop()


async def test_a_fill_without_a_commission_report_is_still_applied(monkeypatch):
    monkeypatch.setattr(ib_mod, "COMMISSION_WAIT_S", 0.01)
    fake = FakeIB()
    b, rep = await _broker(fake)
    await b.submit(_order())
    fake.execDetailsEvent.emit(fake.placed[-1], _fill("X2"))
    await asyncio.sleep(0.05)
    fills = [r for r in rep if r.kind == "fill"]
    assert len(fills) == 1 and fills[0].evidence.get("commission") == "unknown"
    await b.stop()


async def test_catch_up_replays_only_unseen_executions_and_never_drops_one_without_a_receiver():
    done = {"ibkr:OLD"}

    async def seen(x):
        return x in done
    fake = FakeIB(executions=[_fill("OLD", commission=1.0), _fill("NEW", commission=1.0, ref="o9")],
                  open_trades=[NS(order=NS(orderRef="o9", orderId=7), orderStatus=NS(status="Submitted"), log=[])])
    b = ib_mod.IBKRBroker("h", 1, 1, on_quote=lambda q: None, ib_factory=lambda: fake, exec_seen=seen)
    await b.start()                                       # no receiver yet: nothing is marked
    rep = []

    async def on_report(r):
        rep.append(r)
    b.on_report = on_report
    out = await b.catch_up()
    assert out == {"openOrders": 1, "replayed": 1}
    assert [r.exec_id for r in rep] == ["ibkr:NEW"] and rep[0].evidence.get("replayed")
    assert await b.cancel("o9") is True and fake.cancelled == ["o9"]   # an order found again by its orderRef
    await b.stop()


async def test_cancel_versus_venue_rejection():
    fake = FakeIB()
    b, rep = await _broker(fake)
    await b.submit(_order("a"))
    await b.submit(_order("b"))
    ta, tb = fake.placed[-2], fake.placed[-1]
    await b.cancel("a")
    ta.orderStatus.status = "Cancelled"
    fake.orderStatusEvent.emit(ta)
    tb.log.append(NS(errorCode=201, message="Order rejected - reason: insufficient funds"))
    tb.orderStatus.status = "Cancelled"
    fake.orderStatusEvent.emit(tb)
    await asyncio.sleep(0.01)
    kinds = {r.order_id: (r.kind, r.reason) for r in rep if r.kind in ("cancelled", "rejected")}
    assert kinds["a"][0] == "cancelled"
    assert kinds["b"][0] == "rejected" and "201" in kinds["b"][1] and "insufficient" in kinds["b"][1]
    await b.stop()


async def test_a_warning_never_rejects_a_working_order():
    fake = FakeIB()
    b, rep = await _broker(fake)
    await b.submit(_order("w"))
    t = fake.placed[-1]
    fake.errorEvent.emit(t.order.orderId, 399, "Order will be placed at the open", None)
    t.orderStatus.status = "ValidationError"
    fake.orderStatusEvent.emit(t)
    await asyncio.sleep(0.01)
    assert [r.kind for r in rep if r.order_id == "w"] == ["accepted"]
    await b.stop()


async def test_account_state_reads_usd_cash_and_stock_positions_only():
    fake = FakeIB()
    b, _ = await _broker(fake)
    st = await b.account_state(cash_currency="USD")
    assert st["cash"] == 3000.50 and st["settledCash"] == 2900.0 and st["cashByCurrency"]["CAD"] == 100.0
    assert st["positions"] == [{"symbol": "KWEB", "secType": "STK", "qty": 80.0, "avgCost": 24.74, "currency": "USD"}]
    await b.stop()


class _S(dict):
    def get(self, k, d=None):
        return super().get(k, d)


def test_tips_live_book_rules():
    from zargar.approvals.proposals import live_capital_room, live_vehicle_refusal, policy_kind, shares_first_applies
    on = _S({"techniques.tip.live_parity": True})
    ibkr_live = {"kind": "live", "venue": "ibkr"}
    assert policy_kind(on, ibkr_live) == "sim"
    assert policy_kind(on, {"kind": "live", "venue": "snaptrade"}) == "live"     # Wealthsimple/Webull never
    assert policy_kind(_S({}), ibkr_live) == "live"                              # parity off: Practice-only stays
    assert shares_first_applies("shares", direction="long", lotto=False, portfolio_kind=policy_kind(on, ibkr_live))
    assert live_vehicle_refusal(_S({}), ibkr_live, "OPT") and live_vehicle_refusal(_S({}), ibkr_live, "SPREAD")
    assert live_vehicle_refusal(_S({}), ibkr_live, "STK") is None
    assert live_vehicle_refusal(_S({}), {"kind": "sim"}, "OPT") is None
    assert live_capital_room(3000, 2500) == 500 and live_capital_room(3000, 3200) == 0 and live_capital_room(0, 10) is None
