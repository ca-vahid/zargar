"""Real PostgreSQL checks for the Delivery A reconciliation follow-up.

Run sequentially through scripts/test-codex.ps1 with the reviewed backend on
PYTHONPATH. This module refuses every database except zargar_test_codex on
loopback:5433. It starts no Engine, broker, scheduler, or application service.
The production build_manifest/apply and production Journal perform all writes.
Only uniquely named test rows are inserted/deleted; no runtime DB access occurs.
"""

import asyncio
import copy
import os
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zargar.bus import Bus
from zargar.db import make_engine, make_session_factory
from zargar.events import Journal
from zargar.models import Base, Event, Execution, Order, Portfolio, TechniqueArmed
from zargar.tools.em_reconcile_fallback import CORRECTION_KIND, apply, build_manifest


def _safe_database_url():
    raw = os.environ.get("ZARGAR_TEST_DATABASE_URL")
    assert raw, "Run with scripts/test-codex.ps1; no default database is permitted"
    url = make_url(raw)
    assert url.drivername == "postgresql+asyncpg"
    assert url.host in {"127.0.0.1", "localhost", "::1"}
    assert url.port == 5433 and url.database == "zargar_test_codex", (
        "These write tests are restricted to the disposable Codex database"
    )
    return raw


@asynccontextmanager
async def _case(*, n=1, status="disarmed", projected_exit=99.0, fee=0.0):
    db = make_engine(_safe_database_url())
    sf = make_session_factory(db)
    token = uuid.uuid4().hex
    run_id = "review-reconcile-" + token
    portfolio_id = "review-book-" + token
    order_ids = []
    try:
        async with db.begin() as conn:
            await conn.run_sync(lambda sync: Base.metadata.create_all(
                sync, tables=[Portfolio.__table__, Order.__table__,
                              Execution.__table__, TechniqueArmed.__table__, Event.__table__]
            ))
        trades = []
        async with sf() as session:
            session.add(Portfolio(id=portfolio_id, name="EM reconciliation test",
                                  kind="sim", starting_cash=10000.0, cash=10000.0))
            await session.flush()
            for i in range(n):
                tid = f"b{i + 1}"
                entry_id = f"review-entry-{i}-" + token
                exit_id = f"review-exit-{i}-" + token
                order_ids.extend([entry_id, exit_id])
                session.add_all([
                    Order(id=entry_id, portfolio_id=portfolio_id, symbol="TEST", sec_type="STK",
                          side="BUY", qty=1.0, order_type="LMT", status="FILLED",
                          filled_qty=1.0, avg_fill_price=100.0, source="technique", technique="enhanced_market"),
                    Order(id=exit_id, portfolio_id=portfolio_id, symbol="TEST", sec_type="STK",
                          side="SELL", qty=1.0, order_type="MKT", status="FILLED",
                          filled_qty=1.0, avg_fill_price=99.0, source="technique", technique="enhanced_market"),
                ])
                await session.flush()
                session.add_all([
                    Execution(id=f"review-buy-{i}-" + token, order_id=entry_id,
                              portfolio_id=portfolio_id, symbol="TEST", side="BUY",
                              qty=1.0, price=100.0, commission=fee),
                    Execution(id=f"review-sell-{i}-" + token, order_id=exit_id,
                              portfolio_id=portfolio_id, symbol="TEST", side="SELL",
                              qty=1.0, price=99.0, commission=fee),
                ])
                trades.append({
                    "triggerId": tid, "instrument": "shares", "multiplier": 100.0,
                    "avgFill": 100.0, "filledQty": 1.0, "entryOrderId": entry_id,
                    "realizedPnl": (projected_exit - 100.0) * 100.0,
                    "exits": [{"orderId": exit_id, "kind": "stop", "filledQty": 1.0,
                               "price": projected_exit, "status": "FILLED"}],
                })
            initial = {"trades": trades, "realizedPnl": sum(t["realizedPnl"] for t in trades)}
            session.add(TechniqueArmed(
                run_id=run_id, symbol="TEST", portfolio_id=portfolio_id,
                technique="enhanced_market", mode="auto", status=status,
                plan_for="2026-09-14", config={"dailyLossLimit": 50.0}, state=initial,
            ))
            await session.commit()
        eng = SimpleNamespace(db=db, sf=sf, bus=Bus())
        eng.journal = Journal(sf, eng.bus)
        complete = await build_manifest(eng)
        manifest = {**complete, "items": [i for i in complete["items"] if i["runId"] == run_id]}
        assert len(manifest["items"]) == n
        yield SimpleNamespace(eng=eng, sf=sf, run_id=run_id, portfolio_id=portfolio_id,
                              initial=copy.deepcopy(initial), manifest=manifest)
    finally:
        async with sf() as session:
            await session.execute(delete(Event).where(Event.aggregate_id == run_id))
            await session.execute(delete(TechniqueArmed).where(TechniqueArmed.run_id == run_id))
            if order_ids:
                await session.execute(delete(Execution).where(Execution.order_id.in_(order_ids)))
                await session.execute(delete(Order).where(Order.id.in_(order_ids)))
            await session.execute(delete(Portfolio).where(Portfolio.id == portfolio_id))
            await session.commit()
        await db.dispose()


