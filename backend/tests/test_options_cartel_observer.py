"""Live alert lane: shared listener, durable signal, registry, controls, no orders."""
from dataclasses import replace

import httpx
import pytest
from sqlalchemy import func, select

from zargar import bus as topics
from zargar.api.app import create_app
from zargar.models import BarRow, Event, Order
from zargar.technique.service import TechniqueService
from zargar.techniques.options_cartel.observer import CartelObserver

from .conftest import wait_for
from .test_options_cartel_entry import CLOSE, OPEN, tape
from .test_options_cartel_state import repo as _repo_fixture

repo = _repo_fixture


async def observer(repository, monkeypatch):
    async def ensure(symbol):
        return None
    monkeypatch.setattr(repository.engine, "ensure_symbol", ensure)
    await repository.engine.positions.load()
    instance = CartelObserver(repository.engine)
    instance.clock = lambda: OPEN
    await instance.arm("r1", {"portfolioId": "pf", "mode": "alert"})
    return instance


async def test_bus_observation_fires_once_and_restores_without_orders(repo, monkeypatch):
    instance = await observer(repo, monkeypatch)
    try:
        for bar in tape():
            instance.clock = lambda b=bar: b.ts+60000
            async def observed(current=bar):
                repo.engine.bus.publish(topics.BARS, {"symbol": current.symbol, "tf": "1m", "bar": current})
                row = await repo.load("r1")
                return row["state"].get("lastMinute") == current.ts
            await wait_for(observed)
        async def fired():
            return (await repo.load("r1"))["state"]["phase"] == "signalled"
        await wait_for(fired)
        signal = (await repo.load("r1"))["state"]["signal"]
        await instance.on_minute_bar("HOOD", tape()[-1])
        assert (await repo.load("r1"))["state"]["signal"] == signal
        assert "triggered" in instance.detail("r1")["summary"]
        await instance.stop()
        restored = CartelObserver(repo.engine)
        restored.clock = instance.clock
        assert await restored.restore() == 1
        assert restored.detail("r1")["signal"] == signal
        async with repo.engine.sf() as session:
            assert await session.scalar(select(func.count()).select_from(Order)) == 0
    finally:
        await instance.stop()


async def test_pause_resume_disarm_and_expiry(repo, monkeypatch):
    instance = await observer(repo, monkeypatch)
    try:
        await instance.pause("r1")
        for bar in tape():
            instance.clock = lambda b=bar: b.ts+60000
            await instance.on_minute_bar("HOOD", bar)
        assert (await repo.load("r1"))["state"]["signal"] is None
        await instance.resume("r1")
        instance.clock = lambda: CLOSE
        assert len(await instance.roll_stale()) == 1
        assert instance.armed() == []
        assert (await repo.load("r1"))["status"] == "expired"
    finally:
        await instance.stop()


async def test_money_modes_cannot_be_enabled_through_alert_adapter(repo, monkeypatch):
    instance = await observer(repo, monkeypatch)
    try:
        with pytest.raises(ValueError, match="Money-mode"):
            await instance.set_mode("r1", "auto")
        with pytest.raises(ValueError, match="Only alert"):
            await instance.arm("r1", {"portfolioId": "pf", "mode": "proposal"})
        assert await instance.disarm("r1")
        assert instance.armed() == []
    finally:
        await instance.stop()


async def test_technique_pause_blocks_new_arming(repo, monkeypatch):
    async def ensure(symbol):
        return None
    monkeypatch.setattr(repo.engine, "ensure_symbol", ensure)
    await repo.engine.settings.set("techniques.options_cartel.paused", True)
    instance = CartelObserver(repo.engine)
    instance.clock = lambda: OPEN
    with pytest.raises(ValueError, match="paused"):
        await instance.arm("r1", {"portfolioId": "pf"})


async def test_shared_armed_api_and_technique_controls_include_cartel(repo, monkeypatch):
    instance = await observer(repo, monkeypatch)
    engine = repo.engine
    engine.cartel_observer = instance
    engine.plan_runners = {"options_cartel": instance}
    engine.techniques = {"options_cartel": instance}
    engine.technique = TechniqueService(engine)
    app = create_app(engine.config, engine)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/technique/armed")
            assert response.status_code == 200 and response.json()[0]["technique"] == "options_cartel"
            summary = (await client.get("/api/technique/armed/summary")).json()
            assert summary["counts"]["watching"] == 1
            assert summary["watching"][0]["nearest"]["entry"] == 48.8
            assert (await client.post("/api/techniques/options_cartel/pause")).status_code == 200
            assert instance.detail("r1")["status"] == "paused"
            assert (await client.post("/api/techniques/options_cartel/resume")).status_code == 200
            bad = await client.post("/api/technique/armed/r1/mode", json={"mode": "auto"})
            assert bad.status_code == 400
            assert (await client.get("/api/options-cartel/armed")).json()[0]["runId"] == "r1"
    finally:
        await instance.stop()


