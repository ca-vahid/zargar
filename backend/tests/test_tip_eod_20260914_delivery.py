"""Delivery/protection isolation boundaries: bounded mocks, no database."""
import asyncio
import contextlib
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from zargar import bus as topics
from zargar.bus import Bus
from zargar.domain import Quote
from zargar.engine import Engine
from zargar.execution.positions import Leg, Managed, PositionManager
from zargar.execution.serialization import position_guard


async def test_slow_sim_fill_does_not_hold_up_unrelated_quote_aggregation():
    entered = asyncio.Event()
    release = asyncio.Event()
    second = asyncio.Event()

    async def slow_fill(_quote):
        entered.set()
        await release.wait()

    def consume(quote):
        if quote.symbol == "SECOND":
            second.set()

    eng = NS(bus=Bus(), bars=NS(on_quote=consume), sim_executor=NS(on_quote=slow_fill))
    task = asyncio.create_task(Engine._quote_consumer(eng))
    try:
        await asyncio.sleep(0)  # subscribe
        eng.bus.publish(topics.QUOTES, Quote(symbol="FIRST", last=10, bid=9, ask=11))
        await asyncio.wait_for(entered.wait(), 1)
        eng.bus.publish(topics.QUOTES, Quote(symbol="SECOND", last=20, bid=19, ask=21))
        try:
            await asyncio.wait_for(second.wait(), .25)
        except TimeoutError:
            pass
        assert second.is_set(), "A fill awaiting I/O blocked unrelated bar aggregation"
    finally:
        release.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_one_position_guard_does_not_block_other_positions_exit_watchdog():
    manager = PositionManager(NS(settings={}))
    manager._persist = AsyncMock()
    manager._journal = AsyncMock()
    manager._now = lambda: 1000.0
    second = asyncio.Event()

    async def close_leg(position, *_args, **_kwargs):
        if position.id == "second":
            second.set()

    manager._close_leg = AsyncMock(side_effect=close_leg)
    for pid in ("first", "second"):
        p = Managed(id=pid, portfolio_id="practice", symbol=pid.upper(), direction="long",
                    technique="tip", policy={}, entry=10, risk=1,
                    legs=[Leg(pid.upper(), "STK", 1, avg_fill=10)])
        p.exits = [{"status": "ERROR", "kind": "stop", "ts": 1}]
        manager._pos[pid] = p
    held = asyncio.Event()
    release = asyncio.Event()

    async def hold_first():
        async with position_guard(manager, "first"):
            held.set()
            await release.wait()

    owner = asyncio.create_task(hold_first())
    await held.wait()
    watch = asyncio.create_task(manager._watch_once())
    try:
        try:
            await asyncio.wait_for(second.wait(), .25)
        except TimeoutError:
            pass
        assert second.is_set(), "One busy position prevented a different position's protective retry"
    finally:
        watch.cancel()
        release.set()
        with contextlib.suppress(asyncio.CancelledError):
            await watch
        await owner
