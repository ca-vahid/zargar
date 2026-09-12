"""1A (Codex consolidated recommendation, 2026-09-10): bounded ONE-shot
quote-freshness recovery for Tips auto entries. The 10:53 AAPL take died on
'quote age 10.5s (max 10s)' with no retry."""
import datetime as dt
from unittest.mock import AsyncMock

import pytest

from zargar.approvals import proposals as proposals_mod
from zargar.domain import new_id
from zargar.engine import Engine
from zargar.models import Proposal
from zargar.signals.service import attach_signal_layer

from .conftest import make_test_config

STALE = {"status": "REJECTED_RISK", "id": "o1",
         "rejectReason": "quote age 10.5s (max 10s)"}
OK = {"status": "SUBMITTED", "id": "o2"}


@pytest.fixture
async def rig(fresh_db):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    yield eng
    await eng.stop()


async def _proposal(rig, ctx: dict | None = None) -> str:
    pid = next(p["id"] for p in rig.positions.portfolios() if p["kind"] == "sim")
    row = Proposal(id=new_id(), portfolio_id=pid, symbol="AAPL260914C00330000",
                   sec_type="OPT", side="BUY", qty=12.0, order_type="LMT",
                   limit_price=0.59, status="pending",
                   expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2),
                   context={"techniqueId": "tip", **(ctx or {})})
    async with rig.sf() as session:
        session.add(row)
        await session.commit()
    return row.id


@pytest.fixture
def no_refresh(monkeypatch):
    # the retry requests a REAL observation via options.refresh_now (v0.7.44
    # review 1A) — stub it to "no fresh quote available"
    def _apply(rig):
        monkeypatch.setattr(rig.options, "refresh_now", AsyncMock(return_value=None))
    return _apply


async def test_fresh_retry_recovers_a_stale_quote_rejection(rig, monkeypatch, no_refresh):
    no_refresh(rig)
    pid = await _proposal(rig)
    place = AsyncMock(side_effect=[dict(STALE), dict(OK)])
    monkeypatch.setattr(rig.orders, "place", place)
    out = await rig.proposals.approve(pid, via="auto")
    assert out["proposal"]["status"] == "executed"
    assert place.await_count == 2
    async with rig.sf() as session:
        row = await session.get(Proposal, pid)
    fr = (row.context or {}).get("freshRetry")
    assert fr and fr["firstOrderId"] == "o1" and fr["retryOrderId"] == "o2"
    assert fr["retryStatus"] == "SUBMITTED"


async def test_still_stale_retry_terminates_visibly(rig, monkeypatch, no_refresh):
    no_refresh(rig)
    pid = await _proposal(rig)
    place = AsyncMock(side_effect=[dict(STALE), dict(STALE, id="o3")])
    monkeypatch.setattr(rig.orders, "place", place)
    out = await rig.proposals.approve(pid, via="auto")
    assert out["proposal"]["status"] == "failed"
    assert place.await_count == 2                      # ONE retry, never a chase
    async with rig.sf() as session:
        row = await session.get(Proposal, pid)
    assert (row.context or {}).get("freshRetry", {}).get("retryStatus") == "REJECTED_RISK"


async def test_other_gate_failures_never_retry(rig, monkeypatch, no_refresh):
    no_refresh(rig)
    pid = await _proposal(rig)
    place = AsyncMock(return_value={"status": "REJECTED_RISK", "id": "o1",
                                    "rejectReason": "per-source budget cap reached"})
    monkeypatch.setattr(rig.orders, "place", place)
    out = await rig.proposals.approve(pid, via="auto")
    assert out["proposal"]["status"] == "failed" and place.await_count == 1


async def test_mixed_failures_never_retry(rig, monkeypatch, no_refresh):
    no_refresh(rig)
    pid = await _proposal(rig)
    place = AsyncMock(return_value={"status": "REJECTED_RISK", "id": "o1",
                                    "rejectReason": "quote age 11s (max 10s); rate window"})
    monkeypatch.setattr(rig.orders, "place", place)
    out = await rig.proposals.approve(pid, via="auto")
    assert out["proposal"]["status"] == "failed" and place.await_count == 1


