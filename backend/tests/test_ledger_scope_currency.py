"""2026-10-05 (user): the live ledger summed a C$ real account with a US$ IBKR paper book into one "brokerage total".
Real money and paper are now separate scopes, and every amount is in one requested currency."""
import uuid

import pytest

from zargar.desk import attach_desk
from zargar.engine import Engine
from zargar.models import Portfolio
from zargar.signals.service import attach_signal_layer

from .conftest import make_test_config


@pytest.fixture
async def rig(fresh_db):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    attach_desk(eng)
    yield eng
    await eng.stop()


async def _book(eng, *, name, kind, ccy, cash):
    p = Portfolio(id=uuid.uuid4().hex, name=name, kind=kind, base_currency=ccy, starting_cash=0.0, cash=cash)
    async with eng.sf() as s:
        s.add(p)
        await s.commit()
    eng.positions.register_portfolio(p)
    return p.id


async def test_real_and_paper_are_never_summed_and_amounts_follow_the_currency(rig, monkeypatch):
    await _book(rig, name="Real CAD", kind="live", ccy="CAD", cash=1000.0)
    await _book(rig, name="IBKR Paper", kind="paper", ccy="USD", cash=700.0)
    monkeypatch.setattr(rig.positions.fx, "rate",
                        lambda a, b, **k: {("USD", "CAD"): 1.4, ("CAD", "USD"): 1 / 1.4}.get((a, b)))

    real = await rig.desk.ledger(workspace="live", currency="CAD")
    assert real["scope"] == "real" and real["currency"] == "CAD"
    assert "IBKR Paper" not in real["books"] and "Real CAD" in real["books"]
    assert abs(real["total"] - 1000.0) < 0.01, real["total"]
    assert real["hasPaper"] is True

    paper = await rig.desk.ledger(workspace="live", scope="paper", currency="CAD")
    assert paper["scope"] == "paper" and paper["books"] == ["IBKR Paper"]
    assert abs(paper["total"] - 980.0) < 0.01, paper["total"]          # US$700 at 1.4

    paper_usd = await rig.desk.ledger(workspace="live", scope="paper", currency="USD")
    assert abs(paper_usd["total"] - 700.0) < 0.01


async def test_practice_scope_is_unchanged(rig):
    led = await rig.desk.ledger(workspace="practice")
    assert led["scope"] == "practice" and led["workspace"] == "practice"
