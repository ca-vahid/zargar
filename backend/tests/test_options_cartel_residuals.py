"""Late fill ranges, durable exit attempts, and restart recovery of residuals."""
import asyncio

import pytest
from sqlalchemy import select

from zargar.execution.positions import PositionManager
from zargar.models import ManagedPositionRow, Order, Position
from zargar.techniques.options_cartel.adoption import reconcile_entry_fills
from zargar.techniques.options_cartel.position_adapter import register_cartel_policy
from zargar.techniques.options_cartel.residuals import drain_residual
from zargar.techniques.options_cartel.settlement import settle_entry

from .test_options_cartel_adoption import repo as _repo_fixture
from .test_options_cartel_adoption import setup_entry
from .test_position_chaos import FakeOrders

repo = _repo_fixture


@pytest.fixture(autouse=True)
async def stop_manager(repo):
    yield
    await repo.engine.position_manager.stop()


async def closed_primary(repo):
    await setup_entry(repo, status="PARTIALLY_FILLED", filled=1)
    first = await reconcile_entry_fills(repo.engine, "r1")
    manager = repo.engine.position_manager
    await manager.stop()
    await manager.close(first["positionId"], force_market=True, reason="synthetic stop before entry cancellation")
    async with repo.engine.sf() as session:
        assert (await session.get(ManagedPositionRow, first["positionId"])).status == "closed"
    return first["positionId"]


async def late_fill(repo, *, total=2, held=1, status="FILLED"):
    async with repo.engine.sf() as session, session.begin():
        order = await session.get(Order, "o1")
        order.qty = total
        order.filled_qty, order.avg_fill_price, order.status = total, 49., status
        # The reserved quantity normally covers the late fill. Synthetic tests
        # extend it when exercising more than one late report.
        from zargar.models import TechniqueArmed
        armed = await session.get(TechniqueArmed, "r1")
        armed.state = {**armed.state, "intent": {**armed.state["intent"], "qty": total}}
        holding = await session.scalar(select(Position).where(Position.portfolio_id == "pf"))
        holding.qty, holding.avg_cost = held, 49.
    await repo.engine.positions.load()


async def test_late_fill_closes_separate_residual_without_reopening_primary(repo):
    primary = await closed_primary(repo)
    await late_fill(repo)
    before = len(repo.engine.orders.placed)
    a, b = await asyncio.gather(reconcile_entry_fills(repo.engine, "r1"), reconcile_entry_fills(repo.engine, "r1"))
    assert a["residualPositionIds"] == b["residualPositionIds"]
    assert a["status"] == "closed"
    assert len(repo.engine.orders.placed) == before+1
    exit_intent = repo.engine.orders.placed[-1]
    assert exit_intent.side == "SELL" and exit_intent.qty == 1 and exit_intent.reduce_only
    async with repo.engine.sf() as session:
        assert (await session.get(ManagedPositionRow, primary)).status == "closed"
        residual = await session.get(ManagedPositionRow, a["residualPositionIds"][0])
    assert residual.status == "closed" and residual.config["policy"]["cartel"]["residualOf"] == primary
    assert residual.legs[0]["avgFill"] == pytest.approx(49.05)
    await late_fill(repo, total=3, held=1)
    again = await reconcile_entry_fills(repo.engine, "r1")
    assert len(again["residualPositionIds"]) == 2
    assert len(repo.engine.orders.placed) == before+2
    assert (await repo.load("r1"))["state"]["adoptedEntryQty"] == 3


class PersistedExits(FakeOrders):
    def __init__(self, engine, status="ACCEPTED", *, lose_response=False):
        super().__init__()
        self.engine, self.status, self.lose_response = engine, status, lose_response
        self.n = 800

    async def place(self, intent):
        self.placed.append(intent)
        oid = f"residual-exit-{self.n}"
        self.n += 1
        async with self.engine.sf() as session, session.begin():
            session.add(Order(id=oid, portfolio_id=intent.portfolio_id, technique=intent.technique_id,
                              symbol=intent.symbol, sec_type=intent.sec_type, side=intent.side,
                              qty=intent.qty, order_type=intent.order_type, limit_price=intent.limit_price,
                              tags=list(intent.tags), status=self.status, filled_qty=0))
        if self.lose_response:
            raise ConnectionError("response lost after order persisted")
        return {"id": oid, "status": self.status, "filledQty": 0}


async def test_lost_exit_response_reconciles_before_retry_and_survives_restart(repo, monkeypatch):
    primary = await closed_primary(repo)
    await late_fill(repo)
    orders = repo.engine.orders = PersistedExits(repo.engine, lose_response=True)
    result = await reconcile_entry_fills(repo.engine, "r1")
    residual_id = result["residualPositionIds"][0]
    p = repo.engine.position_manager.get(residual_id)
    assert p.exits[0]["status"] == "ERROR" and p.exits[0]["orderId"] is None
    await repo.engine.position_manager.stop()
    async def ensure(symbol):
        return None
    monkeypatch.setattr(repo.engine, "ensure_symbol", ensure)
    repo.engine.position_manager = PositionManager(repo.engine)
    register_cartel_policy(repo.engine)
    await repo.engine.position_manager.restore()
    manager = repo.engine.position_manager
    p = manager.get(residual_id)
    await drain_residual(manager, p)
    assert len(orders.placed) == 1 and p.exits[0]["orderId"] == "residual-exit-800"
    assert p.exits[0]["status"] == "ACCEPTED"
    manager._now = lambda: (p.exits[0]["ts"]+1_000_000)/1000
    await manager._watch_once()  # beyond the generic TTL: unknown/working is still not retryable
    assert len(orders.placed) == 1
    async with repo.engine.sf() as session, session.begin():
        order = await session.get(Order, "residual-exit-800")
        order.status, order.filled_qty, order.avg_fill_price = "CANCELLED", 1, 48.5
    await drain_residual(manager, p)
    assert p.status == "closed" and p.legs[0].qty == 0
    result = await reconcile_entry_fills(repo.engine, "r1")
    assert result["status"] == "closed" and result["positionId"] == primary


