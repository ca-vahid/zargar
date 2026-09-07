"""Cross-instance row-lock races and crash recovery on real PostgreSQL."""
import asyncio

import pytest
from sqlalchemy import func, select

from zargar.engine import Engine
from zargar.models import Order, Portfolio, TechniqueArmed, TechniqueRun
from zargar.orders import OrderIntent
from zargar.techniques.options_cartel.state import ArmRepository

from .conftest import make_test_config
from .test_options_cartel_entry import OPEN, plan


@pytest.fixture
async def repo(fresh_db):
    engine = Engine(make_test_config())
    p = plan(id="r1")
    async with engine.sf() as session:
        session.add(Portfolio(id="pf", name="test", kind="sim", base_currency="USD", cash=10000))
        session.add(TechniqueRun(id=p.id, technique="options_cartel", symbol=p.symbol, mode="plan",
                                 status="done", result={"plan": p.snapshot()}))
        await session.commit()
    yield ArmRepository(engine)
    await engine.db.dispose()


def signal():
    return {"id": f"r1:entry:{OPEN+300000}", "at": OPEN+300000,
            "referencePrice": 48.9, "stop": 48.4, "risk": .5, "targets": [55], "direction": "long"}


def intent():
    return OrderIntent(portfolio_id="pf", symbol="HOOD", side="BUY", qty=2, order_type="LMT",
                       limit_price=49, technique_id="options_cartel", source="technique")


async def ready(repo, mode="auto"):
    await repo.arm("r1", "pf", mode, {"test": True}, now_ms=OPEN)
    assert await repo.consume_signal("r1", signal(), now_ms=OPEN+300000)


async def test_concurrent_arms_create_one_record_without_resetting_state(repo):
    other = ArmRepository(repo.engine)
    a, b = await asyncio.gather(repo.arm("r1", "pf", "auto", {}, now_ms=OPEN),
                                other.arm("r1", "pf", "auto", {}, now_ms=OPEN))
    assert a == b
    assert await repo.consume_signal("r1", signal(), now_ms=OPEN+300000)
    retry = await other.arm("r1", "pf", "auto", {}, now_ms=OPEN)
    assert retry["state"]["phase"] == "signalled"
    async with repo.engine.sf() as session:
        assert await session.scalar(select(func.count()).select_from(TechniqueArmed)) == 1


async def test_concurrent_callbacks_consume_and_reserve_only_once(repo):
    await repo.arm("r1", "pf", "auto", {}, now_ms=OPEN)
    results = await asyncio.gather(*(ArmRepository(repo.engine).consume_signal("r1", signal(), now_ms=OPEN+300000)
                                     for _ in range(3)))
    assert results.count(True) == 1
    reservations = await asyncio.gather(*(ArmRepository(repo.engine).reserve_submission("r1", intent()) for _ in range(3)))
    assert sum(r is not None for r in reservations) == 1
    row = await ArmRepository(repo.engine).load("r1")
    assert row["state"]["phase"] == "submitting"
    assert row["state"]["attemptTag"] in next(r for r in reservations if r).tags


async def test_ambiguous_crash_before_order_is_not_permission_to_resubmit(repo):
    await ready(repo)
    await repo.reserve_submission("r1", intent())
    restored = ArmRepository(repo.engine)
    result = await restored.reconcile_submission("r1")
    assert result["state"]["phase"] == "needs_attention"
    assert await restored.reserve_submission("r1", intent()) is None


async def insert_order(repo, reservation, *, oid="o1", **overrides):
    values = {k: getattr(reservation, k) for k in ("portfolio_id", "symbol", "side", "qty", "sec_type", "order_type", "limit_price", "tags")}
    values.update(technique="options_cartel", source="technique", status="PARTIALLY_FILLED", filled_qty=1, avg_fill_price=48.95)
    values.update(overrides)
    async with repo.engine.sf() as session:
        session.add(Order(id=oid, **values))
        await session.commit()


async def test_crash_after_order_write_recovers_exact_order_and_real_filled_quantity(repo):
    await ready(repo)
    reservation = await repo.reserve_submission("r1", intent())
    await insert_order(repo, reservation)
    restored = await ArmRepository(repo.engine).reconcile_submission("r1")
    assert restored["state"]["orderId"] == "o1" and restored["state"]["filledQty"] == 1
    assert restored["state"]["intent"]["qty"] == 2  # never mistaken for filled qty
    assert await repo.reserve_submission("r1", intent()) is None


@pytest.mark.parametrize("mismatch", ["symbol", "duplicates", "technique"])
async def test_ambiguous_or_foreign_orders_cannot_be_adopted(repo, mismatch):
    await ready(repo)
    reservation = await repo.reserve_submission("r1", intent())
    if mismatch == "duplicates":
        await insert_order(repo, reservation)
        await insert_order(repo, reservation, oid="o2")
    else:
        await insert_order(repo, reservation, **{mismatch: "OTHER"})
    assert (await repo.reconcile_submission("r1"))["state"]["phase"] == "needs_attention"


async def test_disarm_preserves_pending_exposure_for_recovery(repo):
    await ready(repo)
    reservation = await repo.reserve_submission("r1", intent())
    row = await repo.set_status("r1", "disarmed")
    assert row["status"] == "closing" and row["state"]["retireTo"] == "disarmed"
    await insert_order(repo, reservation)
    row = await repo.reconcile_submission("r1")
    assert row["status"] == "closing" and row["state"]["filledQty"] == 1
    with pytest.raises(ValueError, match="closing exposure"):
        await repo.set_status("r1", "paused")


async def test_pause_and_retirement_block_consumption_and_cannot_reset(repo):
    await repo.arm("r1", "pf", "alert", {}, now_ms=OPEN)
    await repo.set_status("r1", "paused")
    assert not await repo.consume_signal("r1", signal(), now_ms=OPEN+300000)
    await repo.set_status("r1", "armed")
    await repo.set_status("r1", "disarmed")
    for status in ("paused", "armed"):
        with pytest.raises(ValueError, match="retired"):
            await repo.set_status("r1", status)
    assert not await repo.consume_signal("r1", signal(), now_ms=OPEN+300000)


async def test_alert_cannot_reserve_and_ownership_cannot_change(repo):
    await ready(repo, mode="alert")
    with pytest.raises(ValueError, match="alert"):
        await repo.reserve_submission("r1", intent())
    with pytest.raises(ValueError, match="silently replaced"):
        await repo.arm("r1", "pf", "auto", {}, now_ms=OPEN)


async def test_foreign_records_and_old_signals_rejected(repo):
    assert await repo.load("foreign") is None
    await repo.arm("r1", "pf", "alert", {}, now_ms=OPEN+600000)
    with pytest.raises(ValueError, match="predates"):
        await repo.consume_signal("r1", signal(), now_ms=OPEN+600000)
    assert not await repo.consume_signal("r1", signal(), now_ms=OPEN+86400000)
