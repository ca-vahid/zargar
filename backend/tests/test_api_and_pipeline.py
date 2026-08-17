"""API surface + full signal→proposal→approval pipeline (extraction stubbed)."""
import httpx
import pytest

from zargar.api.app import create_app
from zargar.engine import Engine
from zargar.models import RawContent
from zargar.domain import new_id
from zargar.signals.schemas import ExtractionResult, TradeSignal
from zargar.signals.service import attach_signal_layer

from .conftest import make_test_config, wait_for


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


async def test_health_and_state(app_client):
    client, eng = app_client
    r = await client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"]
    r = await client.get("/api/state")
    state = r.json()
    assert state["settings"]["trading.mode"] == "sim"
    assert len(state["portfolios"]) == 2
    assert state["watchlists"][0]["symbols"]
    assert state["halt"]["engaged"] is False


async def test_settings_roundtrip(app_client):
    client, _ = app_client
    r = await client.patch("/api/settings", json={"risk.max_position_notional": 2500,
                                                  "ui.theme": "light"})
    assert r.status_code == 200
    body = r.json()
    assert body["risk.max_position_notional"] == 2500
    assert body["ui.theme"] == "light"
    r = await client.patch("/api/settings", json={"bogus.key": 1})
    assert r.status_code == 400


async def test_order_via_api(app_client):
    client, eng = app_client
    pid = next(p for p in eng.positions.portfolios() if p["kind"] == "sim")["id"]
    await wait_quote(eng, "AAPL")
    r = await client.post("/api/orders", json={
        "portfolio_id": pid, "symbol": "aapl", "side": "buy", "qty": 2,
        "order_type": "MKT"})
    assert r.status_code == 200
    order = r.json()
    assert order["symbol"] == "AAPL" and order["status"] == "SUBMITTED"

    async def filled():
        rows = (await client.get("/api/orders", params={"portfolio": pid})).json()
        return any(o["status"] == "FILLED" for o in rows)
    await wait_for(filled)
    positions = (await client.get("/api/state")).json()["positions"]
    assert any(p["symbol"] == "AAPL" and p["qty"] == 2 for p in positions)


async def test_watchlist_crud_and_chart(app_client):
    client, _ = app_client
    r = await client.post("/api/watchlists", json={"name": "Tech", "symbols": ["nvda", "amd"]})
    wid = r.json()["id"]
    r = await client.put(f"/api/watchlists/{wid}",
                         json={"name": "Tech", "symbols": ["NVDA", "AMD", "MSFT"]})
    assert r.json()["symbols"] == ["NVDA", "AMD", "MSFT"]
    r = await client.get("/api/chart/NVDA", params={"tf": "5m", "limit": 50})
    assert r.status_code == 200
    assert len(r.json()["bars"]) > 0
    r = await client.delete(f"/api/watchlists/{wid}")
    assert r.json()["ok"]


async def test_halt_resume_via_api(app_client):
    client, eng = app_client
    r = await client.post("/api/halt", json={"reason": "api test"})
    assert r.json()["engaged"]
    assert eng.halt.engaged
    r = await client.post("/api/resume")
    assert not r.json()["engaged"]


async def test_ingest_without_key_stores_content(app_client):
    client, _ = app_client
    r = await client.post("/api/ingest/email", json={
        "from": "alerts@newsletter.com", "subject": "Buy XYZ", "text": "Buy XYZ now"})
    assert r.status_code == 200
    assert "extraction unavailable" in r.json().get("note", "")
    content = (await client.get("/api/content")).json()
    assert len(content) == 1
    assert content[0]["sender"] == "alerts@newsletter.com"


SOURCE_TEXT = """ALERT: We are buying AAPL today. Entry at $231.50, stop loss $220, target $260.
Apple remains our top pick."""


def canned_extraction(entry=231.50):
    return ExtractionResult(
        signals=[TradeSignal(
            ticker="AAPL", direction="long", action="open",
            entry_price=entry, target_price=260.0, stop_price=220.0,
            entry_type="limit", timeframe="swing",
            thesis_summary="Top pick.",
            evidence_quotes=["We are buying AAPL today",
                             "Entry at $231.50, stop loss $220, target $260"],
            confidence="explicit_call", is_actionable=True)],
        source_type="trade_alert")