async def _read(case):
    async with case.sf() as session:
        row = await session.get(TechniqueArmed, case.run_id)
        events = (await session.execute(select(Event).where(
            Event.aggregate_id == case.run_id, Event.type == CORRECTION_KIND
        ).order_by(Event.id))).scalars().all()
        return copy.deepcopy(row.state), [copy.deepcopy(e.payload) for e in events]


class ProjectionCommitFailure(AsyncSession):
    async def commit(self):
        if any(isinstance(row, TechniqueArmed) for row in self.dirty):
            raise RuntimeError("injected projection commit failure")
        await super().commit()


class SecondReceiptFailure(AsyncSession):
    async def commit(self):
        if any(isinstance(row, Event) and row.type == CORRECTION_KIND
               and (row.payload or {}).get("trigger") == "b2" for row in self.new):
            raise RuntimeError("injected second receipt failure")
        await super().commit()


def test_postgres_grouped_roundtrip_and_exact_retry_control():
    async def scenario():
        async with _case(n=2) as c:
            assert await apply(c.eng, c.manifest) == 2
            state, events = await _read(c)
            assert [t["multiplier"] for t in state["trades"]] == [1.0, 1.0]
            assert state["realizedPnl"] == -2.0
            assert len(events) == 2
            assert await apply(c.eng, c.manifest) == 0
            assert (await _read(c))[1] == events
    asyncio.run(scenario())


def test_postgres_state_commit_failure_rolls_back_correction_receipts():
    async def scenario():
        async with _case(n=2) as c:
            # Actual Journal retains its own real session factory, exactly as in Engine.
            c.eng.sf = async_sessionmaker(c.eng.db, class_=ProjectionCommitFailure,
                                         expire_on_commit=False)
            with pytest.raises(RuntimeError, match="projection commit failure"):
                await apply(c.eng, c.manifest)
            state, events = await _read(c)
            assert state == c.initial
            assert events == [], "No correction receipt may survive a rolled-back plan transition"
    asyncio.run(scenario())


def test_postgres_retry_after_commit_failure_does_not_duplicate_receipts():
    async def scenario():
        async with _case(n=2) as c:
            c.eng.sf = async_sessionmaker(c.eng.db, class_=ProjectionCommitFailure,
                                         expire_on_commit=False)
            with pytest.raises(RuntimeError, match="projection commit failure"):
                await apply(c.eng, c.manifest)
            c.eng.sf = c.sf
            assert await apply(c.eng, c.manifest) == 2
            state, events = await _read(c)
            assert state["realizedPnl"] == -2.0
            assert len(events) == 2, "A failed attempt must not leave extra durable correction receipts"
    asyncio.run(scenario())


def test_postgres_second_receipt_failure_rolls_back_first_receipt():
    async def scenario():
        async with _case(n=2) as c:
            failing_sf = async_sessionmaker(c.eng.db, class_=SecondReceiptFailure,
                                           expire_on_commit=False)
            c.eng.sf = failing_sf
            c.eng.journal = Journal(failing_sf, c.eng.bus)
            with pytest.raises(RuntimeError, match="second receipt failure"):
                await apply(c.eng, c.manifest)
            state, events = await _read(c)
            assert state == c.initial
            assert events == [], "Both trade receipts belong to the same atomic plan correction"
    asyncio.run(scenario())


@pytest.mark.parametrize("changed_field,changed_value", [
    ("portfolio_id", "different-book"), ("technique", "team2")
])
def test_postgres_changed_ownership_refuses_before_any_write(changed_field, changed_value):
    async def scenario():
        async with _case() as c:
            async with c.sf() as session:
                row = await session.get(TechniqueArmed, c.run_id)
                setattr(row, changed_field, changed_value)
                await session.commit()
            assert await apply(c.eng, c.manifest) == 0
            state, events = await _read(c)
            assert state == c.initial and events == []
    asyncio.run(scenario())


def test_postgres_manifest_verifies_execution_prices_and_all_commissions():
    async def scenario():
        # Ledger says -1 gross, 0.50 fees. The corrupted projection says -2 and
        # carries no exit commission fields. It must be corrected from the ledger
        # or explicitly excluded as an evidence conflict, not certified as -2/0.
        async with _case(projected_exit=98.0, fee=0.25) as c:
            item = c.manifest["items"][0]
            assert item["new"]["realizedPnl"] == -1.0, (
                "A repair manifest must be independently grounded in Order/Execution records"
            )
            assert item["commissions"] == 0.5, "Entry and exit commissions both count"
    asyncio.run(scenario())
