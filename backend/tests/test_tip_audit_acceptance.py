"""Independent v0.7.17 audit acceptance; failures identify unresolved boundaries.

Run only via scripts/test-codex.ps1. Real PostgreSQL for cursor cases; model
responses are stubbed. No engine, external market data, or paid LLM calls.
"""
import datetime as dt
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from zargar.db import make_engine
from zargar.models import ManagedPositionRow
from zargar.signals.extraction import Extractor
from zargar.signals.schemas import TradeSignal, underlying_price_checks_ok
from zargar.signals.verification import verify_signal
from zargar.techniques.tip import retro

from .conftest import TEST_DB_URL


def extractor_with(response):
    extractor = Extractor("offline-placeholder", "offline-model")
    extractor._client = NS(messages=NS(create=AsyncMock(return_value=response)))
    return extractor


@pytest.mark.parametrize("stop, text, outcome", [
    ("end_turn", "not JSON", "invalid_output"),
    ("refusal", "", "refused"),
    ("end_turn", '{"signals":[],"source_type":"other"}', "ok"),
])
async def test_extraction_distinguishes_failure_refusal_and_empty_success(stop, text, outcome):
    extractor = extractor_with(NS(stop_reason=stop, content=[NS(type="text", text=text)]))
    result = await extractor.extract("offline sample")
    assert result.outcome == outcome
    if outcome == "invalid_output":
        assert result.outcome_detail and extractor._client.messages.create.await_count == 2


async def test_successful_model_json_cannot_set_machine_outcome():
    payload = {"signals": [], "source_type": "other", "outcome": "refused",
               "outcome_detail": "model-generated status, not a provider refusal"}
    extractor = extractor_with(NS(stop_reason="end_turn", content=[NS(type="text", text=json.dumps(payload))]))
    result = await extractor.extract("offline sample")
    assert result.outcome == "ok", "A valid response must not forge a provider refusal"
    assert result.outcome_detail is None


@pytest.mark.parametrize("instrument,direction", [("call", "long"), ("put", "short")])
@pytest.mark.parametrize("entry", [None, 98.87])
async def test_premium_targets_never_enter_underlying_price_ordering(instrument, direction, entry):
    signal = TradeSignal(ticker="CRWV", direction=direction, instrument=instrument,
        premium=1.4, price_domain="premium", entry_price=entry,
        target_price=1.75, stop_price=0.90, is_actionable=True, confidence="explicit_call",
        thesis_summary="Premium ladder", evidence_quotes=["CRWV premium 1.4 target 1.75 stop .90"])
    quote = NS(last=98.87, bid=98.79, ask=98.86, halted=False, spread_pct=0.071)
    result = await verify_signal(signal, NS(get=lambda symbol: quote), {})
    assert any(c["name"] == "price_units" for c in result["checks"])
    assert not any(c["name"] == "not_past_target" for c in result["checks"])
    assert not any(c["name"] == "price_ordering" and not c["passed"] for c in result["checks"]), result


def test_unknown_option_units_are_not_assumed_underlying_above_heuristic():
    signal = TradeSignal(ticker="X", direction="long", instrument="call",
        premium=30, target_price=35, stop_price=20, price_domain=None,
        is_actionable=True, confidence="explicit_call", thesis_summary="Unknown units",
        evidence_quotes=["X 30 target 35 stop 20"])
    allowed, reason = underlying_price_checks_ok(signal, 100)
    assert not allowed and reason, "Unknown units remain unknown even above 25% of stock price"


@pytest.fixture
async def review_store(fresh_db):
    db = make_engine(TEST_DB_URL)
    sf = async_sessionmaker(db, expire_on_commit=False)
    try:
        yield NS(sf=sf, settings={})
    finally:
        await db.dispose()


def position(i, stamp, reviewed=False):
    return ManagedPositionRow(id=f"audit-{i:05}", technique="tip", symbol="X",
        portfolio_id="audit-only", status="closed", tags=["retro-done"] if reviewed else [],
        config={}, state={}, legs=[], created_at=stamp, updated_at=stamp)


async def test_position_51_is_reviewed_and_tagged(review_store, monkeypatch):
    old = dt.datetime.now(dt.UTC) - dt.timedelta(days=5)
    async with review_store.sf() as session:
        session.add_all([position(i, old, True) for i in range(50)])
        session.add(position(50, old + dt.timedelta(days=1)))
        await session.commit()
    call = AsyncMock(return_value={"grade": "good_call"})
    monkeypatch.setattr(retro, "retro_position", call)
    result = await retro.run_tip_retros(review_store)
    assert call.await_count == 1 and call.call_args.args[1]["id"] == "audit-00050"
    assert result["backlog"] == 1 and result["pending"] == 0 and result["retros"] == 1
    async with review_store.sf() as session:
        row = await session.get(ManagedPositionRow, "audit-00050")
        assert "retro-done" in row.tags
    assert (await retro.run_tip_retros(review_store, limit=0))["backlog"] == 0


async def test_cursor_does_not_drop_equal_timestamp_rows(review_store):
    stamp = dt.datetime.now(dt.UTC) - dt.timedelta(days=1)
    async with review_store.sf() as session:
        session.add_all([position(i, stamp) for i in range(201)])
        await session.commit()
    result = await retro.run_tip_retros(review_store, limit=0)
    assert result["backlog"] == 201 and result["pending"] == 201, result
