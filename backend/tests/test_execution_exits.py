"""Unit tests for the shared execution layer: the pure exit-decision logic and
reduce-only intent building (no broker, no DB)."""
from __future__ import annotations

from dataclasses import dataclass, field

from zargar.domain import Bar
from zargar.execution.exits import (
    ExitDecision, plan_exit, reduce_only_exit_intent, stale_working_exit,
)


@dataclass
class FakeTrade:
    remaining: float
    filled_qty: float
    trims_done: int
    targets: list[float]
    stop: float
    sec_type: str = "STK"
    exits: list[dict] = field(default_factory=list)

    @property
    def pending_exit_qty(self) -> float:
        total = 0.0
        for e in self.exits:
            if e.get("status") in ("FILLED", "CANCELLED", "REJECTED", "REJECTED_RISK", "EXPIRED", "ERROR"):
                continue
            total += float(e.get("qty") or 0) - float(e.get("filledQty") or 0)
        return max(0.0, total)


def _bar(low, high, ts=1_000, close=None):
    close = high if close is None else close
    return Bar(symbol="X", tf="1m", ts=ts, open=low, high=high, low=low, close=close, volume=100)


def test_stop_takes_priority_and_exits_everything():
    tr = FakeTrade(remaining=100, filled_qty=100, trims_done=0, targets=[101, 102, 103], stop=99)
    d = plan_exit(tr, _bar(98.5, 100.0), close_ms=10**13, flatten_minutes=5)
    assert isinstance(d, ExitDecision) and d.kind == "stop" and d.qty == 100 and d.new_trims_done == 3


def test_ladder_trims_30_40_15():
    tr = FakeTrade(remaining=100, filled_qty=100, trims_done=0, targets=[101, 102, 103], stop=99)
    d = plan_exit(tr, _bar(100.5, 101.2), close_ms=10**13, flatten_minutes=5)
    assert d.kind == "tp1" and d.qty == 30 and d.new_trims_done == 1
    tr.remaining, tr.trims_done = 70, 1
    d = plan_exit(tr, _bar(101.5, 102.2), close_ms=10**13, flatten_minutes=5)
    assert d.kind == "tp2" and d.qty == 40 and d.new_trims_done == 2


def test_flatten_before_close_beats_targets():
    tr = FakeTrade(remaining=55, filled_qty=100, trims_done=2, targets=[101, 102, 103], stop=99)
    close_ms = 1_000_000
    bar = _bar(102.5, 103.5, ts=close_ms - 4 * 60_000)   # inside the 5-min flatten window
    d = plan_exit(tr, bar, close_ms=close_ms, flatten_minutes=5)
    assert d.kind == "flatten" and d.qty == 55


def test_pending_exit_blocks_a_second_send():
    tr = FakeTrade(remaining=100, filled_qty=100, trims_done=0, targets=[101, 102, 103], stop=99,
                   exits=[{"kind": "stop", "qty": 100, "filledQty": 0, "status": None}])
    assert plan_exit(tr, _bar(98.0, 99.5), close_ms=10**13, flatten_minutes=5) is None


def test_single_contract_option_exits_in_full_at_tp2():
    tr = FakeTrade(remaining=1, filled_qty=1, trims_done=0, targets=[101, 102, 103], stop=99, sec_type="OPT")
    # TP1 touched: a single contract does not trim, and the caller advances trims
    assert plan_exit(tr, _bar(100.5, 101.2), close_ms=10**13, flatten_minutes=5, single_exit="tp2") is None
    tr.trims_done = 1
    d = plan_exit(tr, _bar(101.5, 102.2), close_ms=10**13, flatten_minutes=5, single_exit="tp2")
    assert d.kind == "tp2" and d.qty == 1 and d.new_trims_done == 3


def test_stale_working_exit_flags_after_reprice_window():
    tr = FakeTrade(remaining=100, filled_qty=100, trims_done=0, targets=[101], stop=99,
                   exits=[{"kind": "stop", "qty": 100, "filledQty": 0, "status": None,
                           "orderId": "o1", "barIndex": 5}])
    assert stale_working_exit(tr, 6, reprice_bars=2) is None      # still fresh
    stale = stale_working_exit(tr, 8, reprice_bars=2)
    assert stale is not None and stale["orderId"] == "o1"


def test_reduce_only_intent_is_reduce_only_and_sells():
    shares = reduce_only_exit_intent(portfolio_id="p", symbol="AAPL", sec_type="STK", qty=10)
    assert shares.reduce_only and shares.side == "SELL" and shares.order_type == "MKT"
    opt = reduce_only_exit_intent(portfolio_id="p", symbol="AAPL260101C00200000", sec_type="OPT", qty=1, bid=2.4)
    assert opt.reduce_only and opt.order_type == "LMT" and opt.limit_price == 2.4
    forced = reduce_only_exit_intent(portfolio_id="p", symbol="AAPL260101C00200000", sec_type="OPT",
                                     qty=1, bid=2.4, force_market=True)
    assert forced.order_type == "MKT"
