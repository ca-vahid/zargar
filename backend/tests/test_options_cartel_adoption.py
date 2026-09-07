"""Terminal confirmed entry adoption is durable and idempotent across callback races."""
import asyncio

import pytest
from sqlalchemy import func, select

from zargar.models import ManagedPositionRow, Order, Position, TechniqueRun
from zargar.techniques.options_cartel.adoption import adopt_confirmed_entry, reconcile_entry_fills
from zargar.techniques.options_cartel.exits import ExitCampaign

from .cartel_orders import RecordedOrders
from .test_options_cartel_setups import histories
from .test_options_cartel_state import insert_order, intent, ready
from .test_options_cartel_state import repo as _repo_fixture

repo = _repo_fixture


async def setup_entry(repository, *, status="FILLED", filled=2):
    await ready(repository)
    reservation = await repository.reserve_submission("r1", intent())
    await insert_order(repository, reservation, status=status, filled_qty=filled)
    await repository.reconcile_submission("r1")
    history, _ = histories()
    async with repository.engine.sf() as session:
        run = await session.get(TechniqueRun, "r1")
        run.result = {**run.result, "exitCampaign": ExitCampaign.for_profile("may_2026", [55]).model_dump(mode="json")}
        run.config = {"inputs": {"history": [b.model_copy(update={"symbol": "HOOD"}).model_dump(mode="json") for b in history]}}
        session.add(Position(portfolio_id="pf", symbol="HOOD", sec_type="STK", qty=filled, avg_cost=48.95))
        await session.commit()
    await repository.engine.positions.load()
    repository.engine.orders = RecordedOrders(repository.engine)
    repository.engine.orders.n = 100  # exit/stop ids must not collide with synthetic entry o1
    repository.engine.orders.script[100] = {"status": "ACCEPTED"}  # venue stop


async def test_competing_adoptions_create_one_position_with_actual_fill_price(repo):
    await setup_entry(repo)
    try:
        results = await asyncio.gather(adopt_confirmed_entry(repo.engine, "r1"), adopt_confirmed_entry(repo.engine, "r1"))
        assert len({r["positionId"] for r in results}) == 1
        assert sum(not r["reused"] for r in results) == 1
        async with repo.engine.sf() as session:
            assert await session.scalar(select(func.count()).select_from(ManagedPositionRow)) == 1
            row = await session.get(ManagedPositionRow, results[0]["positionId"])
            assert row.legs[0]["qty"] == 2 and row.legs[0]["avgFill"] == 48.95
            assert row.legs[0]["entryOrderId"] == "o1"
        assert (await repo.load("r1"))["state"]["phase"] == "managed"
    finally:
        await repo.engine.position_manager.stop()


async def test_working_partial_is_not_mistaken_for_terminal_filled_quantity(repo):
    await setup_entry(repo, status="PARTIALLY_FILLED", filled=1)
    with pytest.raises(ValueError, match="still working"):
        await adopt_confirmed_entry(repo.engine, "r1")
    async with repo.engine.sf() as session:
        assert await session.scalar(select(func.count()).select_from(ManagedPositionRow)) == 0


async def test_cancelled_partial_adopts_only_confirmed_units(repo):
    await setup_entry(repo, status="CANCELLED", filled=1)
    try:
        result = await adopt_confirmed_entry(repo.engine, "r1")
        p = repo.engine.position_manager.get(result["positionId"])
        assert p.legs[0].qty == 1 and p.policy["cartel"]["initialQty"] == 1
        assert (await repo.load("r1"))["state"]["adoptedEntryQty"] == 1
    finally:
        await repo.engine.position_manager.stop()


async def test_unfilled_terminal_order_cannot_manufacture_a_position(repo):
    await setup_entry(repo, status="CANCELLED", filled=0)
    with pytest.raises(ValueError, match="confirmed bought"):
        await adopt_confirmed_entry(repo.engine, "r1")


