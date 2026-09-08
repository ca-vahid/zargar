"""Historical recovery preserves existing records and never invents marks."""
import asyncio
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from zargar.api.app import create_app
from zargar.domain import Bar, Quote
from zargar.models import BarRow, Event
from zargar.techniques.options_cartel.marks import recover_prior_marks

from .test_options_cartel_loss import NOW, PREVIOUS_OPEN, fill, holding, mark
from .test_options_cartel_loss import ledger as _ledger_fixture

ledger = _ledger_fixture


async def carried(engine, symbol="TEST", sec_type="STK"):
    engine.config.quote_source = "yahoo"
    await fill(engine, "entry", "BUY", 1, 90, PREVIOUS_OPEN, symbol=symbol, sec_type=sec_type)
    await holding(engine, 1, symbol=symbol, sec_type=sec_type)
    engine.quotes.on_quote(Quote(symbol, bid=101, ask=101.1, last=101, source="yahoo", ts=NOW))


def provider(calls, *, price=100):
    async def fetch(symbol, tf, start, end, *, client):
        calls.append((symbol, tf, start, end, client))
        return [Bar(symbol, tf, PREVIOUS_OPEN, price, price, price, price, 100)]
    return fetch


async def test_missing_carried_close_is_recovered_and_repeat_makes_no_provider_call(ledger):
    await carried(ledger)
    calls = []
    first = await recover_prior_marks(ledger, "pf", now_ms=NOW, fetch=provider(calls))
    assert first["recovered"] == ["TEST"] and first["report"]["pnl"] == 1
    assert calls[0][2] == PREVIOUS_OPEN and calls[0][-1].is_closed
    await recover_prior_marks(ledger, "pf", now_ms=NOW, fetch=provider(calls, price=999))
    assert len(calls) == 1
    async with ledger.sf() as session:
        assert (await session.scalar(select(BarRow).where(BarRow.symbol == "TEST"))).close == 100
        assert len((await session.scalars(select(Event).where(Event.type == "TechniqueCartelRiskMarksRecovered"))).all()) == 1


async def test_option_recovery_requests_contract_not_underlying(ledger):
    symbol = "TEST261016C00100000"
    await carried(ledger, symbol, "OPT")
    await mark(ledger, 100, symbol="TEST")
    calls = []
    result = await recover_prior_marks(ledger, "pf", now_ms=NOW, fetch=provider(calls, price=2))
    assert result["recovered"] == [symbol] and [c[0] for c in calls] == [symbol]


@pytest.mark.parametrize("failure", ["missing", "wrong_symbol", "bad_timestamp", "network"])
async def test_provider_failure_does_not_create_a_mark(ledger, failure):
    await carried(ledger)
    async def fetch(symbol, tf, start, end, *, client):
        if failure == "network":
            raise httpx.ConnectError("provider unavailable")
        if failure == "missing":
            return []
        return [Bar("OTHER" if failure == "wrong_symbol" else symbol, tf,
                    PREVIOUS_OPEN-60_000 if failure == "bad_timestamp" else PREVIOUS_OPEN, 100, 100, 100, 100, 1)]
    result = await recover_prior_marks(ledger, "pf", now_ms=NOW, fetch=fetch)
    assert result["unavailable"] and not result["report"]["available"]
    async with ledger.sf() as session:
        assert not (await session.scalars(select(BarRow))).all()


async def test_simulated_tape_does_not_get_a_real_historical_anchor(ledger):
    await carried(ledger)
    ledger.config.quote_source = "sim"
    ledger.quotes.get("TEST").source = "sim"
    calls = []
    result = await recover_prior_marks(ledger, "pf", now_ms=NOW, fetch=provider(calls))
    assert not calls and not result["recovered"] and result["unavailable"]


async def test_real_contract_source_is_judged_per_symbol_not_stock_feed_setting(ledger):
    symbol = "TEST261016C00100000"
    await carried(ledger, symbol, "OPT")
    ledger.config.quote_source = "sim"
    ledger.quotes.get(symbol).source = "opra"
    calls = []
    result = await recover_prior_marks(ledger, "pf", now_ms=NOW, fetch=provider(calls))
    assert result["recovered"] == [symbol] and len(calls) == 1


async def test_concurrent_recovery_never_overwrites_a_completed_insert(ledger):
    await carried(ledger)
    entered, release = asyncio.Event(), asyncio.Event()
    async def slow(symbol, tf, start, end, *, client):
        entered.set()
        await release.wait()
        return [Bar(symbol, tf, PREVIOUS_OPEN, 200, 200, 200, 200, 1)]
    task = asyncio.create_task(recover_prior_marks(ledger, "pf", now_ms=NOW, fetch=slow))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        await mark(ledger, 100)
    finally:
        release.set()
    result = await task
    assert result["preserved"] == ["TEST"] and result["report"]["pnl"] == 1


async def test_recovery_endpoint_is_authenticated_and_uses_owned_inventory(ledger, monkeypatch):
    await carried(ledger)
    from zargar.api import routes_options_cartel
    from zargar.techniques.options_cartel import marks
    calls = []
    monkeypatch.setattr(routes_options_cartel, "time", SimpleNamespace(time=lambda: NOW/1000))
    monkeypatch.setattr(marks, "fetch_window", provider(calls))
    ledger.config.auth_token = "marks-test"
    app = create_app(ledger.config, ledger)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        url = "/api/options-cartel/risk/pf/recover-marks"
        assert (await client.post(url)).status_code == 401 and not calls
        response = await client.post(url, headers={"Authorization": "Bearer marks-test"})
        assert response.status_code == 200 and response.json()["report"]["pnl"] == 1
        assert response.json()["recovered"] == ["TEST"]
        assert (await client.post("/api/options-cartel/risk/missing/recover-marks",
                                 headers={"Authorization": "Bearer marks-test"})).status_code == 400


async def test_quote_changes_during_recovery_do_not_reprice_the_requested_snapshot(ledger):
    await carried(ledger)
    async def fetch(symbol, tf, start, end, *, client):
        quote = ledger.quotes.get(symbol)
        quote.bid, quote.ask, quote.last, quote.ts = 102, 102.1, 102, NOW+1000
        return [Bar(symbol, tf, PREVIOUS_OPEN, 100, 100, 100, 100, 1)]
    result = await recover_prior_marks(ledger, "pf", now_ms=NOW, fetch=fetch)
    assert result["report"]["available"] and result["report"]["pnl"] == 1
    assert result["report"]["asOfMs"] == NOW
    assert ledger.quotes.get("TEST").bid == 102


async def test_existing_invalid_mark_is_reported_and_not_overwritten(ledger):
    await carried(ledger)
    await mark(ledger, 0)
    calls = []
    result = await recover_prior_marks(ledger, "pf", now_ms=NOW, fetch=provider(calls))
    assert not calls and result["preserved"] == ["TEST"] and result["unavailable"]
    assert not result["report"]["available"]
