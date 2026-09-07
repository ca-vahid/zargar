"""Cancel acknowledgements come from persisted order state, never response optimism."""
import asyncio

import pytest

from zargar.models import Order
from zargar.techniques.options_cartel.settlement import settle_entry

from .test_options_cartel_adoption import repo as _repo_fixture
from .test_options_cartel_adoption import setup_entry
from .test_position_chaos import FakeOrders

repo = _repo_fixture


@pytest.fixture(autouse=True)
async def stop_manager(repo):
    yield
    await repo.engine.position_manager.stop()


class CancellationOrders(FakeOrders):
    def __init__(self, engine, outcome):
        super().__init__()
        self.engine, self.outcome = engine, outcome
        self.n = 100
        self.script[100] = {"status": "ACCEPTED"}

    async def cancel(self, oid):
        self.cancelled.append(oid)
        if self.outcome == "error":
            raise ConnectionError("cancel unavailable")
        if self.outcome == "ack":
            async with self.engine.sf() as session:
                order = await session.get(Order, oid)
                order.status = "CANCELLED"
                await session.commit()
        return {"id": oid, "status": "CANCELLED"}  # deliberately optimistic in the unconfirmed case


async def test_unconfirmed_cancel_protects_partial_without_resubmitting_entry(repo):
    await setup_entry(repo, status="PARTIALLY_FILLED", filled=1)
    orders = repo.engine.orders = CancellationOrders(repo.engine, "unconfirmed")
    result = await settle_entry(repo.engine, "r1", wait_seconds=0)
    assert result["status"] == "cancel_pending" and not result["needsProtection"]
    p = repo.engine.position_manager.get(result["protection"]["positionId"])
    assert p.legs[0].qty == 1 and p.policy["cartel"]["entryPending"]
    await settle_entry(repo.engine, "r1", wait_seconds=0)
    assert orders.cancelled == ["o1"]
    assert len(orders.placed) == 1 and orders.placed[0].reduce_only


async def test_confirmed_cancel_adopts_actual_partial_once(repo):
    await setup_entry(repo, status="PARTIALLY_FILLED", filled=1)
    orders = repo.engine.orders = CancellationOrders(repo.engine, "ack")
    try:
        a, b = await asyncio.gather(settle_entry(repo.engine, "r1", wait_seconds=1),
                                    settle_entry(repo.engine, "r1", wait_seconds=1))
        assert a["adoption"]["positionId"] == b["adoption"]["positionId"]
        assert a["filledQty"] == 1 and a["status"] == "managed"
        assert orders.cancelled == ["o1"]
    finally:
        await repo.engine.position_manager.stop()


async def test_zero_fill_cancellation_closes_plan_without_position(repo):
    await setup_entry(repo, status="ACCEPTED", filled=0)
    repo.engine.orders = CancellationOrders(repo.engine, "ack")
    result = await settle_entry(repo.engine, "r1", request_cancel=True, wait_seconds=0)
    assert result["status"] == "closed_unfilled"
    assert (await repo.load("r1"))["status"] == "disarmed"
    assert repo.engine.position_manager.positions() == []


async def test_cancel_failure_exposes_partial_risk(repo):
    await setup_entry(repo, status="PARTIALLY_FILLED", filled=1)
    repo.engine.orders = CancellationOrders(repo.engine, "error")
    result = await settle_entry(repo.engine, "r1", wait_seconds=0)
    assert not result["needsProtection"] and result["status"] == "cancel_pending"
    assert "ConnectionError" in (await repo.load("r1"))["state"]["cancelError"]


async def test_unfilled_working_entry_is_left_alone_without_cancel_request(repo):
    await setup_entry(repo, status="ACCEPTED", filled=0)
    orders = repo.engine.orders = CancellationOrders(repo.engine, "ack")
    result = await settle_entry(repo.engine, "r1", wait_seconds=0)
    assert result["status"] == "working" and orders.cancelled == []