async def test_late_extra_fills_are_reported_instead_of_duplicating_adoption(repo):
    await setup_entry(repo, status="CANCELLED", filled=1)
    try:
        await adopt_confirmed_entry(repo.engine, "r1")
        async with repo.engine.sf() as session:
            order = await session.get(Order, "o1")
            order.filled_qty = 2
            await session.commit()
        with pytest.raises(ValueError, match="late additional"):
            await adopt_confirmed_entry(repo.engine, "r1")
        async with repo.engine.sf() as session:
            assert await session.scalar(select(func.count()).select_from(ManagedPositionRow)) == 1
    finally:
        await repo.engine.position_manager.stop()


async def test_already_sold_exposure_cannot_be_adopted_from_an_old_fill(repo):
    await setup_entry(repo)
    async with repo.engine.sf() as session:
        position = await session.scalar(select(Position).where(Position.portfolio_id == "pf"))
        position.qty = 0
        await session.commit()
    await repo.engine.positions.load()
    with pytest.raises(ValueError, match="unallocated portfolio holdings"):
        await adopt_confirmed_entry(repo.engine, "r1")


async def test_failed_durable_save_cannot_continue_to_venue_protection_or_binding(repo, monkeypatch):
    await setup_entry(repo)
    original = repo.engine.sf
    calls = [0]

    class Unavailable:
        async def __aenter__(self):
            raise OSError("injected persistence outage")

        async def __aexit__(self, *args):
            return False

    def factory():
        calls[0] += 1
        return Unavailable() if calls[0] == 3 else original()

    monkeypatch.setattr(repo.engine, "sf", factory)
    with pytest.raises(OSError, match="persistence outage"):
        await adopt_confirmed_entry(repo.engine, "r1")
    monkeypatch.setattr(repo.engine, "sf", original)
    assert repo.engine.orders.placed == []
    assert (await repo.load("r1"))["state"]["phase"] == "working"
    async with original() as session:
        assert await session.scalar(select(func.count()).select_from(ManagedPositionRow)) == 0
    try:
        result = await adopt_confirmed_entry(repo.engine, "r1")
        assert not result["reused"]
    finally:
        await repo.engine.position_manager.stop()


async def test_closed_adoption_is_never_resurrected_by_retry(repo):
    await setup_entry(repo)
    try:
        first = await adopt_confirmed_entry(repo.engine, "r1")
        await repo.engine.position_manager.close(first["positionId"], fraction=1, force_market=True,
                                                 reason="synthetic closure")
        again = await adopt_confirmed_entry(repo.engine, "r1")
        assert again["reused"] and again["status"] == "closed"
        state = await repo.load("r1")
        assert state["state"]["phase"] == "closed" and state["status"] == "disarmed"
    finally:
        await repo.engine.position_manager.stop()


async def test_working_partial_growth_and_terminal_handoff_keep_one_campaign(repo):
    await setup_entry(repo, status="PARTIALLY_FILLED", filled=1)
    repo.engine.orders.script[101] = {"status": "ACCEPTED"}
    try:
        first = await reconcile_entry_fills(repo.engine, "r1")
        p = repo.engine.position_manager.get(first["positionId"])
        assert p.policy["cartel"]["entryPending"] and p.legs[0].qty == 1
        assert (await repo.load("r1"))["state"]["phase"] == "entry_protected"
        async with repo.engine.sf() as session, session.begin():
            order = await session.get(Order, "o1")
            order.filled_qty, order.avg_fill_price, order.status = 2, 49., "FILLED"
            holding = await session.scalar(select(Position).where(Position.portfolio_id == "pf"))
            holding.qty, holding.avg_cost = 2, 49.
        await repo.engine.positions.load()
        a, b = await asyncio.gather(reconcile_entry_fills(repo.engine, "r1"), reconcile_entry_fills(repo.engine, "r1"))
        assert a["positionId"] == b["positionId"] == first["positionId"]
        assert p.legs[0].qty == 2 and p.legs[0].avg_fill == 49.
        assert p.policy["cartel"]["initialQty"] == 2 and not p.policy["cartel"]["entryPending"]
        assert p.policy["cartel"]["state"]["remaining_qty"] == 2
        assert (await repo.load("r1"))["state"]["phase"] == "managed"
        assert [i.qty for i in repo.engine.orders.placed] == [1, 2]
        assert all(i.reduce_only for i in repo.engine.orders.placed)
    finally:
        await repo.engine.position_manager.stop()


