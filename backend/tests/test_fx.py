"""FX correctness: symbol currencies, rate lookup, converted equity, mismatch."""
import pytest

from zargar.bus import Bus
from zargar.db import make_engine, make_session_factory
from zargar.domain import Quote, now_ms
from zargar.events import Journal
from zargar.fx import FxService, currency_for_symbol
from zargar.marketdata import QuoteCache
from zargar.models import Portfolio
from zargar.portfolio import PositionKeeper

from .conftest import TEST_DB_URL


def test_currency_for_symbol():
    assert currency_for_symbol("AAPL") == "USD"
    assert currency_for_symbol("SHOP.TO") == "CAD"
    assert currency_for_symbol("msft.to") == "CAD"
    assert currency_for_symbol("XYZ.V") == "CAD"
    assert currency_for_symbol("TQQQ") == "USD"


def test_rate_direct_inverse_and_stale():
    quotes = QuoteCache(Bus())
    fx = FxService(quotes)
    assert fx.rate("USD", "USD") == 1.0
    assert fx.rate("USD", "CAD") is None      # no data yet
    assert fx.convert(100.0, "USD", "CAD") == 100.0  # 1:1 fallback

    quotes.on_quote(Quote(symbol="USDCAD=X", bid=1.369, ask=1.371, last=1.37))
    assert fx.rate("USD", "CAD") == 1.37
    assert fx.rate("CAD", "USD") == pytest.approx(1 / 1.37)  # inverse pair
    assert fx.convert(100.0, "USD", "CAD") == pytest.approx(137.0)

    stale = Quote(symbol="USDCAD=X", bid=1.3, ask=1.31, last=1.3,
                  ts=now_ms() - 7 * 60 * 60 * 1000)
    quotes.on_quote(stale)
    assert fx.rate("USD", "CAD") is None  # too old to trust


@pytest.fixture
async def sf(fresh_db):
    engine = make_engine(TEST_DB_URL)
    yield make_session_factory(engine)
    await engine.dispose()


async def test_equity_converts_usd_positions_in_cad_account(sf):
    """The bug that started this phase: SPCX (USD) inside a CAD account."""
    bus = Bus()
    quotes = QuoteCache(bus)
    keeper = PositionKeeper(sf, bus, Journal(sf, bus), quotes)
    keeper.register_portfolio(Portfolio(
        id="cad1", name="Webull CASH", kind="live",
        base_currency="CAD", starting_cash=0.0, cash=67.31), venue="snaptrade")
    keeper._positions[("cad1", "SPCX", "STK")] = {
        "portfolioId": "cad1", "symbol": "SPCX", "secType": "STK",
        "qty": 60.0, "avgCost": 159.67, "realizedPnl": 0.0, "currency": "USD",
    }
    keeper._positions[("cad1", "AAPL.TO", "STK")] = {
        "portfolioId": "cad1", "symbol": "AAPL.TO", "secType": "STK",
        "qty": 89.0, "avgCost": 32.86, "realizedPnl": 0.0, "currency": "CAD",
    }
    quotes.on_quote(Quote(symbol="SPCX", bid=131.9, ask=132.1, last=132.0))
    quotes.on_quote(Quote(symbol="AAPL.TO", bid=44.5, ask=44.7, last=44.61))

    # without an FX rate: USD counted 1:1 (conservative fallback)
    eq_no_fx = await keeper.equity("cad1")
    assert eq_no_fx == pytest.approx(67.31 + 60 * 132.0 + 89 * 44.61, rel=1e-6)

    quotes.on_quote(Quote(symbol="USDCAD=X", bid=1.369, ask=1.371, last=1.37))
    eq_fx = await keeper.equity("cad1")
    assert eq_fx == pytest.approx(67.31 + 60 * 132.0 * 1.37 + 89 * 44.61, rel=1e-6)
    assert eq_fx - eq_no_fx == pytest.approx(60 * 132.0 * 0.37, rel=1e-6)

    # gross exposure converts too
    gross = await keeper.gross_exposure("cad1")
    assert gross == pytest.approx(60 * 132.0 * 1.37 + 89 * 44.61, rel=1e-6)

    # enriched rows expose their native currency
    enriched = {p["symbol"]: p for p in keeper.positions_list("cad1")}
    assert enriched["SPCX"]["currency"] == "USD"
    assert enriched["AAPL.TO"]["currency"] == "CAD"
