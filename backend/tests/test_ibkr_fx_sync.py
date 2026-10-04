"""2026-10-04 (user): a C$10,000 IBKR paper account read as US$10,000. The sync converts every currency to the book's
currency at the live rate, never 1:1; with no rate it skips the level-set (journaled)."""
import uuid

import pytest

from zargar.engine import Engine
from zargar.models import Portfolio

from .conftest import make_test_config


class FakeIbkr:
    connected = True

    def __init__(self, st):
        self.st = st

    async def account_state(self, cash_currency="USD"):
        return dict(self.st)

    async def stop(self):
        pass


@pytest.fixture
async def eng(fresh_db):
    e = Engine(make_test_config())
    await e.start()
    yield e
    await e.stop()


async def _paper(e):
    p = Portfolio(id=uuid.uuid4().hex, name="Tips IBKR Paper", kind="paper", base_currency="USD",
                  starting_cash=0.0, cash=0.0)
    async with e.sf() as s:
        s.add(p)
        await s.commit()
    e.positions.register_portfolio(p)
    await e.settings.set("ibkr.portfolio_id", p.id, journal=False)
    await e.settings.set("ibkr.cash_currency", "CAD", journal=False)
    return p.id


async def test_cad_cash_is_converted_into_the_usd_book(eng, monkeypatch):
    pid = await _paper(eng)
    eng.ibkr = FakeIbkr({"account": "DU1", "cash": 10000.0, "settledCash": None,
                         "cashByCurrency": {"CAD": 10000.0, "USD": -2.0}, "positions": []})
    monkeypatch.setattr(eng.positions.fx, "rate", lambda a, b: 0.72 if (a, b) == ("CAD", "USD") else None)
    st = await eng.sync_ibkr_account()
    assert st is not None and abs(st["spendable"] - (7200.0 - 2.0)) < 0.01
    assert abs(eng.positions.portfolio(pid)["cash"] - 7198.0) < 0.01


async def test_no_rate_means_no_level_set(eng, monkeypatch):
    pid = await _paper(eng)
    eng.ibkr = FakeIbkr({"account": "DU1", "cash": 10000.0, "settledCash": None,
                         "cashByCurrency": {"CAD": 10000.0}, "positions": []})
    monkeypatch.setattr(eng.positions.fx, "rate", lambda a, b: None)
    assert await eng.sync_ibkr_account() is None
    assert eng.positions.portfolio(pid)["cash"] == 0.0, "never a 1:1 conversion"