async def test_once_only_survives_a_prior_attempt(rig, monkeypatch, no_refresh):
    no_refresh(rig)
    pid = await _proposal(rig, ctx={"freshRetry": {"at": "earlier", "firstOrderId": "old"}})
    place = AsyncMock(return_value=dict(STALE))
    monkeypatch.setattr(rig.orders, "place", place)
    out = await rig.proposals.approve(pid, via="auto")
    assert out["proposal"]["status"] == "failed" and place.await_count == 1


async def test_live_books_never_retry(rig, monkeypatch, no_refresh):
    no_refresh(rig)
    pid = await _proposal(rig)
    place = AsyncMock(return_value=dict(STALE))
    monkeypatch.setattr(rig.orders, "place", place)
    monkeypatch.setattr(rig.positions, "portfolio", lambda _id: {"kind": "live"})
    out = await rig.proposals.approve(pid, via="auto")
    assert out["proposal"]["status"] == "failed" and place.await_count == 1


async def test_retry_limit_is_never_raised(rig, monkeypatch):
    pid = await _proposal(rig)

    from types import SimpleNamespace as NS
    import time as _t
    q = NS(ask=0.94, bid=0.9, last=0.92, source="opra",
           source_ts=int(_t.time() * 1000), ts=int(_t.time() * 1000))
    monkeypatch.setattr(rig.options, "refresh_now", AsyncMock(return_value=q))
    place = AsyncMock(side_effect=[dict(STALE), dict(OK)])
    monkeypatch.setattr(rig.orders, "place", place)
    await rig.proposals.approve(pid, via="auto")
    limits = [c.args[0].limit_price for c in place.call_args_list]
    assert limits == [0.59, 0.59]                      # improve-only, never chase


async def test_submitted_or_ambiguous_outcomes_never_retry(rig, monkeypatch, no_refresh):
    no_refresh(rig)
    pid = await _proposal(rig)
    place = AsyncMock(return_value={"status": "SUBMITTED", "id": "o1"})
    monkeypatch.setattr(rig.orders, "place", place)
    out = await rig.proposals.approve(pid, via="auto")
    assert out["proposal"]["status"] == "executed" and place.await_count == 1


async def test_entry_study_journals_decision_and_delayed_samples(rig, monkeypatch):
    """P3 diagnostics with HONEST labels (v0.7.44 review): decision-time and
    delayed samples, two durable rows, source premium separate from the
    proposal limit. Changes no behavior."""
    import asyncio as aio
    import time
    from types import SimpleNamespace as NS
    from sqlalchemy import select
    from zargar.models import Event, Signal
    await rig.settings.set("techniques.tip.entry_study_delay_seconds", 0.05, journal=False)
    now_ms = int(time.time() * 1000)
    q = NS(bid=0.85, ask=0.88, last=0.86, source="opra", source_ts=now_ms,
           ts=now_ms, delayed=False)
    monkeypatch.setattr(rig.options, "refresh_now", AsyncMock(return_value=q))
    monkeypatch.setattr(rig.quotes, "get", lambda s: q)
    sid = new_id()
    async with rig.sf() as session:
        session.add(Signal(id=sid, ticker="AAPL", direction="long", action="open",
                           source_name="StudySrc", status="proposed", premium=0.87,
                           thesis_summary="x", extraction={},
                           confidence="explicit_call", is_actionable=True))
        await session.commit()
    pdict = {"id": "study-1", "symbol": "AAPL260914C00330000", "secType": "OPT",
             "signalId": sid, "limitPrice": 0.59,
             "portfolioId": next(p["id"] for p in rig.positions.portfolios()
                                 if p["kind"] == "sim"),
             "context": {"sizing": {"refPrice": 0.59},
                         "analyst": {"verdict": "take"}}}
    rig.proposals._start_entry_study(pdict)
    tasks = list(rig.proposals._entry_studies)
    assert tasks, "study task not started"
    await aio.wait_for(aio.gather(*tasks), 10)
    async with rig.sf() as session:
        rows = (await session.execute(select(Event).where(
            Event.type == "TipEntryStudy").order_by(Event.id))).scalars().all()
    assert [r.payload["phase"] for r in rows] == ["created", "delayed"]
    created, delayed = rows[0].payload, rows[1].payload
    # source premium and proposal limit are SEPARATE — never interchanged
    assert created["signalStatedPremium"] == 0.87
    assert created["proposalLimit"] == 0.59
    assert created["atDecision"]["ask"] == 0.88
    assert delayed["afterDelay"]["ask"] == 0.88 and delayed["verdict"] == "take"
