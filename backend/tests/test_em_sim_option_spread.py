"""EM 2026-09-17 (EOD review package A, ED-01 corrected): the OPTIONAL option spread cap applies ONLY to OPENING option
orders, keyed on the order manager's position-derived `option_action` (BUY_TO_OPEN / SELL_TO_OPEN). A protective stop,
a flatten, a reducing partial exit (…_TO_CLOSE) or an order of unknown intent (None) is never capped and keeps its
existing quote-quality checks. Default OFF keeps every existing rig unchanged; the knob is executor-wide (every desk's
Practice book), so a non-EM opening order is capped the same way when it is on. Reproduces the 09-17 ORCL 148C evidence:
limit 2.29 accepted against 2.10/2.29, then an OPRA snapshot 0.76/1.12 (38% of mid) seven seconds later "filled" at 1.12.
Pure executor tests, pinned clock, no engine, no database."""
import datetime as dt
from zoneinfo import ZoneInfo

from zargar.brokers.base import BrokerOrder, ExecReport
from zargar.brokers.sim import SimExecutor
from zargar.domain import OrderSide, OrderType, Quote, TimeInForce

ET = ZoneInfo("America/New_York")
T0 = int(dt.datetime(2026, 9, 17, 9, 32, 1, tzinfo=ET).timestamp() * 1000)
OCC = "ORCL260918C00148000"


class Collector:
    def __init__(self):
        self.reports: list[ExecReport] = []

    async def __call__(self, r: ExecReport):
        self.reports.append(r)

    def kinds(self, kind):
        return [r for r in self.reports if r.kind == kind]


def _executor(**kw):
    state = {"t": T0}
    ex = SimExecutor(latency_ms=0, slippage_bps=0.0, size_impact_bps=0.0, clock=lambda: state["t"], **kw)
    col = Collector(); ex.on_report = col
    return ex, col, state


def _order(oid, side, order_type, *, qty=1, limit=None, stop=None, action=None, symbol=OCC):
    return BrokerOrder(id=oid, symbol=symbol, sec_type="OPT", side=side, qty=qty, order_type=order_type,
                       limit_price=limit, stop_price=stop, tif=TimeInForce.DAY, option_action=action)


def _q(ts, bid, ask, bid_size=202, ask_size=66, last=None):
    return Quote(symbol=OCC, bid=bid, ask=ask, last=(last if last is not None else ask), bid_size=bid_size, ask_size=ask_size,
                 ts=ts, source="opra", source_ts=ts - 1000)


ABERRANT = (0.76, 1.12)      # 38% of mid


async def test_default_off_keeps_the_old_behaviour_the_aberrant_book_fills_the_entry():
    ex, col, st = _executor()
    await ex.submit(_order("entry", OrderSide.BUY, OrderType.LMT, limit=2.29, action="BUY_TO_OPEN"))
    st["t"] += 7000
    await ex.on_quote(_q(st["t"], *ABERRANT))
    fills = col.kinds("fill")
    assert len(fills) == 1 and abs(float(fills[0].fill_price) - 1.12) < 1e-9, "knob off = 09-17 behaviour, unchanged"


async def test_cap_on_rests_the_opening_order_then_a_plausible_book_fills_at_the_limit():
    ex, col, st = _executor(max_option_spread_pct=0.15)
    await ex.submit(_order("entry", OrderSide.BUY, OrderType.LMT, limit=2.29, action="BUY_TO_OPEN"))
    st["t"] += 7000
    await ex.on_quote(_q(st["t"], *ABERRANT))
    assert col.kinds("fill") == []
    waiting = col.kinds("fill_waiting")
    assert waiting and "implausible for a simulated option entry" in (waiting[-1].reason or "") and "38%" in waiting[-1].reason
    st["t"] += 1000
    await ex.on_quote(_q(st["t"], 2.20, 2.29))
    fills = col.kinds("fill")
    assert len(fills) == 1 and abs(float(fills[0].fill_price) - 2.29) < 1e-9
    assert len(col.kinds("fill_waiting")) == 1, "the waiting reason is journaled once per change, not per quote"


