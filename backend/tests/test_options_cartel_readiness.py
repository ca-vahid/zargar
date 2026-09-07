"""Read-only persisted execution gates, including restart and account isolation."""
import pytest
from sqlalchemy import select

from zargar.execution.positions import PositionManager
from zargar.models import ManagedPositionRow, Order, TechniqueArmed, TechniqueRun
from zargar.techniques.options_cartel.adoption import reconcile_entry_fills
from zargar.techniques.options_cartel.execution import ExecutionInput, preflight
from zargar.techniques.options_cartel.plans import CartelPlan
from zargar.techniques.options_cartel.position_adapter import register_cartel_policy
from zargar.techniques.options_cartel.readiness import execution_readiness

from .test_options_cartel_adoption import repo as _repo_fixture
from .test_options_cartel_adoption import setup_entry

repo = _repo_fixture


@pytest.fixture(autouse=True)
async def stop_manager(repo):
    yield
    await repo.engine.position_manager.stop()


async def managed(repo):
    await setup_entry(repo)
    result = await reconcile_entry_fills(repo.engine, "r1")
    await repo.engine.position_manager.stop()
    return repo.engine.position_manager.get(result["positionId"])


async def test_healthy_resting_stop_is_ready_and_gate_does_not_mutate_state(repo):
    p = await managed(repo)
    before = p.to_dict()
    report = await execution_readiness(repo.engine, "pf", "HOOD")
    assert report["passed"] and report["blockers"] == [], report
    assert p.to_dict() == before


async def test_unknown_exit_is_scoped_to_this_book_and_underlying(repo):
    p = await managed(repo)
    p.exits.append({"kind": "close", "leg": "HOOD", "qty": 1, "orderId": None,
                    "attemptTag": "missing-exit", "status": "ERROR", "filledQty": 0})
    await repo.engine.position_manager._persist(p)
    report = await execution_readiness(repo.engine, "pf", "HOOD")
    assert not report["passed"] and "exit_outcome_unknown" in {b["code"] for b in report["blockers"]}
    assert (await execution_readiness(repo.engine, "another-book", "HOOD"))["passed"]
    assert (await execution_readiness(repo.engine, "pf", "ANOTHER"))["passed"]
    assert not p.halt_entries  # no mutable global halt is installed by a read


async def test_order_recovery_only_clears_gate_after_managed_ledger_reconciliation(repo):
    p = await managed(repo)
    p.exits.append({"kind": "manual", "leg": "HOOD", "qty": 1, "orderId": None,
                    "attemptTag": "late-response", "status": "ERROR", "filledQty": 0, "ts": 1})
    await repo.engine.position_manager._persist(p)
    async with repo.engine.sf() as session, session.begin():
        session.add(Order(id="late-exit", portfolio_id="pf", symbol="HOOD", sec_type="STK", side="SELL", qty=1,
                          order_type="LMT", limit_price=49., technique="options_cartel", tags=["late-response"],
                          status="CANCELLED", filled_qty=1, avg_fill_price=49.))
    report = await execution_readiness(repo.engine, "pf", "HOOD")
    assert {"exit_not_reconciled", "exit_fills_unreconciled"} <= {b["code"] for b in report["blockers"]}
    await repo.engine.position_manager._policy_adapter(p).exit_router.poll(repo.engine.position_manager, p)
    assert p.legs[0].qty == 1
    report = await execution_readiness(repo.engine, "pf", "HOOD")
    assert report["passed"], report


async def test_restart_cannot_forget_unrestored_position_or_pending_cancellation(repo, monkeypatch):
    p = await managed(repo)
    p.exits[0]["cancelAttempts"] = 1
    await repo.engine.position_manager._persist(p)
    repo.engine.position_manager = PositionManager(repo.engine)
    register_cartel_policy(repo.engine)
    report = await execution_readiness(repo.engine, "pf", "HOOD")
    assert {"position_not_restored", "exit_cancellation_pending"} <= {b["code"] for b in report["blockers"]}
    async def ensure(symbol):
        return None
    monkeypatch.setattr(repo.engine, "ensure_symbol", ensure)
    await repo.engine.position_manager.restore()
    report = await execution_readiness(repo.engine, "pf", "HOOD")
    assert "position_not_restored" not in {b["code"] for b in report["blockers"]}
    assert not report["passed"]


async def test_closed_record_with_working_exit_still_blocks_new_exposure(repo):
    p = await managed(repo)
    async with repo.engine.sf() as session, session.begin():
        stored = await session.get(ManagedPositionRow, p.id)
        stored.status = "closed"
    report = await execution_readiness(repo.engine, "pf", "HOOD")
    assert "exit_cancellation_pending" in {b["code"] for b in report["blockers"]}


async def test_unmanaged_entry_fills_block_new_exposure(repo):
    await setup_entry(repo)
    report = await execution_readiness(repo.engine, "pf", "HOOD")
    assert "entry_fills_unmanaged" in {b["code"] for b in report["blockers"]}


async def test_public_preflight_reports_blocker_without_creating_an_order(repo):
    p = await managed(repo)
    p.exits.append({"kind": "manual", "leg": "HOOD", "qty": 1, "orderId": None,
                    "attemptTag": "unresolved", "status": None, "filledQty": 0})
    await repo.engine.position_manager._persist(p)
    async with repo.engine.sf() as session:
        run = await session.get(TechniqueRun, "r1")
        before = len((await session.scalars(select(Order))).all())
    plan = CartelPlan.model_validate(run.result["plan"]["plan"])
    spec = ExecutionInput(portfolio_id="pf", instrument="shares", budget=500)
    result = await preflight(repo.engine, plan, spec)
    assert not result["executionReadiness"]["passed"] and result["intent"] is None
    assert not next(c for c in result["checks"] if c["name"] == "execution_reconciled")["passed"]
    async with repo.engine.sf() as session:
        assert len((await session.scalars(select(Order))).all()) == before


async def test_other_entry_attempt_is_not_ignored_by_current_reservation_exemption(repo):
    await setup_entry(repo, status="ACCEPTED", filled=0)
    report = await execution_readiness(repo.engine, "pf", "HOOD", ignore_attempt_run_id="another-run")
    assert "entry_not_settled" in {b["code"] for b in report["blockers"]}
    assert (await execution_readiness(repo.engine, "pf", "HOOD", ignore_attempt_run_id="r1"))["passed"]
    async with repo.engine.sf() as session, session.begin():
        row = await session.get(TechniqueArmed, "r1")
        row.state = {**row.state, "submissionAborted": True}
    assert (await execution_readiness(repo.engine, "pf", "HOOD"))["passed"]


async def test_entry_readiness_block_does_not_prevent_confirmed_position_exit(repo):
    p = await managed(repo)
    async with repo.engine.sf() as session, session.begin():
        row = await session.get(TechniqueArmed, "r1")
        row.state = {**row.state, "attemptTag": "unresolved-entry", "orderId": None}
    assert not (await execution_readiness(repo.engine, "pf", "HOOD"))["passed"]
    await repo.engine.position_manager.close(p.id, force_market=True, reason="protective exit remains available")
    assert p.status == "closed" and p.legs[0].qty == 0


async def test_same_quantity_price_correction_remains_blocked_for_accounting_review(repo):
    p = await managed(repo)
    await repo.engine.position_manager.close(p.id, force_market=True)
    async with repo.engine.sf() as session, session.begin():
        order = await session.get(Order, p.exits[-1]["orderId"])
        order.avg_fill_price += .25
    report = await execution_readiness(repo.engine, "pf", "HOOD")
    assert "exit_price_unreconciled" in {b["code"] for b in report["blockers"]}
