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


async def test_auto_halt_spares_the_shadow_record_manual_blocks_all():
    # 2026-09-04: Practice's -9.13% daily-loss halt rejected a RESEARCH entry —
    # an AUTO halt protects real books from tilt but must not blind the
    # learning record; a MANUAL halt (app/Telegram) still stops everything.
    quotes = FakeQuotes()
    quotes.set("AAPL", 100.0)
    shadow_pf = type("Pf", (), {"kind": "shadow", "id": "sh1"})()
    halt = HaltState()
    halt.engage("daily loss limit: Practice at -9.13%", source="auto")
    gate = make_gate(quotes=quotes, halt=halt)
    v_shadow = await gate.evaluate(intent(portfolio_id="sh1"), shadow_pf)
    assert check(v_shadow, "kill_switch").passed          # the record keeps collecting
    v_real = await gate.evaluate(intent(), P)
    assert not check(v_real, "kill_switch").passed        # real books stay halted
    halt.engage("user hit HALT", source="app")            # manual: everything stops
    v_manual = await gate.evaluate(intent(portfolio_id="sh1"), shadow_pf)
    assert not check(v_manual, "kill_switch").passed


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


async def test_share_shorting_is_never_allowed():
    """NEVER-LIST (2026-08-27): share shorting is a hard rejection even with
    risk.allow_short set — shorts are expressed with long puts only."""
    quotes = FakeQuotes()
    quotes.set("AAPL", 100.0)
    settings = FakeSettings(**{"risk.allow_short": True})
    verdict = await make_gate(settings=settings, quotes=quotes).evaluate(
        intent(side="SELL", qty=2), P)
    c = check(verdict, "short_allowed")
    assert not c.passed and "never" in c.detail


async def test_halted_instrument_blocks():
    quotes = FakeQuotes()
    quotes.set("AAPL", 100.0, halted=True)
    verdict = await make_gate(quotes=quotes).evaluate(intent(), P)
    assert not check(verdict, "not_halted").passed


async def test_duplicate_order_blocked():
    quotes = FakeQuotes()
    quotes.set("AAPL", 100.0)
    gate = make_gate(quotes=quotes)
    gate.note_submission("AAPL", "BUY", 2, "LMT", portfolio_id="p1")
    verdict = await gate.evaluate(intent(), P)
    assert not check(verdict, "duplicate_order").passed
    # a DIFFERENT book's identical order is NOT a duplicate (2026-08-29 rule:
    # the shadow book expressing the same tip must not block the real order)
    verdict2 = await gate.evaluate(intent(portfolio_id="p2"), P)
    assert check(verdict2, "duplicate_order").passed
    # a RESEARCH book never dedupes: distinct tips firing the same level in
    # the same second are separate records (tt MU x3, 2026-09-02)

    class Shadow:
        kind = "shadow"
    verdict3 = await gate.evaluate(intent(), Shadow)
    assert check(verdict3, "duplicate_order").passed


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


async def test_shadow_books_exempt_from_equity_pct_caps():
    """2026-09-01: $5k-sized record entries bounced off %-of-equity caps on
    small fake books (TSLA $4.8k premium vs a $7.6k shadow book; 337% gross).
    Same precedent as the daily-loss exemption — absolute caps still apply."""
    quotes = FakeQuotes()
    quotes.set("AAPL", 100.0)
    positions = FakePositions(equity=5_000.0, gross=14_000.0)

    class Shadow:
        kind = "shadow"

    verdict = await make_gate(quotes=quotes, positions=positions).evaluate(
        intent(qty=40), Shadow)      # $4k notional = 80% of the fake equity
    names = {c.name for c in verdict.checks}
    assert "max_position_pct" not in names and "max_gross_exposure" not in names
    assert "option_premium_cap" not in names
    assert "max_position_notional" in names          # absolute caps still run


async def test_tip_lotto_lane_allows_0dte_before_flatten_time(monkeypatch):
    """Found 2026-09-02 open: a 4th 0DTE gate (the RiskGate never-list) rejected
    the lotto lane's first fills. Tips get their own gated path; every other
    technique stays hard-rejected."""
    import zargar.risk as riskmod
    from zargar.options import occ as occmod
    quotes = FakeQuotes()
    today = __import__("datetime").date.today()
    sym = f"AAPL{today:%y%m%d}C00100000"
    quotes.set(sym, 1.0)
    settings = FakeSettings(**{"techniques.tip.lotto_enabled": True,
                               "techniques.tip.lotto_flatten_et": "23:59"})
    gate = make_gate(settings=settings, quotes=quotes)
    v = await gate.evaluate(intent(symbol=sym, sec_type="OPT", qty=1, technique_id="tip"), P)
    assert check(v, "option_not_expired").passed
    v2 = await gate.evaluate(intent(symbol=sym, sec_type="OPT", qty=1, technique_id="flow"), P)
    assert not check(v2, "option_not_expired").passed
    settings.values["techniques.tip.lotto_flatten_et"] = "00:00"
    v3 = await gate.evaluate(intent(symbol=sym, sec_type="OPT", qty=1, technique_id="tip"), P)
    assert not check(v3, "option_not_expired").passed


async def test_shadow_books_exempt_from_daily_loss_halt():
    """User decision 2026-08-31: shadow books are the research record — eva's
    immediate book self-halted at -8% and stopped RECORDING tips. A shadow
    loss costs nothing; a gap in the record costs learning."""
    quotes = FakeQuotes()
    quotes.set("AAPL", 100.0)
    positions = FakePositions(daily_loss=-21.0)

    class Shadow:
        kind = "shadow"

    verdict = await make_gate(quotes=quotes, positions=positions).evaluate(intent(), Shadow)
    assert verdict.passed, verdict.failures
    assert not any(c.name == "daily_loss_limit" for c in verdict.checks)


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


# ---------------------------------------------------------------- phone safety

class LiveP:
    kind = "live"


async def test_phone_cannot_open_real_position_by_default():
    quotes = FakeQuotes()
    quotes.set("AAPL", 100.0)
    verdict = await make_gate(quotes=quotes).evaluate(intent(client="phone"), LiveP)
    assert not verdict.passed
    assert not check(verdict, "phone_entry_blocked").passed
    # the same order from a desktop passes
    assert (await make_gate(quotes=quotes).evaluate(intent(client="desktop"), LiveP)).passed


async def test_phone_may_reduce_and_may_trade_practice():
    quotes = FakeQuotes()
    quotes.set("AAPL", 100.0)
    pos = FakePositions()
    pos.qty["AAPL"] = 5
    # selling part of a real position from a phone reduces risk -> allowed
    verdict = await make_gate(quotes=quotes, positions=pos).evaluate(
        intent(client="phone", side="SELL", qty=2), LiveP)
    assert check(verdict, "phone_entry_blocked").passed
    # opening on the simulator from a phone is fine
    assert check(await make_gate(quotes=quotes).evaluate(intent(client="phone"), P),
                 "phone_entry_blocked").passed


async def test_phone_entries_allowed_when_setting_off():
    quotes = FakeQuotes()
    quotes.set("AAPL", 100.0)
    gate = make_gate(settings=FakeSettings(**{"mobile.exit_only": False}), quotes=quotes)
    verdict = await gate.evaluate(intent(client="phone"), LiveP)
    assert verdict.passed, verdict.failures