@pytest.mark.parametrize("recovery", ["resume", "restart"])
async def test_recovery_uses_saved_context_but_requires_a_new_crossing(repo, monkeypatch, recovery):
    instance = await observer(repo, monkeypatch)
    await instance.stop()
    await instance.pause("r1")
    # The complete original crossing happened while observation was unavailable.
    async with repo.engine.sf() as session, session.begin():
        for bar in tape():
            session.add(BarRow(symbol=bar.symbol, tf=bar.tf, ts=bar.ts, open=bar.open,
                               high=bar.high, low=bar.low, close=bar.close, volume=bar.volume))
    now = OPEN + 10 * 60_000
    instance.clock = lambda: now
    if recovery == "restart":
        await repo.set_status("r1", "armed")
        instance = CartelObserver(repo.engine)
        instance.clock = lambda: now
        await instance.restore()
    else:
        await instance.resume("r1")
    assert len((await repo.load("r1"))["state"]["minutes"]) == 10
    # A repeated delivery of the old confirmation must not produce an alert.
    await instance.on_minute_bar("HOOD", tape()[-1])
    assert (await repo.load("r1"))["state"]["signal"] is None
    # A fresh pullback and crossing still work; the stop retains the opening low.
    for i, original in enumerate(tape(), start=10):
        bar = replace(original, ts=OPEN+i*60_000)
        now = bar.ts+60_000
        await instance.on_minute_bar("HOOD", bar)
    row = await repo.load("r1")
    assert row["state"]["signal"]["at"] == OPEN+20*60_000
    assert row["state"]["signal"]["stop"] == 48.4
    assert row["state"]["observeAfter"] == OPEN+10*60_000
    async with repo.engine.sf() as session:
        assert await session.scalar(select(func.count()).select_from(Order)) == 0


async def test_subscription_failure_is_durable_visible_and_retryable(repo, monkeypatch):
    async def unavailable(symbol):
        raise RuntimeError("feed disconnected")
    monkeypatch.setattr(repo.engine, "ensure_symbol", unavailable)
    await repo.engine.positions.load()
    instance = CartelObserver(repo.engine)
    instance.clock = lambda: OPEN
    try:
        detail = await instance.arm("r1", {"portfolioId": "pf"})
        assert detail["status"] == "paused" and detail["needsAttention"]
        assert "feed disconnected" in detail["summary"]
        assert instance.summary()["counts"]["attention"] == 1
        with pytest.raises(ValueError, match="feed disconnected"):
            await instance.resume("r1")
        assert (await repo.load("r1"))["status"] == "paused"
        async with repo.engine.sf() as session:
            events = (await session.scalars(select(Event).where(Event.aggregate_id == "r1"))).all()
        assert any(e.payload.get("action") == "observation_recovery_failed" for e in events)
        async def available(symbol):
            return None
        monkeypatch.setattr(repo.engine, "ensure_symbol", available)
        detail = await instance.resume("r1")
        assert detail["status"] == "armed" and not detail["needsAttention"]
        assert (await repo.load("r1"))["state"]["observationError"] is None
        assert instance.summary()["windowOpenNow"]
        await instance.pause("r1")
        assert not instance.summary()["windowOpenNow"]
    finally:
        await instance.stop()


async def test_signal_and_observation_survive_journal_failure_together(repo, monkeypatch):
    instance = await observer(repo, monkeypatch)
    await instance.stop()
    for bar in tape()[:-1]:
        instance.clock = lambda b=bar: b.ts+60000
        await instance.on_minute_bar("HOOD", bar)
    journal = instance.repository._journal
    async def unavailable(row, action):
        raise RuntimeError("journal unavailable after commit")
    monkeypatch.setattr(instance.repository, "_journal", unavailable)
    instance.clock = lambda: OPEN+10*60000
    with pytest.raises(RuntimeError, match="journal unavailable"):
        await instance.on_minute_bar("HOOD", tape()[-1])
    row = await repo.load("r1")
    assert row["state"]["signal"] == row["state"]["observation"]["signal"]
    assert row["state"]["phase"] == "signalled"
    monkeypatch.setattr(instance.repository, "_journal", journal)
    restored = CartelObserver(repo.engine)
    restored.clock = instance.clock
    await restored.restore()
    assert restored.detail("r1")["signal"] == row["state"]["signal"]
    await restored.on_minute_bar("HOOD", tape()[-1])
    assert (await repo.load("r1"))["state"]["signal"] == row["state"]["signal"]
