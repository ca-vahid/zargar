"""Controller -> real OrderManager/RiskGate/SimExecutor -> actual-fill adoption."""
import asyncio
import datetime as dt
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from zargar.brokers.base import ExecReport
from zargar.brokers.sim import SimExecutor
from zargar.domain import Quote
from zargar.models import Execution, ManagedPositionRow, Order, TechniqueArmed, TechniqueRun
from zargar.orders import OrderManager
from zargar.techniques.options_cartel.controller import CartelEntryController
from zargar.techniques.options_cartel.entry import read_entry
from zargar.techniques.options_cartel.execution import ExecutionInput
from zargar.techniques.options_cartel.exits import ExitCampaign
from zargar.techniques.options_cartel.loss import daily_loss_report
from zargar.techniques.options_cartel.plans import CartelPlan

from .conftest import wait_for
from .test_options_cartel_entry import OPEN, tape
from .test_options_cartel_setups import histories
from .test_options_cartel_state import repo as _repo_fixture

repo = _repo_fixture


async def setup(repo, monkeypatch, mode="auto", *, arm=True):
    engine = repo.engine
    now = OPEN+10*60_000
    async def ensure(symbol):
        return None
    monkeypatch.setattr(engine, "ensure_symbol", ensure)
    monkeypatch.setattr(engine.quotes, "age_seconds", lambda symbol: (now-engine.quotes.get(symbol).ts)/1000)
    await engine.positions.load()
    engine.sim_executor = SimExecutor(latency_ms=0, slippage_bps=0, size_impact_bps=0, settings=engine.settings)
    engine.orders = OrderManager(engine.sf, engine.bus, engine.journal, engine.risk, engine.settings,
                                 engine.positions, engine.quotes, engine.executor_for, ensure)
    engine.sim_executor.on_report = engine.orders.on_report
    history, _ = histories()
    async with engine.sf() as session, session.begin():
        run = await session.get(TechniqueRun, "r1")
        plan = CartelPlan.model_validate(run.result["plan"]["plan"])
        run.result = {**run.result, "exitCampaign": ExitCampaign.for_profile("may_2026", [55]).model_dump(mode="json")}
        run.config = {"inputs": {"history": [b.model_copy(update={"symbol": "HOOD"}).model_dump(mode="json") for b in history]}}
    execution = ExecutionInput(portfolio_id="pf", mode=mode, instrument="shares", budget=500, max_units=2)
    signal = read_entry(plan, tape(), now)["signal"]
    if arm:
        await repo.arm("r1", "pf", mode, {"execution": execution.model_dump(), "clientKind": "desktop"}, now_ms=OPEN)
        assert await repo.consume_signal("r1", signal, now_ms=now)
    engine.quotes.on_quote(Quote("HOOD", bid=48.9, ask=48.95, last=48.92, ts=now))
    controller = CartelEntryController(engine)
    controller.clock = lambda: now
    return controller, signal


@pytest.fixture(autouse=True)
async def stop_manager(repo):
    yield
    await repo.engine.position_manager.stop()


async def test_single_submission_actual_fill_and_managed_handoff(repo, monkeypatch):
    controller, _ = await setup(repo, monkeypatch)
    first, second = await asyncio.gather(controller.submit("r1"), controller.submit("r1"))
    assert first["orderId"] == second["orderId"]
    assert sum(bool(r.get("submissionAttempted")) for r in (first, second)) == 1
    async with repo.engine.sf() as session:
        entries = (await session.scalars(select(Order).where(Order.side == "BUY"))).all()
    assert len(entries) == 1 and entries[0].qty == 2
    assert (await repo.load("r1"))["state"]["phase"] == "working"
    quote = Quote("HOOD", bid=48.85, ask=48.9, last=48.88, ts=controller.clock())
    repo.engine.quotes.on_quote(quote)
    await repo.engine.sim_executor.on_quote(quote)
    assert repo.engine.positions.position_qty("pf", "HOOD") == 2
    result = await controller.poll("r1")
    assert result["status"] == "managed"
    p = repo.engine.position_manager.get(result["adoption"]["positionId"])
    assert p.legs[0].qty == 2 and p.legs[0].avg_fill == 48.9
    assert p.state.stop == 48.4
    assert p.venue_stop_order_id
    assert (await controller.submit("r1"))["adoption"]["positionId"] == p.id
    stop_id = p.venue_stop_order_id
    repo.engine.halt.engage("halt must not trap the verified exit")
    await repo.engine.position_manager.close(p.id, force_market=True, reason="real sim lifecycle close")
    async with repo.engine.sf() as session:
        assert (await session.get(Order, stop_id)).status == "CANCELLED"
    await repo.engine.sim_executor.on_quote(quote)
    await wait_for(lambda: repo.engine.position_manager.get(p.id) is None)
    assert repo.engine.positions.position_qty("pf", "HOOD") == 0
    assert (await controller.poll("r1"))["status"] == "closed"


