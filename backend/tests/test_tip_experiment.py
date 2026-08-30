"""Out-of-band historical experiment guarantees (KNOWLEDGE plan §E / Phase 0).

The user's hard condition: the experiment places ZERO orders and touches ZERO
books — proven here, not assumed. An experiment-tagged signal is forced onto
the replayed path even when its content is fresh, never dedupes against real
tips (either direction), and never scores a source.
"""
import datetime as dt

import httpx
import pytest
from sqlalchemy import select

from zargar.api.app import create_app
from zargar.domain import new_id
from zargar.engine import Engine
from zargar.models import Order, Proposal, RawContent, Signal
from zargar.signals.schemas import ExtractionResult, TradeSignal
from zargar.signals.service import attach_signal_layer, experiment_tag

from .conftest import make_test_config, wait_for

SOURCE_TEXT = """ALERT: We are buying AAPL today. Entry at $231.50, stop loss $220, target $260.
Apple remains our top pick."""


@pytest.fixture
async def app_client(fresh_db):
    config = make_test_config()
    eng = Engine(config)
    await eng.start()
    await attach_signal_layer(eng)
    app = create_app(config, eng)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, eng
    await eng.stop()


async def wait_quote(eng, symbol):
    await eng.ensure_symbol(symbol)
    await wait_for(lambda: eng.quotes.get(symbol) is not None)


def canned(stated_at: str | None = None) -> ExtractionResult:
    return ExtractionResult(
        signals=[TradeSignal(
            ticker="AAPL", direction="long", action="open",
            entry_price=231.50, target_price=260.0, stop_price=220.0,
            entry_type="limit", timeframe="swing",
            thesis_summary="Top pick.",
            evidence_quotes=["We are buying AAPL today",
                             "Entry at $231.50, stop loss $220, target $260"],
            confidence="explicit_call", is_actionable=True)],
        source_type="trade_alert",
        **({"stated_at": stated_at} if stated_at else {}))


async def _run(eng, extraction, *, source="ExpLetter", experiment=None):
    row = RawContent(id=new_id(), source_type="manual", source_name=source,
                     subject="alert", body_text=SOURCE_TEXT)
    async with eng.sf() as session:
        session.add(row)
        await session.commit()
    return await eng.signals_service.handle_extraction(
        row, extraction, source_text=SOURCE_TEXT, experiment=experiment)


async def test_experiment_signal_is_forced_out_of_band(app_client):
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    await eng.settings.set("verification.max_price_deviation_pct", 10.0)

    # FRESH content (no stated_at, would verify) + experiment tag → replayed
    out = await _run(eng, canned(), experiment="b-test")
    assert len(out) == 1
    sig = out[0]["signal"]
    assert sig["status"] == "replayed", sig["verification"]
    assert out[0]["proposal"] is None
    assert out[0]["shadowOrder"] is None
    fresh = next(c for c in sig["verification"]["checks"] if c["name"] == "fresh")
    assert "experiment batch b-test" in fresh["detail"] and fresh["fatal"]

    # tagged on the row, readable via the helper
    async with eng.sf() as session:
        db_row = await session.get(Signal, sig["id"])
        assert experiment_tag(db_row.extraction) == "b-test"

    # zero orders, zero proposals — the whole point
    async with eng.sf() as session:
        assert (await session.execute(select(Order))).scalars().all() == []
        assert (await session.execute(select(Proposal))).scalars().all() == []
    assert (await client.get("/api/proposals")).json() == []

    # scorecards never see it: the source has no card at all
    cards = (await client.get("/api/signals/sources")).json()
    assert not any(c["source"] == "ExpLetter" for c in cards)


async def test_experiment_never_dedupes_with_real_tips(app_client):
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    await eng.settings.set("verification.max_price_deviation_pct", 10.0)

    # experiment first — a REAL tip with the same dedupe key must NOT attach to it
    exp = await _run(eng, canned(), source="SameSrc", experiment="b-test")
    real = await _run(eng, canned(), source="SameSrc")
    assert real[0].get("duplicateOf") is None, "real tip deduped onto an experiment row"
    assert real[0]["signal"]["id"] != exp[0]["signal"]["id"]
    assert real[0]["signal"]["status"] != "replayed"

    # and a SECOND experiment sample must not dedupe onto the real tip either
    exp2 = await _run(eng, canned(), source="SameSrc", experiment="b-test")
    assert exp2[0].get("duplicateOf") is None
    assert exp2[0]["signal"]["status"] == "replayed"

    # the real tip still counts for the scorecard; the two experiment rows don't
    cards = (await client.get("/api/signals/sources")).json()
    card = next(c for c in cards if c["source"] == "SameSrc")
    assert card["signals"] == 1


async def test_stale_experiment_content_keeps_age_wording(app_client):
    # experiment + genuinely old stated_at keeps the age-based wording (the
    # stale gate fired on its own) and still tags the row
    client, eng = app_client
    await wait_quote(eng, "AAPL")

    from zargar.domain import Bar

    async def fake_fetch(symbol, tf, start_ms, end_ms):
        now_ms = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
        return [Bar(symbol=symbol, tf="1h", ts=now_ms - (300 - i) * 3_600_000,
                    open=100.0, high=100.6, low=99.4, close=100.0, volume=10_000)
                for i in range(300)]

    eng.signals_service._replay_fetch = fake_fetch
    stated = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=10)).isoformat()
    out = await _run(eng, canned(stated_at=stated), experiment="b-old")
    sig = out[0]["signal"]
    assert sig["status"] == "replayed"
    fresh = next(c for c in sig["verification"]["checks"] if c["name"] == "fresh")
    assert "old" in fresh["detail"]          # the age wording, not the experiment wording
    async with eng.sf() as session:
        db_row = await session.get(Signal, sig["id"])
        assert experiment_tag(db_row.extraction) == "b-old"