async def test_interrupted_residual_binding_reuses_persisted_fill_range(repo, monkeypatch):
    await closed_primary(repo)
    await late_fill(repo)
    manager = repo.engine.position_manager
    original = manager.adopt
    async def interrupted(spec):
        await original(spec)
        raise RuntimeError("crashed after residual persistence")
    monkeypatch.setattr(manager, "adopt", interrupted)
    with pytest.raises(RuntimeError, match="after residual"):
        await reconcile_entry_fills(repo.engine, "r1")
    monkeypatch.setattr(manager, "adopt", original)
    result = await reconcile_entry_fills(repo.engine, "r1")
    assert len(result["residualPositionIds"]) == 1
    async with repo.engine.sf() as session:
        rows = (await session.scalars(select(ManagedPositionRow))).all()
    assert len(rows) == 2  # original plus exactly one residual


async def test_zero_cumulative_fill_regression_cannot_close_managed_entry_as_unfilled(repo):
    await setup_entry(repo, status="PARTIALLY_FILLED", filled=1)
    await reconcile_entry_fills(repo.engine, "r1")
    async with repo.engine.sf() as session, session.begin():
        order = await session.get(Order, "o1")
        order.status, order.filled_qty = "CANCELLED", 0
    with pytest.raises(ValueError, match="regressed"):
        await settle_entry(repo.engine, "r1", wait_seconds=0)
    assert (await repo.load("r1"))["state"]["adoptedEntryQty"] == 1


async def test_fill_during_primary_close_does_not_cancel_or_resize_its_exit(repo):
    await setup_entry(repo, status="PARTIALLY_FILLED", filled=1)
    first = await reconcile_entry_fills(repo.engine, "r1")
    manager = repo.engine.position_manager
    await manager.stop()
    repo.engine.orders.script[101] = {"status": "ACCEPTED"}
    await manager.close(first["positionId"], force_market=True)
    primary = manager.get(first["positionId"])
    assert primary.status == "closing"
    original_exit = dict(primary.exits[-1])
    cancelled = list(repo.engine.orders.cancelled)
    await late_fill(repo, held=2)
    result = await reconcile_entry_fills(repo.engine, "r1")
    again = await reconcile_entry_fills(repo.engine, "r1")
    assert result["status"] == again["status"] == "closing"
    assert primary.legs[0].qty == 1 and primary.exits[-1] == original_exit
    assert repo.engine.orders.cancelled == cancelled
    assert [o.qty for o in repo.engine.orders.placed] == [1, 1, 1]  # original stop, primary exit, residual exit
    assert (await repo.load("r1"))["state"]["phase"] == "residual_closing"


async def test_confirmed_rejection_retries_after_delay_without_cancelling_working_order(repo):
    await closed_primary(repo)
    await late_fill(repo)
    orders = repo.engine.orders = PersistedExits(repo.engine, status="REJECTED")
    result = await reconcile_entry_fills(repo.engine, "r1")
    manager = repo.engine.position_manager
    await manager.stop()
    p = manager.get(result["residualPositionIds"][0])
    await drain_residual(manager, p)
    assert len(orders.placed) == 1
    manager._now = lambda: (p.exits[0]["ts"]+31_000)/1000
    orders.status = "ACCEPTED"
    await drain_residual(manager, p)
    assert len(orders.placed) == 2
    await drain_residual(manager, p)
    assert len(orders.placed) == 2 and orders.cancelled == []


async def test_unknown_submit_never_retries_even_after_generic_exit_ttl(repo):
    await closed_primary(repo)
    await late_fill(repo)
    orders = repo.engine.orders = FakeOrders()
    orders.script[0] = {"raise": True}
    result = await reconcile_entry_fills(repo.engine, "r1")
    manager = repo.engine.position_manager
    await manager.stop()
    p = manager.get(result["residualPositionIds"][0])
    manager._now = lambda: (p.exits[0]["ts"]+1_000_000)/1000
    await drain_residual(manager, p)
    await manager._watch_once()
    await manager.close(p.id, force_market=True)
    assert len(orders.placed) == 1
    assert any("outcome is unresolved" in message for message in p.attention)


async def test_unrestored_residual_prevents_allocating_another_fill_range(repo):
    await closed_primary(repo)
    await late_fill(repo)
    repo.engine.orders = PersistedExits(repo.engine)
    await reconcile_entry_fills(repo.engine, "r1")
    await repo.engine.position_manager.stop()
    repo.engine.position_manager = PositionManager(repo.engine)
    await late_fill(repo, total=3, held=2)
    with pytest.raises(RuntimeError, match="restore residual"):
        await reconcile_entry_fills(repo.engine, "r1")
    async with repo.engine.sf() as session:
        assert len((await session.scalars(select(ManagedPositionRow))).all()) == 2