async def test_proposal_requires_approval_of_this_signal(repo, monkeypatch):
    controller, signal = await setup(repo, monkeypatch, "proposal")
    assert (await controller.submit("r1"))["status"] == "awaiting_approval"
    assert (await controller.submit("r1", approval_signal_id="wrong"))["status"] == "awaiting_approval"
    assert not (await repo.load("r1"))["state"].get("attemptTag")
    assert (await controller.submit("r1", approval_signal_id=signal["id"]))["status"] == "working"


@pytest.mark.parametrize("issue", ["stale_signal", "chase", "halt", "no_loss_halt"])
async def test_invalid_entry_conditions_never_reserve_or_place(repo, monkeypatch, issue):
    controller, _ = await setup(repo, monkeypatch)
    if issue == "stale_signal":
        controller.clock = lambda: OPEN+20*60_000
    elif issue == "chase":
        repo.engine.quotes.on_quote(Quote("HOOD", bid=51, ask=51.1, last=51, ts=controller.clock()))
    elif issue == "halt":
        repo.engine.halt.engage("test")
    else:
        await repo.engine.settings.set("risk.daily_loss_halt_pct", 0)
    with pytest.raises(ValueError):
        await controller.submit("r1")
    assert not (await repo.load("r1"))["state"].get("attemptTag")
    async with repo.engine.sf() as session:
        assert not (await session.scalars(select(Order))).all()


async def test_lost_response_recovers_existing_order_without_second_submission(repo, monkeypatch):
    controller, _ = await setup(repo, monkeypatch)
    original = repo.engine.orders.place
    async def lost(intent):
        await original(intent)
        raise ConnectionError("response lost")
    monkeypatch.setattr(repo.engine.orders, "place", lost)
    a = await controller.submit("r1")
    b = await controller.submit("r1")
    assert a["status"] == "working" and a["orderId"] == b["orderId"]
    async with repo.engine.sf() as session:
        assert len((await session.scalars(select(Order).where(Order.side == "BUY"))).all()) == 1


async def test_unknown_submission_is_attention_not_retry_permission(repo, monkeypatch):
    controller, _ = await setup(repo, monkeypatch)
    calls = []
    async def unavailable(intent):
        calls.append(intent)
        raise ConnectionError("no acknowledgement")
    monkeypatch.setattr(repo.engine.orders, "place", unavailable)
    assert (await controller.submit("r1"))["status"] == "needs_attention"
    assert (await controller.submit("r1"))["status"] == "needs_attention"
    assert len(calls) == 1


async def test_pause_during_reservation_aborts_before_routing(repo, monkeypatch):
    controller, _ = await setup(repo, monkeypatch)
    original = controller.repository._journal
    async def pause(row, action):
        await original(row, action)
        if action == "submission_reserved":
            await repo.set_status("r1", "paused")
    monkeypatch.setattr(controller.repository, "_journal", pause)
    assert (await controller.submit("r1"))["status"] == "pre_submit_rejected"
    assert (await controller.submit("r1"))["status"] == "pre_submit_rejected"
    async with repo.engine.sf() as session:
        assert not (await session.scalars(select(Order))).all()


async def test_price_moving_during_preflight_cannot_bypass_the_chase_cap(repo, monkeypatch):
    controller, _ = await setup(repo, monkeypatch)
    original = repo.engine.journal.append
    async def move(kind, *args, **kwargs):
        result = await original(kind, *args, **kwargs)
        if kind == "TechniqueCartelPreflight":
            repo.engine.quotes.on_quote(Quote("HOOD", bid=51, ask=51.1, last=51, ts=controller.clock()))
        return result
    monkeypatch.setattr(repo.engine.journal, "append", move)
    with pytest.raises(ValueError, match="chase"):
        await controller.submit("r1")
    assert not (await repo.load("r1"))["state"].get("attemptTag")


