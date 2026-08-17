"""RiskGate unit tests with in-memory fakes (no DB)."""
import time

import pytest

from zargar.domain import Quote
from zargar.orders import OrderIntent
from zargar.risk import HaltState, RiskGate


class FakeSettings:
    def __init__(self, **overrides):
        self.values = {
            "risk.max_position_notional": 1000.0,
            "risk.max_position_pct": 10.0,
            "risk.max_gross_exposure_pct": 100.0,
            "risk.price_collar_pct": 5.0,
            "risk.max_orders_per_minute": 10,
            "risk.stale_quote_seconds": 10,
            "risk.daily_loss_halt_pct": 3.0,
            "risk.allow_short": False,
            "risk.allow_options": True,
            "risk.max_option_premium_pct": 5.0,
            "risk.duplicate_window_seconds": 10,
            "risk.require_market_hours": False,
        }
        self.values.update(overrides)

    def get(self, key, default=None):
        return self.values.get(key, default)


class FakeQuotes:
    def __init__(self):
        self.quotes = {}

    def set(self, symbol, last, bid=None, ask=None, halted=False, age=0.0):
        q = Quote(symbol=symbol, last=last, bid=bid or last - 0.01,
                  ask=ask or last + 0.01, bid_size=500, ask_size=500, halted=halted)
        q.ts = int((time.time() - age) * 1000)
        self.quotes[symbol] = q

    def get(self, symbol):
        return self.quotes.get(symbol)

    def age_seconds(self, symbol):
        q = self.quotes.get(symbol)
        if q is None:
            return float("inf")
        return max(0.0, time.time() - q.ts / 1000)


class FakePositions:
    def __init__(self, equity=10_000.0, gross=0.0, daily_loss=0.0):
        self._equity = equity
        self._gross = gross
        self._daily = daily_loss
        self.qty = {}

    def position_qty(self, pid, symbol, sec_type="STK"):
        return self.qty.get(symbol, 0.0)

    async def equity(self, pid):
        return self._equity

    async def gross_exposure(self, pid):
        return self._gross

    async def daily_loss_pct(self, pid):
        return self._daily


class P:
    kind = "sim"


def make_gate(settings=None, quotes=None, positions=None, halt=None):
    return RiskGate(settings or FakeSettings(), quotes or FakeQuotes(),
                    positions or FakePositions(), halt or HaltState())


def intent(**kw):
    base = dict(portfolio_id="p1", symbol="AAPL", side="BUY", qty=2,
                order_type="LMT", limit_price=100.0)
    base.update(kw)
    return OrderIntent(**base)


def check(verdict, name):
    return next(c for c in verdict.checks if c.name == name)


async def test_passes_clean_order():
    quotes = FakeQuotes()
    quotes.set("AAPL", 100.0)
    verdict = await make_gate(quotes=quotes).evaluate(intent(), P)
    assert verdict.passed, verdict.failures


async def test_kill_switch_blocks():
    halt = HaltState()
    halt.engage("test")
    quotes = FakeQuotes()
    quotes.set("AAPL", 100.0)
    verdict = await make_gate(quotes=quotes, halt=halt).evaluate(intent(), P)
    assert not verdict.passed
    assert not check(verdict, "kill_switch").passed


async def test_stale_quote_blocks():
    quotes = FakeQuotes()
    quotes.set("AAPL", 100.0, age=60)
    verdict = await make_gate(quotes=quotes).evaluate(intent(), P)
    assert not check(verdict, "quote_fresh").passed


async def test_missing_quote_blocks():
    verdict = await make_gate().evaluate(intent(), P)
    assert not check(verdict, "quote_fresh").passed


async def test_price_collar():
    quotes = FakeQuotes()
    quotes.set("AAPL", 100.0)
    verdict = await make_gate(quotes=quotes).evaluate(intent(limit_price=120.0), P)
    assert not check(verdict, "price_collar").passed


async def test_max_position_notional():
    quotes = FakeQuotes()
    quotes.set("AAPL", 100.0)
    verdict = await make_gate(quotes=quotes).evaluate(intent(qty=50), P)  # $5000 > $1000
    assert not check(verdict, "max_position_notional").passed


async def test_reducing_position_bypasses_caps():
    quotes = FakeQuotes()
    quotes.set("AAPL", 100.0)
    positions = FakePositions()
    positions.qty["AAPL"] = 50  # existing $5000 position
    verdict = await make_gate(quotes=quotes, positions=positions).evaluate(
        intent(side="SELL", qty=40), P)  # reduces to $1000
    assert verdict.passed, verdict.failures


async def test_short_blocked_by_default():
    quotes = FakeQuotes()
    quotes.set("AAPL", 100.0)
    verdict = await make_gate(quotes=quotes).evaluate(intent(side="SELL", qty=2), P)
    assert not check(verdict, "short_allowed").passed


async def test_short_allowed_when_enabled():
    quotes = FakeQuotes()
    quotes.set("AAPL", 100.0)
    settings = FakeSettings(**{"risk.allow_short": True})
    verdict = await make_gate(settings=settings, quotes=quotes).evaluate(
        intent(side="SELL", qty=2), P)
    assert check(verdict, "short_allowed").passed


async def test_halted_instrument_blocks():
    quotes = FakeQuotes()
    quotes.set("AAPL", 100.0, halted=True)
    verdict = await make_gate(quotes=quotes).evaluate(intent(), P)
    assert not check(verdict, "not_halted").passed


async def test_duplicate_order_blocked():
    quotes = FakeQuotes()
    quotes.set("AAPL", 100.0)
    gate = make_gate(quotes=quotes)
    gate.note_submission("AAPL", "BUY", 2, "LMT")
    verdict = await gate.evaluate(intent(), P)
    assert not check(verdict, "duplicate_order").passed


async def test_order_rate_limit():
    quotes = FakeQuotes()
    quotes.set("AAPL", 100.0)
    gate = make_gate(quotes=quotes)
    for i in range(10):
        gate.note_submission("SYM" + str(i), "BUY", 1, "LMT")
    verdict = await gate.evaluate(intent(), P)
    assert not check(verdict, "order_rate").passed


async def test_daily_loss_halt():
    quotes = FakeQuotes()
    quotes.set("AAPL", 100.0)
    positions = FakePositions(daily_loss=-4.0)
    verdict = await make_gate(quotes=quotes, positions=positions).evaluate(intent(), P)
    assert not check(verdict, "daily_loss_limit").passed


async def test_option_premium_cap():
    quotes = FakeQuotes()
    quotes.set("AAPL240119C00100000", 6.0)
    # 2 contracts * $6 * 100 = $1200 premium > 5% of $10k equity ($500)
    verdict = await make_gate(quotes=quotes).evaluate(
        intent(symbol="AAPL240119C00100000", sec_type="OPT", qty=2, limit_price=6.0), P)
    assert not check(verdict, "option_premium_cap").passed


async def test_naked_short_option_blocked():
    quotes = FakeQuotes()
    quotes.set("OPT1", 2.0)
    settings = FakeSettings(**{"risk.allow_short": True})
    verdict = await make_gate(settings=settings, quotes=quotes).evaluate(
        intent(symbol="OPT1", sec_type="OPT", side="SELL", qty=1, limit_price=2.0), P)
    assert not check(verdict, "no_naked_short_option").passed
