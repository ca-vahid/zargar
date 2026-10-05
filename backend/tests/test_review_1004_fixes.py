"""2026-10-04 pre-live review fixes (R1 money path, R2 Tips pipeline): account-type guard, pending entry cost in the
cap, T+1 unsettled proceeds, venue stop death re-placed, a failed trim retried as a trim, per-book risk overrides,
the BMO earnings window, one share over budget refused."""
import datetime as dt
import uuid
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest

from zargar.engine import Engine
from zargar.execution.policies import earnings_exit_due
from zargar.models import Order, Portfolio
from zargar.orders import OrderIntent
from zargar.risk import BookRiskSettings

from .conftest import make_test_config

ET = ZoneInfo("America/New_York")


class S(dict):
    def get(self, k, d=None):
        return super().get(k, d)


def test_bmo_report_day_trades_after_the_open():
    t = lambda h, m: dt.datetime(2026, 10, 22, h, m, tzinfo=ET)    # noqa: E731
    assert earnings_exit_due(t(10, 30), "2026-10-22", "BMO") is None
    assert earnings_exit_due(t(15, 0), "2026-10-22", "unknown") is None
    assert earnings_exit_due(t(15, 50), "2026-10-22", "AMC")


def test_book_risk_overrides():
    s = S({"risk.max_position_notional": 25000, "risk.book_overrides": {"live1": {"risk.max_position_notional": 3500}}})
    assert BookRiskSettings(s, "live1").get("risk.max_position_notional") == 3500
    assert BookRiskSettings(s, "sim1").get("risk.max_position_notional") == 25000
    assert BookRiskSettings(s, None).get("risk.max_position_notional") == 25000


def test_ibkr_account_kind():
    from zargar.brokers.ibkr import IBKRBroker
    b = IBKRBroker("h", 1, 1, on_quote=lambda q: None)
    b._ib = NS(managedAccounts=lambda: ["DUR232647"])
    assert b.account_kind() == "paper"
    b._ib = NS(managedAccounts=lambda: ["U1234567"])
    assert b.account_kind() == "live"
    b._ib = NS(managedAccounts=lambda: [])
    assert b.account_kind() is None


@pytest.fixture
async def eng(fresh_db):
    from zargar.signals.service import attach_signal_layer
    e = Engine(make_test_config())
    await e.start()
    await attach_signal_layer(e)
    yield e
    await e.stop()


async def _book(e, kind="sim", cash=10_000.0):
    p = Portfolio(id=uuid.uuid4().hex, name=f"T {kind}", kind=kind, starting_cash=cash, cash=cash)
    async with e.sf() as s:
        s.add(p)
        await s.commit()
    e.positions.register_portfolio(p)
    return p.id


async def test_a_paper_book_never_routes_to_a_live_account(eng):
    pid = await _book(eng, "paper")
    await eng.settings.set("trading.mode", "live", journal=False)

    class FakeExec:
        connected = True

        def account_kind(self):
            return "live"

    eng.executor_for = lambda pf: FakeExec()           # noqa: E731
    eng.orders._executor_for = lambda pf: FakeExec()   # noqa: E731
    await eng.ensure_symbol("AAPL")
    out = await eng.orders.place(OrderIntent(portfolio_id=pid, symbol="AAPL", side="BUY", qty=1, order_type="MKT"))
    assert out["status"] in ("REJECTED", "REJECTED_RISK")
    assert "account type mismatch" in (out.get("rejectReason") or "") or out["status"] == "REJECTED_RISK"


async def test_pending_entry_orders_count_against_the_cap(eng):
    pid = await _book(eng, "sim")
    async with eng.sf() as s:
        s.add(Order(id=uuid.uuid4().hex, portfolio_id=pid, symbol="XYZ", sec_type="STK", side="BUY", qty=10,
                    order_type="LMT", limit_price=100.0, status="ACCEPTED", filled_qty=4, source="signal"))
        await s.commit()
    assert await eng.proposals._pending_entry_cost(pid) == 600.0


async def test_todays_sells_are_unsettled_when_ibkr_reports_no_settled_cash(eng):
    pid = await _book(eng, "paper")
    await eng.settings.set("ibkr.portfolio_id", pid, journal=False)
    from zargar.models import Execution
    oid = uuid.uuid4().hex
    async with eng.sf() as s:
        s.add(Order(id=oid, portfolio_id=pid, symbol="XYZ", sec_type="STK", side="SELL", qty=5,
                    order_type="MKT", status="FILLED", filled_qty=5, source="signal"))
        await s.flush()
        s.add(Execution(id="ibkr:t1", order_id=oid, portfolio_id=pid, symbol="XYZ", side="SELL", qty=5, price=100.0,
                        commission=1.0))
        await s.commit()
    eng.ibkr_synced_at = dt.datetime.now(dt.timezone.utc)      # a sync AFTER the sale...
    eng.ibkr_settled_known = False                             # ...that could not see settled cash
    pf = eng.positions.portfolio(pid)
    assert await eng.proposals._unsettled_since_sync(pid, pf) == 499.0
