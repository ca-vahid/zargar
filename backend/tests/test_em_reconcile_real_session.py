"""FIX-01 reconciliation on a REAL AsyncSession (closure review 2026-09-14: test-harness cleanup).

The five direct-function cases in `tests/test_em_review_da_reconcile.py` ran the tool on a minimal fake
session; the production tool carried branches (projection arithmetic, journal-before-commit, no row lock)
that existed only to keep those green. Those branches are gone. This file is the real-session equivalent,
on the repository's own test database (any `ZARGAR_TEST_DATABASE_URL`); the reviewer's own Postgres cases
(`tests/test_reconcile_postgres_atomicity.py`, restricted to zargar_test_codex) remain the failure-mode
authority.

Coverage map (historical case -> here):
- test_apply_produces_an_orm_tracked_json_update      -> test_real_apply_persists_the_corrected_state
- test_apply_updates_the_plan_aggregate_alongside_the_trade -> test_real_apply_persists_the_corrected_state
- test_two_corrections_for_one_plan_do_not_invalidate_each_other -> test_real_two_corrections_commit_as_one_row_transition
- test_audit_failure_does_not_leave_a_committed_unjournaled_correction -> test_real_receipt_failure_rolls_back_the_state
- test_replay_of_a_corrected_list_trade_is_not_reported_as_a_conflict -> test_real_exact_replay_is_already_applied_not_a_conflict
"""
from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.conftest import TEST_DB_URL
from zargar.bus import Bus
from zargar.db import make_engine, make_session_factory
from zargar.models import Event, Execution, Order, Portfolio, TechniqueArmed
from zargar.tools.em_reconcile_fallback import CORRECTION_KIND, apply, build_manifest

pytestmark = pytest.mark.usefixtures("fresh_db")


async def _seed(sf, *, n=1, tag="plan"):
    run_id, pid = f"real-{tag}", f"book-{tag}"
    trades = []
    async with sf() as session:
        session.add(Portfolio(id=pid, name="EM reconcile real-session", kind="sim", starting_cash=10000.0, cash=10000.0))
        await session.flush()
        for i in range(n):
            entry_id, exit_id = f"{tag}-entry-{i}", f"{tag}-exit-{i}"
            session.add_all([
                Order(id=entry_id, portfolio_id=pid, symbol="TEST", sec_type="STK", side="BUY", qty=1.0, order_type="LMT",
                      status="FILLED", filled_qty=1.0, avg_fill_price=100.0, source="technique", technique="enhanced_market"),
                Order(id=exit_id, portfolio_id=pid, symbol="TEST", sec_type="STK", side="SELL", qty=1.0, order_type="MKT",
                      status="FILLED", filled_qty=1.0, avg_fill_price=99.0, source="technique", technique="enhanced_market"),
            ])
            await session.flush()
            session.add_all([
                Execution(id=f"{tag}-buy-{i}", order_id=entry_id, portfolio_id=pid, symbol="TEST", side="BUY", qty=1.0, price=100.0, commission=0.0),
                Execution(id=f"{tag}-sell-{i}", order_id=exit_id, portfolio_id=pid, symbol="TEST", side="SELL", qty=1.0, price=99.0, commission=0.0),
            ])
            trades.append({"triggerId": f"b{i + 1}", "instrument": "shares", "multiplier": 100.0, "avgFill": 100.0,
                           "filledQty": 1.0, "entryOrderId": entry_id, "realizedPnl": -100.0,
                           "exits": [{"orderId": exit_id, "kind": "stop", "filledQty": 1.0, "price": 99.0, "status": "FILLED"}]})
        initial = {"trades": trades, "realizedPnl": -100.0 * n}          # a LIST of trades, as the runtime persists them
        session.add(TechniqueArmed(run_id=run_id, symbol="TEST", portfolio_id=pid, technique="enhanced_market", mode="auto",
                                   status="disarmed", plan_for="2026-09-14", config={"dailyLossLimit": 50.0}, state=initial))
        await session.commit()
    return run_id, copy.deepcopy(initial)


async def _read(sf, run_id):
    async with sf() as session:
        row = await session.get(TechniqueArmed, run_id)
        receipts = (await session.execute(select(Event).where(Event.aggregate_id == run_id, Event.type == CORRECTION_KIND)
                                          .order_by(Event.id))).scalars().all()
        return copy.deepcopy(row.state), [copy.deepcopy(e.payload) for e in receipts]