async def test_quantity_persistence_serializes_concurrent_exit_fill(repo, monkeypatch):
    await setup_entry(repo, status="PARTIALLY_FILLED", filled=1)
    manager = repo.engine.position_manager
    first = await reconcile_entry_fills(repo.engine, "r1")
    await manager.stop()
    p = manager.get(first["positionId"])
    p.exits.append({"kind": "manual", "leg": "HOOD", "qty": 1, "orderId": "exit1",
                    "filledQty": 0, "status": "ACCEPTED"})
    manager._register_exit_order(p, "exit1")
    async with repo.engine.sf() as session, session.begin():
        order = await session.get(Order, "o1")
        order.filled_qty, order.avg_fill_price, order.status = 2, 49., "FILLED"
        holding = await session.scalar(select(Position).where(Position.portfolio_id == "pf"))
        holding.qty = 2
    await repo.engine.positions.load()
    entered, release, attempted = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = manager._persist
    async def slow(position):
        if position.policy["cartel"]["initialQty"] == 2 and not entered.is_set():
            entered.set()
            await release.wait()
        await original(position)
    monkeypatch.setattr(manager, "_persist", slow)
    async def exit_fill():
        attempted.set()
        await manager.on_order_update({"id": "exit1", "symbol": "HOOD", "status": "FILLED",
                                       "filledQty": 1, "avgFillPrice": 50.})
    growth = asyncio.create_task(reconcile_entry_fills(repo.engine, "r1"))
    fill = None
    try:
        await asyncio.wait_for(entered.wait(), 5)
        fill = asyncio.create_task(exit_fill())
        await asyncio.wait_for(attempted.wait(), 5)
        assert not fill.done() and p.legs[0].qty == 2
        release.set()
        await asyncio.wait_for(asyncio.gather(growth, fill), 10)
        assert p.legs[0].qty == 1 and p.policy["cartel"]["state"]["remaining_qty"] == 1
        assert p.policy["cartel"]["state"]["sold"] == {"manual": 1}
        async with repo.engine.sf() as session:
            saved = await session.get(ManagedPositionRow, p.id)
        assert saved.legs[0]["qty"] == 1
    finally:
        release.set()
        await asyncio.gather(growth, *([fill] if fill else []), return_exceptions=True)
        await manager.stop()


async def test_failed_quantity_save_rolls_back_memory_and_retry_adds_units_once(repo, monkeypatch):
    await setup_entry(repo, status="PARTIALLY_FILLED", filled=1)
    manager = repo.engine.position_manager
    first = await reconcile_entry_fills(repo.engine, "r1")
    await manager.stop()
    p = manager.get(first["positionId"])
    original = manager._persist
    async with repo.engine.sf() as session, session.begin():
        order = await session.get(Order, "o1")
        order.filled_qty, order.avg_fill_price, order.status = 2, 49., "FILLED"
        holding = await session.scalar(select(Position).where(Position.portfolio_id == "pf"))
        holding.qty = 2
    await repo.engine.positions.load()
    async def unavailable(position):
        raise OSError("quantity save unavailable")
    monkeypatch.setattr(manager, "_persist", unavailable)
    with pytest.raises(OSError, match="quantity save"):
        await reconcile_entry_fills(repo.engine, "r1")
    assert p.legs[0].qty == 1 and p.policy["cartel"]["initialQty"] == 1
    assert (await repo.load("r1"))["state"]["adoptedEntryQty"] == 1
    assert len(repo.engine.orders.placed) == 1
    monkeypatch.setattr(manager, "_persist", original)
    try:
        await reconcile_entry_fills(repo.engine, "r1")
        await reconcile_entry_fills(repo.engine, "r1")
        assert p.legs[0].qty == 2 and p.policy["cartel"]["initialQty"] == 2
    finally:
        await manager.stop()
