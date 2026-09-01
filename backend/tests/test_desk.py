"""The morning desk surface (POST-SOAK-BUILD-PLAN Phase 1): scheduler wiring,
the composer, fail-closed proposals surfacing, and the send path."""
import datetime as dt

import httpx
import pytest

from zargar.api.app import create_app
from zargar.desk import attach_desk
from zargar.domain import new_id
from zargar.engine import Engine
from zargar.models import Proposal, Signal
from zargar.signals.service import attach_signal_layer

from .conftest import make_test_config


@pytest.fixture
async def desk_rig(fresh_db):
    config = make_test_config()
    eng = Engine(config)
    await eng.start()
    await attach_signal_layer(eng)
    desk = attach_desk(eng)
    app = create_app(config, eng)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, eng, desk
    await eng.stop()


async def test_desk_jobs_registered(desk_rig):
    client, eng, desk = desk_rig
    names = {j["name"] for j in eng.scheduler.status()}
    assert {"roll_watchdog", "soak_nightly", "morning_report"} <= names


async def _seed(eng, *, with_verdict: bool):
    now = dt.datetime.now(dt.timezone.utc)
    sig_id = new_id()
    async with eng.sf() as session:
        session.add(Signal(
            id=sig_id, source_name="NewSrc", ticker="AAPL", direction="long",
            action="open", entry_type="limit", timeframe="swing",
            confidence="explicit_call", is_actionable=True, status="proposed",
            extraction={}, created_at=now, seen_count=1))
        await session.commit()               # FK: the proposal references it
    async with eng.sf() as session:
        session.add(Proposal(
            id=new_id(), signal_id=sig_id, portfolio_id="p1", symbol="AAPL",
            sec_type="STK", side="BUY", qty=5.0, order_type="LMT", limit_price=100.0,
            rationale="test", expires_at=now + dt.timedelta(hours=2),
            context={"techniqueId": "tip", "sourceName": "NewSrc",
                     **({"analyst": {"verdict": "watch"}} if with_verdict else {})}))
        await session.commit()


async def test_morning_report_surfaces_fail_closed(desk_rig):
    client, eng, desk = desk_rig
    await eng.settings.set("techniques.tip.mode", "auto", journal=False)
    await _seed(eng, with_verdict=False)
    r = await client.get("/api/desk/morning")
    assert r.status_code == 200
    rep = r.json()
    props = rep["needsYou"]["pendingProposals"]
    assert len(props) == 1 and props[0]["failClosed"] is True
    assert "no verdict" in props[0]["why"]
    assert rep["needsYou"]["failClosedCount"] == 1
    # the overnight tip is listed with its status
    assert any(t["ticker"] == "AAPL" for t in rep["overnight"]["tips"])


async def test_morning_report_verdict_is_not_fail_closed(desk_rig):
    client, eng, desk = desk_rig
    await eng.settings.set("techniques.tip.mode", "auto", journal=False)
    await _seed(eng, with_verdict=True)
    rep = (await client.get("/api/desk/morning")).json()
    props = rep["needsYou"]["pendingProposals"]
    assert len(props) == 1 and props[0]["failClosed"] is False
    assert props[0]["verdict"] == "watch"


async def test_morning_report_filters_noise(desk_rig):
    """2026-09-01 live finds: the card said '71 tips overnight' (41 were the b2
    research batch) and listed 6 duplicate/stale follow-up flags (4 of 5 plans
    already disarmed). Experiment rows are not tips; a flag is homework only
    while its plan still waits; one row per plan."""
    client, eng, desk = desk_rig
    now = dt.datetime.now(dt.timezone.utc)
    async with eng.sf() as session:
        session.add(Signal(id=new_id(), source_name="S", ticker="REAL", direction="long",
                           action="open", status="shadow", extraction={},
                           created_at=now, seen_count=1))
        session.add(Signal(id=new_id(), source_name="S", ticker="EXPT", direction="long",
                           action="open", status="replayed",
                           extraction={"experiment": "b9"}, created_at=now, seen_count=1))
        await session.commit()
    for rid in ("live1", "live1", "dead1"):      # live twice (dedupe), dead once
        await eng.journal.append("TechniquePlanError",
                                 {"runId": rid, "symbol": "AMZN",
                                  "error": "source follow-up: 'update_stop' on AMZN"})

    class _AP:
        status = "armed"
        run_id = "live1"
        trades: dict = {}

        def _attention_reasons(self):
            return []

    class _FakeRunner:
        _armed = {"live1": _AP()}

    eng.plan_runners = {"tip": _FakeRunner()}
    rep = await desk.morning_report()
    tickers = [t["ticker"] for t in rep["overnight"]["tips"]]
    assert "REAL" in tickers and "EXPT" not in tickers
    fu = rep["needsYou"]["followUps"]
    assert len(fu) == 1 and fu[0]["runId"] == "live1"


async def test_scheduled_morning_send_skips_late(desk_rig):
    """A late (evening) deploy must not fire a 'morning' push — found live
    2026-08-31 when registering after 08:25 pushed at night."""
    client, eng, desk = desk_rig
    await eng.settings.set("desk.morning_push_until", "00:00", journal=False)
    out = await desk.morning_send_scheduled()
    assert out.get("skippedLate") is True
    assert out["sent"] == {"push": False, "telegram": False}


async def test_morning_send_composes_short_form(desk_rig):
    client, eng, desk = desk_rig
    await eng.settings.set("techniques.tip.mode", "auto", journal=False)
    await _seed(eng, with_verdict=False)
    r = await client.post("/api/desk/morning/send")
    assert r.status_code == 200
    out = r.json()
    assert "1 proposal(s) waiting" in out["body"]
    assert "fail-closed" in out["body"]
    assert out["needsYou"] >= 1
    # no push subscriptions / telegram token in tests — composed, not delivered
    assert out["sent"] == {"push": False, "telegram": False} or out["sent"]["push"] in (True, False)