async def run_pipeline(eng, extraction, source_text=SOURCE_TEXT):
    row = RawContent(id=new_id(), source_type="manual", source_name="TestLetter",
                     subject="alert", body_text=source_text)
    async with eng.sf() as session:
        session.add(row)
        await session.commit()
    return await eng.signals_service.handle_extraction(row, extraction,
                                                       source_text=source_text)


async def test_full_signal_to_proposal_to_execution(app_client):
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    # loosen deviation so sim price (~232) is within range of claimed 231.50
    await eng.settings.set("verification.max_price_deviation_pct", 10.0)

    out = await run_pipeline(eng, canned_extraction())
    assert len(out) == 1
    assert out[0]["signal"]["status"] == "verified", out[0]["signal"]["verification"]
    proposal = out[0]["proposal"]
    assert proposal is not None and proposal["status"] == "pending"
    assert proposal["qty"] >= 1
    assert proposal["bracket"]["take_profit"] == 260.0

    pending = (await client.get("/api/proposals")).json()
    assert len(pending) == 1

    r = await client.post(f"/api/proposals/{proposal['id']}/approve", json={"half": False})
    assert r.status_code == 200
    result = r.json()
    assert result["proposal"]["status"] == "executed"
    assert result["order"]["source"] == "signal"
    assert result["order"]["proposalId"] == proposal["id"]

    r = await client.post(f"/api/proposals/{proposal['id']}/approve")
    assert r.status_code == 400  # cannot approve twice


async def test_hallucinated_signal_never_proposed(app_client):
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    bad = canned_extraction()
    bad.signals[0].evidence_quotes = ["We are buying TSLA today"]  # not in source
    out = await run_pipeline(eng, bad)
    assert out[0]["signal"]["status"] == "verification_failed"
    assert out[0]["proposal"] is None
    assert (await client.get("/api/proposals")).json() == []


async def test_stale_price_signal_rejected(app_client):
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    await eng.settings.set("verification.max_price_deviation_pct", 0.0001)
    out = await run_pipeline(eng, canned_extraction())
    assert out[0]["signal"]["status"] == "verification_failed"
    checks = out[0]["signal"]["verification"]["checks"]
    assert any(c["name"] == "price_deviation" and not c["passed"] for c in checks)


async def test_proposal_reject_and_expiry(app_client):
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    await eng.settings.set("verification.max_price_deviation_pct", 10.0)
    out = await run_pipeline(eng, canned_extraction())
    proposal = out[0]["proposal"]
    r = await client.post(f"/api/proposals/{proposal['id']}/reject")
    assert r.json()["status"] == "rejected"

    # expiry path
    await eng.settings.set("signals.default_ttl_minutes", 0)
    out2 = await run_pipeline(eng, canned_extraction())
    assert out2[0]["proposal"] is not None
    expired = await eng.proposals.expire_due()
    assert expired == 1


async def test_shadow_portfolio_tracks_verified_signal(app_client):
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    await eng.settings.set("verification.max_price_deviation_pct", 10.0)
    out = await run_pipeline(eng, canned_extraction())
    assert out[0]["shadowOrder"] is not None
    assert out[0]["shadowOrder"]["status"] in ("SUBMITTED", "ACCEPTED", "FILLED")
    shadows = [p for p in eng.positions.portfolios() if p["kind"] == "shadow"]
    assert len(shadows) == 1
    assert shadows[0]["sourceName"] == "TestLetter"

    async def shadow_filled():
        return eng.positions.position_qty(shadows[0]["id"], "AAPL") > 0
    await wait_for(shadow_filled)
    # a second signal from the same source reuses the portfolio
    out2 = await run_pipeline(eng, canned_extraction())
    assert len([p for p in eng.positions.portfolios() if p["kind"] == "shadow"]) == 1