async def test_unresolved_exit_discovered_after_preflight_blocks_reservation(repo, monkeypatch):
    controller, _ = await setup(repo, monkeypatch)
    original = repo.engine.journal.append
    async def uncertainty(kind, *args, **kwargs):
        result = await original(kind, *args, **kwargs)
        if kind == "TechniqueCartelPreflight":
            async with repo.engine.sf() as session, session.begin():
                session.add(ManagedPositionRow(id="earlier", portfolio_id="pf", technique="options_cartel",
                    symbol="HOOD", status="closed", config={"policy": {"cartel": {}}}, legs=[],
                    state={"exits": [{"kind": "close", "leg": "HOOD", "qty": 1, "orderId": None,
                                      "status": "ERROR", "attemptTag": "unknown-exit"}]}))
        return result
    monkeypatch.setattr(repo.engine.journal, "append", uncertainty)
    with pytest.raises(ValueError, match="reconciliation"):
        await controller.submit("r1")
    assert not (await repo.load("r1"))["state"].get("attemptTag")


async def test_option_submission_preserves_contract_units_debit_and_overnight_ack(repo, monkeypatch):
    controller, _ = await setup(repo, monkeypatch)
    symbol = "HOOD291016C00050000"  # synthetic distant expiry; not an option recommendation
    execution = ExecutionInput(portfolio_id="pf", mode="auto", instrument="options", budget=500,
                               max_units=2, contract_symbol=symbol, overnight_ack=True)
    async with repo.engine.sf() as session, session.begin():
        armed = await session.get(TechniqueArmed, "r1")
        armed.config = {**armed.config, "execution": execution.model_dump()}
    # The test's exchange clock is the same synthetic RTH clock as its signal.
    monkeypatch.setattr("zargar.risk.is_us_market_hours", lambda *args, **kwargs: True)
    monkeypatch.setattr(repo.engine.quotes, "source_age_seconds", lambda symbol: 0.)
    repo.engine.options = SimpleNamespace(snapshot_cached=lambda _: {
        "greeks": {"delta": .5}, "greeksFieldAsOf": {"delta": controller.clock()}})
    repo.engine.quotes.on_quote(Quote(symbol, bid=.39, ask=.4, last=.4, source="opra", ts=controller.clock()))
    result = await controller.submit("r1")
    assert result["status"] == "working", result
    async with repo.engine.sf() as session:
        order = await session.get(Order, result["orderId"])
    assert order.symbol == symbol and order.sec_type == "OPT" and order.qty == 2 and order.limit_price == .4
    quote = Quote(symbol, bid=.34, ask=.35, last=.35, source="opra", ts=controller.clock())
    repo.engine.quotes.on_quote(quote)
    await repo.engine.sim_executor.on_quote(quote)
    result = await controller.poll("r1")
    assert result["status"] == "managed"
    p = repo.engine.position_manager.get(result["adoption"]["positionId"])
    assert p.legs[0].qty == 2 and p.legs[0].multiplier == 100 and p.legs[0].avg_fill == .35
    assert p.overnight == "app_managed" and p.overnight_ack


async def test_report_timestamp_is_preserved_for_daily_accounting(repo, monkeypatch):
    controller, _ = await setup(repo, monkeypatch)
    result = await controller.submit("r1")
    report_time = controller.clock()-1000
    await repo.engine.orders.on_report(ExecReport(kind="fill", order_id=result["orderId"], exec_id="dated-fill",
        ts=report_time, fill_qty=2, fill_price=48.9, commission=.1))
    async with repo.engine.sf() as session:
        execution = await session.get(Execution, "dated-fill")
    assert execution.ts == dt.datetime.fromtimestamp(report_time/1000, dt.UTC)
    assert (await controller.poll("r1"))["status"] == "managed"
    measured = await daily_loss_report(repo.engine, "pf", now_ms=controller.clock())
    assert measured["available"] and measured["pnl"] == -.1
