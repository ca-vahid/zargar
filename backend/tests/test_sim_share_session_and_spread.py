"""F-HOLD-01 (2026-09-17): a simulated SHARE stop does not trigger pre-market on a placeholder
quote, and an implausibly wide share quote cannot price a fill. Reproduces the AFRM shadow-book
event: GTC stop 65.00, 03:59:54 ET quote bid 45.00 / ask 75.00 (no source) -> the old executor
"filled" 27 sh @ 44.991. Pure executor tests with a pinned clock; no engine, no database."""
import datetime as dt
from zoneinfo import ZoneInfo

from zargar.brokers.base import BrokerOrder, ExecReport
from zargar.brokers.sim import SimExecutor, regular_session_open
from zargar.domain import OrderSide, OrderType, Quote, TimeInForce

ET = ZoneInfo("America/New_York")


def _ms(y, m, d, hh, mm, ss=0):
    return int(dt.datetime(y, m, d, hh, mm, ss, tzinfo=ET).timestamp() * 1000)


PREMARKET = _ms(2026, 9, 17, 3, 59, 54)       # Thursday, a trading day
RTH = _ms(2026, 9, 17, 9, 31, 0)


class Collector:
    def __init__(self):
        self.reports: list[ExecReport] = []

    async def __call__(self, r: ExecReport):
        self.reports.append(r)

    def kinds(self, kind):
        return [r for r in self.reports if r.kind == kind]


def _executor(clock_ms: int, **kw):
    # the ENGINE's production wiring: both guards on (constructor defaults keep the old
    # any-hour behaviour so direct test rigs built before F-HOLD-01 are unchanged)
    opts = {"stock_sessions": True, "max_spread_pct": 0.05, **kw}
    state = {"t": clock_ms}
    ex = SimExecutor(latency_ms=0, slippage_bps=2.0, size_impact_bps=0.0, clock=lambda: state["t"], **opts)
    col = Collector()
    ex.on_report = col
    return ex, col, state


def _stop(qty=27, stop=65.0):
    return BrokerOrder(id="afrm-stop", symbol="AFRM", sec_type="STK", side=OrderSide.SELL, qty=qty,
                       order_type=OrderType.STP, stop_price=stop, tif=TimeInForce.GTC)


def _junk_quote(ts):
    # the real 03:59:54 ET evidence: a placeholder book, no source, "last" on the stale side
    return Quote(symbol="AFRM", bid=45.0, ask=75.0, last=44.99, bid_size=50_000, ask_size=70_000, ts=ts)


def _sane_quote(ts, bid=63.90, ask=63.95, last=63.92):
    return Quote(symbol="AFRM", bid=bid, ask=ask, last=last, bid_size=500, ask_size=500, ts=ts)


def test_regular_session_window_is_the_exchange_session():
    assert regular_session_open(RTH) is True
    assert regular_session_open(PREMARKET) is False
    assert regular_session_open(_ms(2026, 9, 17, 16, 0)) is False            # close is exclusive
    assert regular_session_open(_ms(2026, 9, 19, 10, 0)) is False            # Saturday
    assert regular_session_open(_ms(2026, 11, 27, 13, 5)) is False           # early close 13:00 ET


async def test_share_stop_does_not_trigger_premarket_on_a_placeholder_quote():
    ex, col, st = _executor(PREMARKET)
    await ex.submit(_stop())
    await ex.on_quote(_junk_quote(PREMARKET))
    assert not col.kinds("fill"), "the AFRM 03:59 ET fill must not happen again"
    waiting = col.kinds("fill_waiting")
    assert waiting and "regular session" in waiting[0].reason
    assert ex.working_count == 1                                              # the stop still protects
    # the session opens: a sane quote through the stop fills at the bid less slippage
    st["t"] = RTH
    await ex.on_quote(_sane_quote(RTH))
    fills = col.kinds("fill")
    assert len(fills) == 1 and fills[0].fill_qty == 27
    assert 63.5 < fills[0].fill_price <= 63.90 and fills[0].evidence["bid"] == 63.90


async def test_implausible_spread_cannot_price_a_share_fill_even_in_session():
    ex, col, _ = _executor(RTH)
    await ex.submit(_stop())
    await ex.on_quote(_junk_quote(RTH))                                        # 45 / 75 = 50% of mid
    assert not col.kinds("fill")
    waiting = col.kinds("fill_waiting")
    assert waiting and "spread implausible" in waiting[0].reason and "50%" in waiting[0].reason
    await ex.on_quote(_sane_quote(RTH))                                        # a plausible book fills
    assert len(col.kinds("fill")) == 1


async def test_market_and_limit_share_orders_also_rest_outside_the_session_unless_outside_rth():
    ex, col, st = _executor(PREMARKET)
    await ex.submit(BrokerOrder(id="mkt", symbol="AFRM", sec_type="STK", side=OrderSide.BUY, qty=5,
                                order_type=OrderType.MKT, tif=TimeInForce.DAY))
    await ex.submit(BrokerOrder(id="lmt-ext", symbol="AFRM", sec_type="STK", side=OrderSide.BUY, qty=5,
                                order_type=OrderType.LMT, limit_price=64.0, tif=TimeInForce.DAY, outside_rth=True))
    await ex.on_quote(_sane_quote(PREMARKET))
    fills = {r.order_id for r in col.kinds("fill")}
    assert fills == {"lmt-ext"}, "only the order explicitly placed for extended hours fills pre-market"
    st["t"] = RTH
    await ex.on_quote(_sane_quote(RTH))
    assert {r.order_id for r in col.kinds("fill")} == {"lmt-ext", "mkt"}


async def test_gates_are_knobs_and_options_keep_their_own_rule():
    # stock_sessions off (the test suites' default) restores the old any-hour share fill
    ex, col, _ = _executor(PREMARKET, stock_sessions=False)
    await ex.submit(_stop())
    await ex.on_quote(_sane_quote(PREMARKET))
    assert len(col.kinds("fill")) == 1
    # the spread guard is a knob too, and it never judges options (a 1.00/1.50 contract is a normal book)
    ex2, col2, _ = _executor(RTH, max_spread_pct=0.0)
    await ex2.submit(_stop())
    await ex2.on_quote(_junk_quote(RTH))
    assert len(col2.kinds("fill")) == 1
    ex3, col3, _ = _executor(RTH, option_sessions=False)
    await ex3.submit(BrokerOrder(id="opt", symbol="AFRM261016C00070000", sec_type="OPT", side=OrderSide.SELL, qty=1,
                                 order_type=OrderType.MKT, tif=TimeInForce.DAY))
    await ex3.on_quote(Quote(symbol="AFRM261016C00070000", bid=1.0, ask=1.5, last=1.2, bid_size=10, ask_size=10,
                             ts=RTH, source="opra", source_ts=RTH))
    assert len(col3.kinds("fill")) == 1