def _engine(db, sf):
    return SimpleNamespace(db=db, sf=sf, bus=Bus())


async def _manifest(eng, run_id):
    complete = await build_manifest(eng)
    return {**complete, "items": [i for i in complete["items"] if i["runId"] == run_id]}


def test_real_apply_persists_the_corrected_state():
    async def scenario():
        db = make_engine(TEST_DB_URL); sf = make_session_factory(db)
        try:
            run_id, initial = await _seed(sf, tag="single")
            eng = _engine(db, sf)
            manifest = await _manifest(eng, run_id)
            assert len(manifest["items"]) == 1 and manifest["items"][0]["evidence"] == "ledger"
            assert await apply(eng, manifest) == 1
            state, receipts = await _read(sf, run_id)
            assert state != initial, "a fresh read must see the new state (the ORM tracked the change)"
            assert state["trades"][0]["multiplier"] == 1.0 and state["trades"][0]["realizedPnl"] == -1.0
            assert state["realizedPnl"] == -1.0, "the plan aggregate reconciles with the corrected trade"
            assert len(receipts) == 1 and receipts[0]["trigger"] == "b1" and receipts[0]["new"]["realizedPnl"] == -1.0
        finally:
            await db.dispose()
    asyncio.run(scenario())


def test_real_two_corrections_commit_as_one_row_transition():
    async def scenario():
        db = make_engine(TEST_DB_URL); sf = make_session_factory(db)
        try:
            run_id, _ = await _seed(sf, n=2, tag="pair")
            eng = _engine(db, sf)
            manifest = await _manifest(eng, run_id)
            assert len(manifest["items"]) == 2
            assert await apply(eng, manifest) == 2, "both items share one original row hash and commit as one transition"
            state, receipts = await _read(sf, run_id)
            assert [t["multiplier"] for t in state["trades"]] == [1.0, 1.0]
            assert state["realizedPnl"] == -2.0
            assert sorted(r["trigger"] for r in receipts) == ["b1", "b2"]
        finally:
            await db.dispose()
    asyncio.run(scenario())


class ReceiptCommitFailure(AsyncSession):
    """The commit that would carry a correction receipt fails - the whole transition must roll back."""
    async def commit(self):
        if any(isinstance(r, Event) and r.type == CORRECTION_KIND for r in self.new):
            raise RuntimeError("audit write unavailable")
        await super().commit()


def test_real_receipt_failure_rolls_back_the_state():
    async def scenario():
        db = make_engine(TEST_DB_URL); sf = make_session_factory(db)
        try:
            run_id, initial = await _seed(sf, tag="fail")
            manifest = await _manifest(_engine(db, sf), run_id)
            failing = async_sessionmaker(db, class_=ReceiptCommitFailure, expire_on_commit=False)
            with pytest.raises(RuntimeError, match="audit write unavailable"):
                await apply(_engine(db, failing), manifest)
            state, receipts = await _read(sf, run_id)
            assert state == initial, "state and receipt are one transaction: a failed receipt leaves the state untouched"
            assert receipts == []
            # the exact retry on a healthy session then applies once
            assert await apply(_engine(db, sf), manifest) == 1
            state, receipts = await _read(sf, run_id)
            assert state["trades"][0]["multiplier"] == 1.0 and len(receipts) == 1
        finally:
            await db.dispose()
    asyncio.run(scenario())


def test_real_exact_replay_is_already_applied_not_a_conflict(capsys):
    async def scenario():
        db = make_engine(TEST_DB_URL); sf = make_session_factory(db)
        try:
            run_id, _ = await _seed(sf, tag="replay")
            eng = _engine(db, sf)
            manifest = await _manifest(eng, run_id)
            assert await apply(eng, manifest) == 1
            capsys.readouterr()
            assert await apply(eng, manifest) == 0
            out = capsys.readouterr().out
            assert "already_applied" in out and "REFUSE" not in out, "a committed receipt + corrected state is a replay, not a conflict"
            _, receipts = await _read(sf, run_id)
            assert len(receipts) == 1, "the replay wrote no second receipt"
        finally:
            await db.dispose()
    asyncio.run(scenario())
