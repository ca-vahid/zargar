"""Deterministic signal verification against market data."""
import time

from zargar.domain import Quote
from zargar.signals.schemas import TradeSignal
from zargar.signals.verification import verify_signal


class FakeQuotes:
    def __init__(self):
        self.quotes = {}

    def set(self, symbol, last, spread=0.02, halted=False):
        self.quotes[symbol] = Quote(
            symbol=symbol, last=last, bid=last - spread / 2, ask=last + spread / 2,
            bid_size=500, ask_size=500, halted=halted, ts=int(time.time() * 1000))

    def get(self, symbol):
        return self.quotes.get(symbol)

    def age_seconds(self, symbol):
        return 0.0


class FakeSettings:
    def __init__(self, **overrides):
        self.values = {
            "verification.max_price_deviation_pct": 3.0,
            "verification.max_spread_pct": 1.5,
            "verification.min_price": 1.0,
            "verification.require_actionable": True,
        }
        self.values.update(overrides)

    def get(self, key, default=None):
        return self.values.get(key, default)


def sig(**kw):
    base = dict(ticker="NVDA", direction="long", action="open",
                entry_price=128.0, target_price=145.0, stop_price=122.0,
                entry_type="limit", timeframe="swing", thesis_summary="x",
                evidence_quotes=["buy NVDA"], confidence="explicit_call",
                is_actionable=True)
    base.update(kw)
    return TradeSignal(**base)


def named(result, name):
    return next(c for c in result["checks"] if c["name"] == name)


async def test_clean_signal_passes():
    quotes = FakeQuotes()
    quotes.set("NVDA", 128.5)
    result = await verify_signal(sig(), quotes, FakeSettings())
    assert result["passed"], result


async def test_unknown_ticker_fails():
    result = await verify_signal(sig(ticker="ZZZQ"), FakeQuotes(), FakeSettings())
    assert not named(result, "ticker_resolves")["passed"]


async def test_price_deviation_fails():
    quotes = FakeQuotes()
    quotes.set("NVDA", 140.0)  # 9.4% above claimed 128 entry
    result = await verify_signal(sig(), quotes, FakeSettings())
    assert not named(result, "price_deviation")["passed"]


async def test_past_target_fails():
    quotes = FakeQuotes()
    quotes.set("NVDA", 146.0)
    result = await verify_signal(sig(entry_price=None), quotes, FakeSettings())
    # without entry there is no deviation check, but target check needs entry too;
    # give entry within range instead
    quotes.set("NVDA", 129.0)
    result = await verify_signal(
        sig(target_price=129.0), quotes, FakeSettings())
    assert not named(result, "not_past_target")["passed"]


async def test_wide_spread_fails():
    quotes = FakeQuotes()
    quotes.set("PENNY", 5.0, spread=0.5)  # 10% spread
    result = await verify_signal(sig(ticker="PENNY", entry_price=5.0, target_price=6.0,
                                     stop_price=4.5), quotes, FakeSettings())
    assert not named(result, "spread")["passed"]


async def test_min_price_filter():
    quotes = FakeQuotes()
    quotes.set("SUB", 0.40, spread=0.002)
    result = await verify_signal(sig(ticker="SUB", entry_price=0.40, target_price=0.8,
                                     stop_price=0.3), quotes, FakeSettings())
    assert not named(result, "min_price")["passed"]


async def test_cold_quote_parks_instead_of_failing():
    """MRVL 2026-08-31: a just-subscribed symbol served a placeholder quote
    (last 0.00, empty book) and the fatal penny-stock + 999% spread-sentinel
    checks killed a real tip. A cold quote is a FEED state — park it."""
    quotes = FakeQuotes()
    quotes.quotes["MRVL"] = Quote(symbol="MRVL", last=0.0, bid=0.0, ask=0.0,
                                  bid_size=0, ask_size=0, halted=False,
                                  ts=int(time.time() * 1000))
    result = await verify_signal(sig(ticker="MRVL", entry_price=90.0, target_price=99.0,
                                     stop_price=85.0), quotes, FakeSettings())
    assert not named(result, "ticker_resolves")["passed"]
    assert result["park"], result             # parked, not verification_failed
    names = {c["name"] for c in result["checks"]}
    assert "min_price" not in names and "spread" not in names


async def test_warm_last_with_empty_book_skips_spread_verdict():
    """Yahoo-poll quotes often carry a live last with no bid/ask — the spread
    sentinel (999%) is unknowable liquidity, not bad liquidity. The expression
    layer re-checks the tradeable spread at trade time (T5.4)."""
    quotes = FakeQuotes()
    quotes.quotes["NVDA"] = Quote(symbol="NVDA", last=128.5, bid=0.0, ask=0.0,
                                  bid_size=0, ask_size=0, halted=False,
                                  ts=int(time.time() * 1000))
    result = await verify_signal(sig(), quotes, FakeSettings())
    assert result["passed"], result
    assert "spread" not in {c["name"] for c in result["checks"]}


async def test_halted_fails():
    quotes = FakeQuotes()
    quotes.set("NVDA", 128.5, halted=True)
    result = await verify_signal(sig(), quotes, FakeSettings())
    assert not named(result, "not_halted")["passed"]


async def test_bad_price_ordering_fails():
    quotes = FakeQuotes()
    quotes.set("NVDA", 128.5)
    result = await verify_signal(sig(stop_price=130.0), quotes, FakeSettings())
    assert not named(result, "price_ordering")["passed"]


async def test_commentary_only_fails():
    quotes = FakeQuotes()
    quotes.set("NVDA", 128.5)
    result = await verify_signal(sig(confidence="commentary_only"), quotes, FakeSettings())
    assert not named(result, "explicit_or_implied")["passed"]


async def test_grounding_failure_fails():
    quotes = FakeQuotes()
    quotes.set("NVDA", 128.5)
    result = await verify_signal(sig(), quotes, FakeSettings(),
                                 grounding={"passed": False})
    assert not named(result, "quote_grounding")["passed"]
