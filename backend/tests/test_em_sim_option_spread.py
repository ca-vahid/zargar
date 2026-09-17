"""EM 2026-09-18 (EOD review package A, ORCL 148C): an OPTION quote implausibly wide for its mid cannot price a
simulated resting-order fill when the knob is on; the order RESTS with a journaled fill_waiting reason and fills on the
next plausible book. Default OFF keeps every existing rig unchanged. Reproduces the 09-17 evidence: limit 2.29 accepted
against 2.10/2.29, then an OPRA snapshot 0.76/1.12 (38% of mid) seven seconds later "filled" at 1.12 while the contract
traded 2.48-2.88 that minute. Pure executor tests, pinned clock, no engine, no database."""
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


def _limit_buy(limit=2.29):
    return BrokerOrder(id="orcl-148c", symbol=OCC, sec_type="OPT", side=OrderSide.BUY, qty=1,
                       order_type=OrderType.LMT, limit_price=limit, tif=TimeInForce.DAY)


def _q(ts, bid, ask, bid_size=202, ask_size=66):
    return Quote(symbol=OCC, bid=bid, ask=ask, last=ask, bid_size=bid_size, ask_size=ask_size, ts=ts, source="opra", source_ts=ts - 1000)


async def test_default_off_keeps_the_old_behaviour_the_aberrant_book_fills():
    ex, col, st = _executor()
    await ex.submit(_limit_buy())
    st["t"] += 7000
    await ex.on_quote(_q(st["t"], 0.76, 1.12))
    fills = col.kinds("fill")
    assert len(fills) == 1 and abs(float(fills[0].price) - 1.12) < 1e-9, "knob off = 09-17 behaviour, unchanged"


async def test_cap_on_the_aberrant_book_rests_the_order_then_a_plausible_book_fills_at_the_limit():
    ex, col, st = _executor(max_option_spread_pct=0.15)
    await ex.submit(_limit_buy())
    st["t"] += 7000
    await ex.on_quote(_q(st["t"], 0.76, 1.12))                      # 38% of mid
    assert col.kinds("fill") == []
    waiting = col.kinds("fill_waiting")
    assert waiting and "implausible for a simulated option fill" in (waiting[-1].reason or "") and "38%" in waiting[-1].reason
    st["t"] += 1000
    await ex.on_quote(_q(st["t"], 2.20, 2.29))                      # ~4% of mid, at the limit
    fills = col.kinds("fill")
    assert len(fills) == 1 and abs(float(fills[0].price) - 2.29) < 1e-9
    assert len(col.kinds("fill_waiting")) == 1, "the waiting reason is journaled once per change, not per quote"


async def test_cap_never_touches_share_orders_and_shares_keep_their_own_cap():
    ex, col, st = _executor(max_option_spread_pct=0.15, max_spread_pct=0.0)
    shares = BrokerOrder(id="schw", symbol="SCHW", sec_type="STK", side=OrderSide.BUY, qty=10, order_type=OrderType.LMT, limit_price=105.0, tif=TimeInForce.DAY)
    await ex.submit(shares)
    st["t"] += 1000
    await ex.on_quote(Quote(symbol="SCHW", bid=60.0, ask=104.0, last=100.0, bid_size=100, ask_size=100, ts=st["t"], source="", source_ts=st["t"]))
    assert len(col.kinds("fill")) == 1, "the option cap is an option rule; the share cap is F-HOLD-01's own knob"
