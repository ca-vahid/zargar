"""Public arming and live bus -> controller -> real sim orders -> durable positions."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from zargar import bus as topics
from zargar import events as ev
from zargar.api.app import create_app
from zargar.brokers.base import ExecReport
from zargar.domain import Bar, Quote
from zargar.execution.positions import PositionManager
from zargar.marketstructure.sessions import session_date
from zargar.models import Order, Portfolio
from zargar.techniques.options_cartel.execution import ExecutionInput
from zargar.techniques.options_cartel.position_adapter import register_cartel_policy
from zargar.techniques.options_cartel.runtime import CartelRuntime

from .conftest import wait_for
from .test_options_cartel_controller import setup
from .test_options_cartel_entry import OPEN, tape
from .test_options_cartel_state import repo as _repo_fixture

repo = _repo_fixture


async def runtime(repo, monkeypatch, mode="auto"):
    await setup(repo, monkeypatch, mode, arm=False)
    runner = CartelRuntime(repo.engine)
    runner.clock = lambda: OPEN
    repo.engine.cartel_observer = runner
    repo.engine.plan_runners = {"options_cartel": runner}
    repo.engine.techniques = {"options_cartel": runner}
    spec = ExecutionInput(portfolio_id="pf", mode=mode, instrument="shares", budget=500, max_units=2)
    return runner, spec


async def publish_tape(repo, runner):
    for bar in tape():
        runner.clock = lambda b=bar: b.ts+60_000
        repo.engine.quotes.on_quote(Quote("HOOD", bid=bar.close-.01, ask=bar.close+.01, last=bar.close, ts=runner.clock()))
        async def seen(current=bar):
            repo.engine.bus.publish(topics.BARS, {"symbol": "HOOD", "tf": "1m", "bar": current})
            return (await repo.load("r1"))["state"].get("lastMinute") == current.ts
        await wait_for(seen)
    async def signalled():
        return (await repo.load("r1"))["state"].get("signal") is not None
    await wait_for(signalled)


@pytest.fixture(autouse=True)
async def stop_services(repo):
    yield
    if getattr(repo.engine, "cartel_observer", None):
        await repo.engine.cartel_observer.stop()
    await repo.engine.position_manager.stop()


async def test_public_auto_arm_bus_signal_fill_and_flatten(repo, monkeypatch):
    runner, spec = await runtime(repo, monkeypatch)
    app = create_app(repo.engine.config, repo.engine)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        armed = await client.post("/api/options-cartel/runs/r1/arm", json=spec.model_dump(by_alias=True))
        assert armed.status_code == 200 and armed.json()["config"]["mode"] == "auto"
        assert armed.json()["triggers"][0]["status"] == "waiting"
        assert armed.json()["triggers"][0]["entry"] == 48.8
        assert "5m" in armed.json()["triggers"][0]["waitingText"]
        assert armed.json()["config"]["management"] == "durable"
        assert armed.json()["config"]["maxQty"] == 2
        await publish_tape(repo, runner)
        async def submitted():
            return (await repo.load("r1"))["state"].get("orderId") is not None
        await wait_for(submitted)
        await runner.wait_idle()
        quote = Quote("HOOD", bid=48.85, ask=48.9, last=48.88, ts=runner.clock())
        repo.engine.quotes.on_quote(quote)
        await repo.engine.sim_executor.on_quote(quote)
        async def managed():
            return (await repo.load("r1"))["state"]["phase"] == "managed"
        await wait_for(managed)
        await runner.wait_idle()
        detail = (await client.get("/api/options-cartel/armed/r1")).json()
        assert detail["openPositions"] == 1 and detail["trades"][0]["filledQty"] == 2
        assert runner.summary()["counts"]["inTrade"] == 1
        assert runner.summary()["inTrade"][0]["lastPrice"] == quote.last
        assert (await client.post("/api/options-cartel/armed/r1/flatten")).status_code == 200
        await runner.wait_idle()
        await repo.engine.sim_executor.on_quote(quote)
        async def closed():
            return (await repo.load("r1"))["state"]["phase"] == "closed"
        await wait_for(closed)
        await runner.wait_idle()
        assert repo.engine.positions.position_qty("pf", "HOOD") == 0
        assert runner.detail("r1")["trades"][0]["status"] == "closed"


async def test_option_campaign_api_entry_target_restore_and_stop(repo, monkeypatch):
    runner, _ = await runtime(repo, monkeypatch)
    engine = repo.engine
    contract = 'HOOD291016C00050000'
    monkeypatch.setattr('zargar.risk.is_us_market_hours', lambda *args, **kwargs: True)
    monkeypatch.setattr(engine.quotes, 'source_age_seconds', lambda symbol: 0.)
    engine.options = SimpleNamespace(snapshot_cached=lambda _: {
        'greeks': {'delta': .5}, 'greeksFieldAsOf': {'delta': runner.clock()}})
    engine.position_manager._now = lambda: runner.clock()/1000
    spec = ExecutionInput(portfolio_id='pf', mode='auto', instrument='options', budget=500,
                          risk_pct=2, max_units=4, contract_symbol=contract, overnight_ack=True)
    engine.quotes.on_quote(Quote(contract, bid=.39, ask=.4, last=.4, source='opra', ts=OPEN+10*60_000))
    app = create_app(engine.config, engine)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        armed = await client.post('/api/options-cartel/runs/r1/arm', json=spec.model_dump(by_alias=True))
        assert armed.status_code == 200, armed.text
        await publish_tape(repo, runner)
        await runner.wait_idle()
        async def entry_submitted():
            return (await repo.load('r1'))['state'].get('orderId') is not None
        await wait_for(entry_submitted)
        premium = Quote(contract, bid=.34, ask=.35, last=.35, source='opra', ts=runner.clock())
        engine.quotes.on_quote(premium)
        await engine.sim_executor.on_quote(premium)
        async def adopted():
            return (await repo.load('r1'))['state']['phase'] == 'managed'
        await wait_for(adopted)
        await runner.wait_idle()
        detail = (await client.get('/api/options-cartel/armed/r1')).json()
        assert detail['trades'][0]['filledQty'] == 4
        position = engine.position_manager.get(engine.position_manager.positions()[0]['id'])
        assert position.legs[0].avg_fill == .35 and position.legs[0].multiplier == 100

        runner.clock = lambda: OPEN+11*60_000
        engine.quotes.on_quote(Quote('HOOD', bid=55, ask=55.01, last=55, ts=runner.clock()))
        premium = Quote(contract, bid=.60, ask=.61, last=.60, source='opra', ts=runner.clock())
        engine.quotes.on_quote(premium)
        await engine.position_manager.on_minute_bar(position,
            Bar('HOOD', '1m', OPEN+10*60_000, 55, 55.1, 54.9, 55, 1000))
        await engine.sim_executor.on_quote(premium)
        async def trimmed():
            return position.legs[0].qty == 3
        await wait_for(trimmed)
        assert position.state.stop == position.entry
        assert position.realized_pnl == pytest.approx(25.)
        position_id = position.id

        await runner.stop()
        await engine.position_manager.stop()
        engine.position_manager = PositionManager(engine)
        engine.position_manager._now = lambda: runner.clock()/1000
        register_cartel_policy(engine)
        await engine.position_manager.restore()
        restored = CartelRuntime(engine)
        restored.clock = runner.clock
        engine.cartel_observer = restored
        engine.plan_runners = {'options_cartel': restored}
        await restored.restore()
        restored.start()
        await restored.wait_idle()
        position = engine.position_manager.get(position_id)
        assert position.legs[0].qty == 3 and position.realized_pnl == pytest.approx(25.)
        # Repeated target evidence after restore must not sell another quarter.
        await engine.position_manager.on_minute_bar(position,
            Bar('HOOD', '1m', OPEN+10*60_000, 55, 55.1, 54.9, 55, 1000))
        restored.clock = lambda: OPEN+12*60_000
        engine.position_manager._now = lambda: restored.clock()/1000
        engine.quotes.on_quote(Quote('HOOD', bid=48, ask=48.01, last=48, ts=restored.clock()))
        premium = Quote(contract, bid=.45, ask=.46, last=.45, source='opra', ts=restored.clock())
        engine.quotes.on_quote(premium)
        await engine.position_manager.on_minute_bar(position,
            Bar('HOOD', '1m', OPEN+11*60_000, 48.2, 48.3, 48, 48.1, 1000))
        await engine.sim_executor.on_quote(premium)
        async def closed():
            return position.status == 'closed'
        await wait_for(closed)
        await restored.wait_idle()
        assert engine.positions.position_qty('pf', contract) == 0
        assert position.realized_pnl == pytest.approx(55.)
        async with engine.sf() as session:
            orders = (await session.scalars(select(Order).where(Order.symbol == contract))).all()
        assert sorted((o.side, o.qty, o.filled_qty) for o in orders) == [('BUY', 4, 4), ('SELL', 1, 1), ('SELL', 3, 3)]
        async def api_closed():
            return (await client.get('/api/options-cartel/armed/r1')).json()['openPositions'] == 0
        await wait_for(api_closed)


async def test_proposal_requires_signal_approval_and_resume_waits_for_new_cross(repo, monkeypatch):
    runner, spec = await runtime(repo, monkeypatch, "proposal")
    await runner.arm("r1", {"mode": spec.mode, "portfolioId": "pf", "execution": spec.model_dump()})
    await publish_tape(repo, runner)
    async with repo.engine.sf() as session:
        assert not (await session.scalars(select(Order))).all()
    signal_id = (await repo.load("r1"))["state"]["signal"]["id"]
    assert runner.detail("r1")["awaitingApproval"]
    with pytest.raises(ValueError):
        await runner.approve("r1", "not-this-signal")
    await runner.approve("r1", signal_id)
    await runner.wait_idle()
    assert (await repo.load("r1"))["state"].get("orderId")


async def test_quote_watch_records_selected_option_without_triggering_entry(repo, monkeypatch):
    from zargar.techniques.options_cartel.quote_observations import RECORD_SETTING, quote_observations
    from zargar.techniques.options_cartel.service import CartelService

    runner, _ = await runtime(repo, monkeypatch, 'proposal')
    contract = 'HOOD291016C00050000'
    spec = ExecutionInput(portfolio_id='pf', mode='proposal', instrument='options', budget=100,
                          max_units=1, contract_symbol=contract, overnight_ack=True)
    await runner.arm('r1', {'mode': 'proposal', 'portfolioId': 'pf', 'execution': spec.model_dump()})
    repo.engine.quotes.on_quote(Quote(contract, bid=.39, ask=.4, ts=OPEN, source='opra', source_ts=OPEN))
    await repo.engine.settings.set(RECORD_SETTING, True)
    await runner.on_quote_watch()
    await runner.quote_recorder.task
    observations = await quote_observations(CartelService(repo.engine), 'r1', contract)
    assert len(observations['rows']) == 1 and observations['rows'][0]['source_at'] == OPEN
    async with repo.engine.sf() as session:
        assert not (await session.scalars(select(Order))).all()


async def test_partial_fill_is_managed_while_entry_response_is_still_pending(repo, monkeypatch):
    runner, spec = await runtime(repo, monkeypatch)
    original = repo.engine.orders.place
    entered, release = asyncio.Event(), asyncio.Event()
    async def slow(intent):
        result = await original(intent)
        if intent.side == "BUY":
            entered.set()
            await release.wait()
        return result
    monkeypatch.setattr(repo.engine.orders, "place", slow)
    await runner.arm("r1", {"mode": "auto", "portfolioId": "pf", "execution": spec.model_dump()})
    try:
        await publish_tape(repo, runner)
        await asyncio.wait_for(entered.wait(), 8)
        async with repo.engine.sf() as session:
            entry = await session.scalar(select(Order).where(Order.side == "BUY"))
        await repo.engine.orders.on_report(ExecReport(kind="fill", order_id=entry.id, fill_qty=1,
                                                     fill_price=48.9, exec_id="partial-before-response"))
        async def protected():
            positions = repo.engine.position_manager.positions()
            return bool(positions and positions[0]["venueStopOrderId"])
        await wait_for(protected)
        assert not runner.fires["r1"].done()
        assert repo.engine.position_manager.positions()[0]["legs"][0]["qty"] == 1
    finally:
        release.set()
        await runner.wait_idle()


async def test_restore_managed_exposure_and_disarm_keeps_position_management(repo, monkeypatch):
    runner, spec = await runtime(repo, monkeypatch)
    await runner.arm("r1", {"mode": "auto", "portfolioId": "pf", "execution": spec.model_dump()})
    await publish_tape(repo, runner)
    async def submitted():
        return (await repo.load("r1"))["state"].get("orderId") is not None
    await wait_for(submitted)
    await runner.wait_idle()
    quote = Quote("HOOD", bid=48.85, ask=48.9, last=48.88, ts=runner.clock())
    repo.engine.quotes.on_quote(quote)
    await repo.engine.sim_executor.on_quote(quote)
    async def managed():
        return (await repo.load("r1"))["state"]["phase"] == "managed"
    await wait_for(managed)
    await runner.wait_idle()
    await runner.stop()
    await repo.engine.position_manager.stop()
    repo.engine.position_manager = PositionManager(repo.engine)
    register_cartel_policy(repo.engine)
    await repo.engine.position_manager.restore()
    restored = CartelRuntime(repo.engine)
    restored.clock = runner.clock
    repo.engine.cartel_observer = restored
    await restored.restore()
    restored.start()
    await restored.wait_idle()
    assert restored.detail("r1")["openPositions"] == 1
    await restored.disarm("r1")
    await restored.wait_idle()
    assert (await repo.load("r1"))["status"] == "closing"
    assert restored.detail("r1")["openPositions"] == 1
    async with repo.engine.sf() as session:
        assert len((await session.scalars(select(Order).where(Order.side == "BUY"))).all()) == 1


async def test_pause_resume_discards_old_proposal_and_requires_new_closed_bar_signal(repo, monkeypatch):
    runner, spec = await runtime(repo, monkeypatch, "proposal")
    await runner.arm("r1", {"mode": "proposal", "portfolioId": "pf", "execution": spec.model_dump()})
    await publish_tape(repo, runner)
    await runner.wait_idle()
    old = (await repo.load("r1"))["state"]["signal"]["id"]
    await runner.pause("r1")
    await runner.resume("r1")
    assert (await repo.load("r1"))["state"]["phase"] == "waiting"
    for i, original in enumerate(tape(), start=10):
        bar = replace(original, ts=OPEN+i*60_000)
        runner.clock = lambda b=bar: b.ts+60_000
        repo.engine.quotes.on_quote(Quote("HOOD", bid=bar.close-.01, ask=bar.close+.01, last=bar.close, ts=runner.clock()))
        await runner.on_minute_bar("HOOD", bar)
    await runner.wait_idle()
    new = (await repo.load("r1"))["state"]["signal"]["id"]
    assert new != old
    with pytest.raises(ValueError):
        await runner.approve("r1", old)


async def test_reviewed_upgrade_from_alert_resets_signal_without_placing_an_order(repo, monkeypatch):
    runner, spec = await runtime(repo, monkeypatch)
    await runner.arm("r1", {"mode": "alert", "portfolioId": "pf"})
    await publish_tape(repo, runner)
    await runner.arm("r1", {"mode": "auto", "portfolioId": "pf", "execution": spec.model_dump()})
    row = await repo.load("r1")
    assert row["mode"] == "auto" and row["state"]["signal"] is None
    assert row["state"]["configHistory"]
    async with repo.engine.sf() as session:
        assert not (await session.scalars(select(Order))).all()


async def test_signal_reset_cannot_erase_a_reserved_submission(repo, monkeypatch):
    runner, spec = await runtime(repo, monkeypatch)
    await runner.arm("r1", {"mode": "auto", "portfolioId": "pf", "execution": spec.model_dump()})
    await publish_tape(repo, runner)
    async def submitted():
        return (await repo.load("r1"))["state"].get("orderId") is not None
    await wait_for(submitted)
    await runner.wait_idle()
    before = await repo.load("r1")
    await runner._reset_signal("r1", "simulated_expiry_race")
    after = await repo.load("r1")
    assert after["state"]["signal"] == before["state"]["signal"]
    assert after["state"]["attemptTag"] == before["state"]["attemptTag"]


async def test_latched_loss_pauses_cartel_book_without_global_halt(repo, monkeypatch):
    runner, spec = await runtime(repo, monkeypatch)
    await runner.arm("r1", {"mode": "auto", "portfolioId": "pf", "execution": spec.model_dump()})
    await repo.engine.settings.set("techniques.options_cartel.daily_loss_halt_pct", 1.)
    await repo.engine.journal.append(ev.OPTIONS_CARTEL_LOSS_HALT,
        {"technique": "options_cartel", "portfolioId": "pf", "day": session_date(runner.clock()),
         "asOfMs": runner.clock(), "pnl": -200, "pct": 1, "equity": 10000, "limit": 100, "report": {}}, portfolio_id="pf")
    await runner.on_heartbeat()
    assert (await repo.load("r1"))["status"] == "paused"
    assert "loss halt" in runner.detail("r1")["summary"]
    assert not repo.engine.halt.engaged


@pytest.mark.parametrize("issue", ["no_loss_halt", "disconnected_real", "identity_mismatch"])
async def test_arming_permissions_fail_before_creating_state(repo, monkeypatch, issue):
    runner, spec = await runtime(repo, monkeypatch)
    if issue == "no_loss_halt":
        await repo.engine.settings.set("risk.daily_loss_halt_pct", 0)
    else:
        async with repo.engine.sf() as session, session.begin():
            portfolio = await session.get(Portfolio, "pf")
            portfolio.kind = "live"
        if issue == "disconnected_real":
            await repo.engine.positions.load()
        await repo.engine.settings.set("trading.mode", "live")
        await repo.engine.settings.set("techniques.options_cartel.allow_live_auto", True)
        spec = spec.model_copy(update={"allow_live": True})
    with pytest.raises(ValueError):
        await runner.arm("r1", {"mode": "auto", "portfolioId": "pf", "execution": spec.model_dump()})
    assert await repo.load("r1") is None


async def test_cancelled_approval_request_does_not_cancel_its_order_task(repo, monkeypatch):
    runner, spec = await runtime(repo, monkeypatch, "proposal")
    await runner.arm("r1", {"mode": "proposal", "portfolioId": "pf", "execution": spec.model_dump()})
    await publish_tape(repo, runner)
    await runner.wait_idle()
    signal_id = (await repo.load("r1"))["state"]["signal"]["id"]
    entered, release = asyncio.Event(), asyncio.Event()
    original = repo.engine.orders.place
    async def slow(intent):
        result = await original(intent)
        if intent.side == "BUY":
            entered.set()
            await release.wait()
        return result
    monkeypatch.setattr(repo.engine.orders, "place", slow)
    request = asyncio.create_task(runner.approve("r1", signal_id))
    try:
        await asyncio.wait_for(entered.wait(), 8)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        assert not runner.fires["r1"].done()
    finally:
        release.set()
        await runner.wait_idle()
    async with repo.engine.sf() as session:
        assert len((await session.scalars(select(Order).where(Order.side == "BUY"))).all()) == 1


async def test_display_omits_optional_distance_until_quote_exists(repo, monkeypatch):
    runner, spec = await runtime(repo, monkeypatch, "proposal")
    repo.engine.quotes._quotes.clear()
    result = await runner.arm("r1", {"mode": "proposal", "portfolioId": "pf", "execution": spec.model_dump()})
    assert "distancePct" not in result["triggers"][0]
    assert result["triggers"][0]["status"] == "waiting"