async def test_cap_on_never_touches_a_protective_stop_a_flatten_or_a_reducing_exit():
    """ED-01 reproduction: with the cap at 10% a SELL market flatten on the aberrant book must still exit."""
    ex, col, st = _executor(max_option_spread_pct=0.10)
    await ex.submit(_order("flatten", OrderSide.SELL, OrderType.MKT, qty=3, action="SELL_TO_CLOSE"))
    await ex.submit(_order("stop", OrderSide.SELL, OrderType.STP, qty=1, stop=1.50, action="SELL_TO_CLOSE"))
    await ex.submit(_order("trim", OrderSide.SELL, OrderType.LMT, qty=1, limit=0.70, action="SELL_TO_CLOSE"))
    await ex.submit(_order("cover", OrderSide.BUY, OrderType.MKT, qty=1, action="BUY_TO_CLOSE"))      # closing a short
    st["t"] += 1000
    await ex.on_quote(_q(st["t"], *ABERRANT, last=0.90))                                            # last 0.90 <= stop 1.50 triggers the stop
    filled = {r.order_id for r in col.kinds("fill")}
    assert filled == {"flatten", "stop", "trim", "cover"}, filled
    assert col.kinds("fill_waiting") == [], "no closing order ever inherits the entry spread threshold"


async def test_unknown_intent_is_never_capped_and_existing_quote_checks_still_apply():
    ex, col, st = _executor(max_option_spread_pct=0.10)
    await ex.submit(_order("unknown", OrderSide.BUY, OrderType.LMT, limit=2.29, action=None))     # e.g. a restored order
    st["t"] += 1000
    await ex.on_quote(_q(st["t"], *ABERRANT))
    assert len(col.kinds("fill")) == 1, "unknown intent is never blocked by the cap"
    # the pre-existing rules stay in force for opening orders regardless of the cap: a delayed chain row cannot fill
    await ex.submit(_order("entry2", OrderSide.BUY, OrderType.LMT, limit=2.29, action="BUY_TO_OPEN"))
    st["t"] += 1000
    delayed = Quote(symbol=OCC, bid=2.20, ask=2.29, last=2.25, bid_size=50, ask_size=50, ts=st["t"], source="chain", source_ts=st["t"] - 1000)
    await ex.on_quote(delayed)
    assert [r.order_id for r in col.kinds("fill")] == ["unknown"]
    assert any("Delayed quotes" in (r.reason or "") for r in col.kinds("fill_waiting"))


async def test_cap_is_executor_wide_a_non_em_opening_order_is_capped_the_same_way():
    ex, col, st = _executor(max_option_spread_pct=0.15)
    await ex.submit(_order("tip-entry", OrderSide.BUY, OrderType.LMT, limit=5.00, action="BUY_TO_OPEN", symbol="SMCI260918C00041000"))
    st["t"] += 1000
    await ex.on_quote(Quote(symbol="SMCI260918C00041000", bid=2.00, ask=4.80, last=4.8, bid_size=10, ask_size=10, ts=st["t"], source="opra", source_ts=st["t"] - 500))
    assert col.kinds("fill") == [] and col.kinds("fill_waiting"), "a platform knob, not an EM-only policy - documented in PLATFORM-RULES"


async def test_cap_never_touches_share_orders_and_shares_keep_their_own_cap():
    ex, col, st = _executor(max_option_spread_pct=0.15, max_spread_pct=0.0)
    shares = BrokerOrder(id="schw", symbol="SCHW", sec_type="STK", side=OrderSide.BUY, qty=10, order_type=OrderType.LMT, limit_price=105.0, tif=TimeInForce.DAY)
    await ex.submit(shares)
    st["t"] += 1000
    await ex.on_quote(Quote(symbol="SCHW", bid=60.0, ask=104.0, last=100.0, bid_size=100, ask_size=100, ts=st["t"], source="", source_ts=st["t"]))
    assert len(col.kinds("fill")) == 1, "the option cap is an option rule; the share cap is F-HOLD-01's own knob"
