"""September 10 performance audit: deterministic reproductions, no real orders."""
import datetime as dt
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from zargar.domain import Bar, Quote, new_id
from zargar.execution.positions import Leg, Managed, PositionManager
from zargar.models import Order, Signal
from zargar.techniques.tip import retro

from .test_tip_geometry import rig as rig  # noqa: PLC0414


def option_position():
    return Managed(id="audit", portfolio_id="offline", symbol="SPCX", direction="long",
        technique="tip", policy={"premium_stop_pct": 35}, entry=153.6, risk=2.5,
        entry_mark=2.11, legs=[Leg("SPCX270115C00155000", "OPT", 3, avg_fill=2.11, multiplier=100)])


@pytest.mark.parametrize("source", ["chain", "opra"])
async def test_bar_premium_stop_requires_a_fresh_option_mark(source):
    now = int(dt.datetime(2026, 9, 10, 15, 0, tzinfo=dt.UTC).timestamp() * 1000)
    q = Quote(symbol="SPCX270115C00155000", bid=.97, ask=1.05, last=2.02,
              source=source, ts=now, source_ts=now - 3_600_000)
    manager = PositionManager(NS(settings={}, quotes=NS(get=lambda symbol: q)))
    manager._now = lambda: now / 1000
    manager.close = AsyncMock()
    manager._persist = AsyncMock()
    position = option_position()
    bar = Bar(symbol="SPCX", tf="1m", ts=now, open=153.6, high=153.7, low=153.5, close=153.6)
    await manager._decide(position, bar, [bar])
    assert manager.close.await_count == 0, manager.close.call_args_list


def test_filled_fractional_exit_remainders_are_not_in_flight():
    manager = PositionManager(NS(settings={}))
    position = Managed(id="audit", portfolio_id="offline", symbol="MU", direction="long",
        technique="tip", policy={}, entry=974.25, risk=11.15,
        legs=[Leg("MU", "STK", 1, avg_fill=974.25)])
    position.exits = [{"leg": "MU", "qty": 2.5, "filledQty": 2,
                       "status": "FILLED", "ts": 1} for _ in range(2)]
    assert manager._inflight_exit_qty(position, "MU") == 0


async def test_expired_shadow_plan_does_not_make_a_filled_tip_unfilled(rig, monkeypatch):
    pid = next(p["id"] for p in rig.positions.portfolios() if p["kind"] == "sim")
    sid = new_id()
    async with rig.sf() as session:
        session.add(Signal(id=sid, ticker="CCXI", direction="long", source_name="AuditSource",
            action="open", thesis_summary="offline", status="expired", extraction={},
            confidence="explicit_call", is_actionable=True))
        await session.flush()
        session.add(Order(id=new_id(), portfolio_id=pid, signal_id=sid, symbol="CCXI261016C00017500",
            sec_type="OPT", side="BUY", qty=12, filled_qty=12, avg_fill_price=.60,
            order_type="LMT", status="FILLED"))
        await session.commit()
    loop = AsyncMock(return_value='{"grade":"bad_call"}')
    monkeypatch.setattr(retro, "run_agent_loop", loop)
    await retro.run_unfilled_retros(rig, client=NS())
    assert loop.await_count == 0, "A known filled Practice tip was sent as EXPIRED-UNFILLED"
