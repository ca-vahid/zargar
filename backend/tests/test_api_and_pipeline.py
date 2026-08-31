"""API surface + full signal→proposal→approval pipeline (extraction stubbed)."""
import datetime as dt

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
    assert state["settings"]["trading.mode"] == "practice"
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


async def test_content_bundle_by_id(app_client):
    # The Tips UI surfaces a copyable id per Extract & verify; GET /api/content/{id}
    # is the record behind it — raw content + every signal with full verification.
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    await eng.settings.set("verification.max_price_deviation_pct", 10.0)
    out = await run_pipeline(eng, canned_extraction())
    cid = out[0]["signal"]["rawContentId"]

    r = await client.get(f"/api/content/{cid}")
    assert r.status_code == 200
    bundle = r.json()
    assert bundle["id"] == cid
    assert bundle["bodyText"] == SOURCE_TEXT
    assert len(bundle["signals"]) == 1
    sig = bundle["signals"][0]
    assert sig["id"] == out[0]["signal"]["id"]
    assert sig["ticker"] == "AAPL"
    assert sig["verification"]["checks"]  # the "verify" half rides along

    r = await client.get("/api/content/nope")
    assert r.status_code == 404


async def test_hallucinated_signal_never_proposed(app_client):
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    bad = canned_extraction()
    bad.signals[0].evidence_quotes = ["We are buying TSLA today"]  # not in source
    out = await run_pipeline(eng, bad)
    assert out[0]["signal"]["status"] == "verification_failed"
    assert out[0]["proposal"] is None
    assert (await client.get("/api/proposals")).json() == []


async def test_stale_price_signal_parked_not_killed(app_client):
    # v2 semantics (tip technique): a signal whose only failure is price
    # position is PARKED — the tip watches for the level — never proposed.
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    await eng.settings.set("verification.max_price_deviation_pct", 0.0001)
    out = await run_pipeline(eng, canned_extraction())
    assert out[0]["signal"]["status"] == "parked"
    assert out[0]["proposal"] is None
    checks = out[0]["signal"]["verification"]["checks"]
    assert any(c["name"] == "price_deviation" and not c["passed"] for c in checks)


async def test_implied_tip_trades_shadow_books_only(app_client):
    # 2026-08-28 (PeloSwing CRM case): an implied directional lean with no
    # explicit call — the commonest real-world tip shape — must reach the
    # shadow books and the scorecard, but never the proposal queue.
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    tip = ExtractionResult(
        signals=[TradeSignal(
            ticker="AAPL", direction="long", action="open",
            timeframe="swing", catalyst="buyback",
            thesis_summary="Turning off trendline support; buyback at the lows.",
            evidence_quotes=["We are buying AAPL today"],
            confidence="implied", is_actionable=False)],
        source_type="other")
    out = await run_pipeline(eng, tip)
    sig = out[0]["signal"]
    assert sig["status"] == "shadow", sig["verification"]
    checks = {c["name"]: c for c in sig["verification"]["checks"]}
    assert not checks["actionable"]["passed"] and not checks["actionable"]["fatal"]
    assert out[0]["shadowOrder"] is not None          # the immediate book bought it
    assert out[0]["proposal"] is None                 # but no proposal, ever
    assert (await client.get("/api/proposals")).json() == []
    cards = (await client.get("/api/signals/sources")).json()
    card = next(c for c in cards if c["source"] == "TestLetter")
    assert card["verified"] == 1                      # shadow counts as verified-for-books


async def test_stale_tip_replayed_not_traded(app_client):
    # content whose own visible date is older than max_tip_age_hours is
    # replayed on history (both books' counterfactuals) instead of traded
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    stated = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=10)

    from zargar.domain import Bar
    MIN = 60_000

    async def fake_fetch(symbol, tf, start_ms, end_ms):
        # 1h path: flat 100 before the tip, dip to 98.5 then rally to 112 after
        now_ms = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
        n = 300
        out = []
        for i in range(n):
            ts = now_ms - (n - i) * 60 * MIN
            frac = i / n
            c = 100.0 if frac < 0.55 else (98.5 if frac < 0.6 else 100 + (frac - 0.6) * 30)
            out.append(Bar(symbol=symbol, tf="1h", ts=ts, open=c, high=c + 0.6,
                           low=c - 0.6, close=c, volume=10_000))
        return out

    eng.signals_service._replay_fetch = fake_fetch
    tip = canned_extraction()
    tip.stated_at = stated.strftime("%Y-%m-%dT%H:%M")
    out = await run_pipeline(eng, tip)
    sig = out[0]["signal"]
    assert sig["status"] == "replayed", sig["verification"]
    assert out[0]["shadowOrder"] is None and out[0]["proposal"] is None
    replay = sig["extraction"]["replay"]
    assert replay["ok"] is True
    assert "armed" in replay and "immediate" in replay
    assert sig["extraction"]["ageHours"] > 72
    fresh = next(c for c in sig["verification"]["checks"] if c["name"] == "fresh")
    assert not fresh["passed"] and "replayed" in fresh["detail"]


async def test_immediate_book_sized_by_budget(app_client):
    # shares use the SAME per-tip budget as options (was 5% of equity) so the
    # scorecard's dollar comparisons are apples-to-apples across vehicles
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    await eng.settings.set("verification.max_price_deviation_pct", 10.0)
    await eng.settings.set("techniques.tip.budget_per_tip", 5000.0)
    out = await run_pipeline(eng, canned_extraction())
    assert out[0]["signal"]["status"] == "verified"
    order = out[0]["shadowOrder"]
    assert order is not None and order["qty"] >= 10   # ~$5000/$232 ≈ 21; 5% of 10k was 2
    expr = out[0]["signal"]["extraction"]["shadowExpression"]
    assert expr["vehicle"] == "shares" and expr["qty"] == order["qty"]
    assert expr["closeAfter"] > dt.date.today().isoformat()  # the time exit is booked


class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _FakeAnthropicResp:
    def __init__(self, content):
        self.content = content
        self.stop_reason = "end_turn"


class _FakeAnthropic:
    """Scripted analyst: one get_quote tool call, then the final JSON opinion."""

    def __init__(self):
        self.calls = 0
        self.messages = self

    async def create(self, **kw):
        self.calls += 1
        if self.calls == 1:
            return _FakeAnthropicResp([
                _Block(type="tool_use", id="tu1", name="get_quote",
                       input={"symbol": "AAPL"})])
        return _FakeAnthropicResp([_Block(type="text", text=(
            '{"verdict": "take", "instrument": "option",'
            ' "contract": "AAPL261016C00240000", "contract_label": "AAPL 240C 2026-10-16",'
            ' "limit_price": 4.6, "quantity": 2,'
            ' "invalidation": "close below 225",'
            ' "rationale": "Uptrend intact and the tip names a liquid strike.",'
            ' "confidence": 0.7,'
            ' "exit_targets": [245.0, 252.0], "exit_fractions": [0.5, 0.3],'
            ' "underlying_stop": 224.0, "premium_stop_pct": 45,'
            ' "max_hold_sessions": 8,'
            ' "exit_rationale": "Trim half at 245, more at 252, runner trails."}'))])


async def test_tips_analyst_opinion_attached(app_client):
    # the analyst agent (LLM + tools, advisory) appraises every tradable tip;
    # its opinion rides on extraction.analyst and never gates the pipeline
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    await eng.settings.set("verification.max_price_deviation_pct", 10.0)
    fake = _FakeAnthropic()
    eng.signals_service._analyst_client = fake
    tip = canned_extraction()
    tip.signals[0].premium = 4.60                     # alert-room "At 4.60"
    out = await run_pipeline(eng, tip)
    sig = out[0]["signal"]
    assert sig["status"] == "verified"
    assert sig["premium"] == 4.60                     # premium survives extraction->row->wire
    a = sig["extraction"]["analyst"]
    assert a["verdict"] == "take" and a["quantity"] == 2
    assert a["toolsUsed"] == [{"tool": "get_quote", "args": {"symbol": "AAPL"}}]
    assert fake.calls == 2                            # tool round + final answer
    # a full analyst run was persisted with the play-by-play, listable + fetchable
    assert a["runId"]
    runs = (await client.get("/api/tip/analyst/runs")).json()
    assert any(r["id"] == a["runId"] and r["status"] == "done" for r in runs)
    run = (await client.get(f"/api/tip/analyst/runs/{a['runId']}")).json()
    assert run["ticker"] == "AAPL" and run["verdict"] == "take"
    kinds = [s["kind"] for s in run["trace"]]
    assert "start" in kinds and "tool_call" in kinds and "tool_result" in kinds and "final" in kinds
    assert "get_quote" in run["tools"]                # tools available recorded
    assert (await client.get("/api/tip/analyst/runs/nope")).status_code == 404
    # journaled as SignalAnalyzed
    from sqlalchemy import select as _sel
    from zargar.models import Event
    async with eng.sf() as session:
        kinds = (await session.execute(
            _sel(Event.type).where(Event.aggregate_id == sig["id"]))).scalars().all()
    assert "SignalAnalyzed" in kinds


async def test_option_tip_proposal_is_the_contract(app_client):
    # the proposal trades the SAME vehicle the books do: with an analyst "take"
    # naming a contract, the proposal is BUY that option — never shares at the
    # underlying price (bug 2026-08-28: SPY 750P tip proposed SELL 1 SPY @ 769)
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    await eng.settings.set("verification.max_price_deviation_pct", 10.0)
    eng.signals_service._analyst_client = _FakeAnthropic()
    out = await run_pipeline(eng, canned_extraction())
    p = out[0]["proposal"]
    assert p is not None, "verified explicit call should still propose"
    assert p["secType"] == "OPT" and p["side"] == "BUY"
    assert p["symbol"] == "AAPL261016C00240000"
    assert p["qty"] == 2 and p["limitPrice"] and p["limitPrice"] > 0
    ctx = p["context"]
    assert ctx["analystRunId"] and ctx["analyst"]["verdict"] == "take"
    assert ctx["vehicle"]["kind"] == "option" and ctx["vehicle"]["optionType"] == "call"
    assert ctx["vehicle"]["pickedBy"] == "analyst"
    assert "Approve = buy 2 contracts" in ctx["explain"]
    assert p["bracket"] is None                        # underlying prices never bracket an option


async def test_lotto_premium_contract_qty_is_capped(app_client):
    # budget sizing on lotto premium proposed 277 × a $0.09 call (2026-08-31);
    # techniques.tip.max_contracts_per_tip caps every option sizing site, the
    # analyst's stated count included. 0 disables the cap.
    client, eng = app_client
    assert eng.proposals._cap_contracts(277) == 25
    assert eng.proposals._cap_contracts(3) == 3
    await eng.settings.set("techniques.tip.max_contracts_per_tip", 0)
    assert eng.proposals._cap_contracts(277) == 277


async def test_short_tip_without_put_never_proposes_share_short(app_client):
    # shorts are puts only — a bearish tip with no usable contract makes NO
    # proposal (the old builder proposed SELL shares, which is never allowed)
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    await eng.settings.set("verification.max_price_deviation_pct", 10.0)
    q = eng.quotes.get("AAPL")
    entry, tgt, stop = round(q.last, 2), round(q.last * 0.85, 2), round(q.last * 1.05, 2)
    text = (f"ALERT: We are shorting AAPL today. Entry at ${entry}, "
            f"stop loss ${stop}, target ${tgt}.")
    tip = canned_extraction(entry=entry)
    tip.signals[0].direction = "short"
    tip.signals[0].target_price = tgt
    tip.signals[0].stop_price = stop
    tip.signals[0].evidence_quotes = [f"Entry at ${entry}, stop loss ${stop}, target ${tgt}"]
    out = await run_pipeline(eng, tip, source_text=text)
    sig = out[0]["signal"]
    assert sig["status"] == "verified", sig["verification"]
    assert out[0]["proposal"] is None
    expr = sig["extraction"]["shadowExpression"]
    assert "short tip needs a put" in (expr.get("note") or "")


async def test_auto_mode_self_approves(app_client):
    # a source in auto mode approves its own proposal (same approve() path a
    # human click takes — RiskGate inside), decided_via "auto"
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    await eng.settings.set("verification.max_price_deviation_pct", 10.0)
    await eng.settings.set("techniques.tip.sources", {"TestLetter": {"mode": "auto"}})
    out = await run_pipeline(eng, canned_extraction())
    p = out[0]["proposal"]
    assert p is not None
    assert p["status"] == "executed", p
    assert p["decidedVia"] == "auto" and p["orderId"]


class _FakeAnthropicBroken:
    """Analyst that produces an unparseable reply — the run FAILS."""

    def __init__(self):
        self.messages = self

    async def create(self, **kw):
        return _FakeAnthropicResp([_Block(type="text", text="I am unable to comply.")])


class _FakeAnthropicFlakyReply:
    """First reply has no JSON; the retry delivers the opinion."""

    def __init__(self):
        self.calls = 0
        self.messages = self

    async def create(self, **kw):
        self.calls += 1
        if self.calls == 1:
            return _FakeAnthropicResp([_Block(type="text",
                                              text="Thinking out loud, no JSON here.")])
        return _FakeAnthropicResp([_Block(type="text", text=(
            '{"verdict": "watch", "instrument": "shares",'
            ' "rationale": "Retry delivered.", "confidence": 0.5}'))])


async def test_unparseable_reply_retries_once_and_recovers(app_client):
    # the retry turns a would-be failed run into a real verdict (tick-5 fix)
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    await eng.settings.set("verification.max_price_deviation_pct", 10.0)
    fake = _FakeAnthropicFlakyReply()
    eng.signals_service._analyst_client = fake
    out = await run_pipeline(eng, canned_extraction())
    sig = out[0]["signal"]
    assert fake.calls == 2
    assert (sig["extraction"].get("analyst") or {}).get("verdict") == "watch"


async def test_failed_appraisal_fails_auto_approve_closed(app_client):
    # TSLA 2026-08-31: an appraisal that crashed left no verdict, and auto mode
    # read "no verdict" as "analyst off" — buying 15 two-DTE puts with zero
    # judgment. An ATTEMPTED appraisal with no verdict leaves the proposal
    # PENDING for the human; only a real "take" (or analyst not configured)
    # self-approves.
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    await eng.settings.set("verification.max_price_deviation_pct", 10.0)
    await eng.settings.set("techniques.tip.sources", {"TestLetter": {"mode": "auto"}})
    eng.signals_service._analyst_client = _FakeAnthropicBroken()
    out = await run_pipeline(eng, canned_extraction())
    p = out[0]["proposal"]
    assert p is not None, "the proposal is still minted — only the approval is gated"
    assert p["status"] == "pending", p
    assert not p.get("decidedVia")


async def test_take_fill_adopts_position_under_analyst_exits(app_client):
    # the whole lifecycle: analyst "take" (with exit plan) → auto-approved OPT
    # proposal → fill → durable managed position running the ANALYST'S ladder
    import asyncio as _aio

    from zargar.domain import Quote
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    await eng.settings.set("verification.max_price_deviation_pct", 10.0)
    await eng.settings.set("techniques.tip.sources", {"TestLetter": {"mode": "auto"}})
    # NOTE (found here): the $1000 per-tip budget outruns the platform's 5%-of-
    # equity option premium cap on the $10k practice book — raise it for the test
    # the way a real config would have to
    await eng.settings.set("risk.max_option_premium_pct", 15.0)
    eng.signals_service._analyst_client = _FakeAnthropic()
    occ = "AAPL261016C00240000"
    # keep the REAL chain out of the test: order placement tracks the contract
    # and the options service would overlay live CBOE bid/ask over our quote
    import httpx as _hx
    from zargar.options.chain import CboeClient
    eng.options.use_client(CboeClient(_hx.AsyncClient(
        transport=_hx.MockTransport(lambda _req: _hx.Response(404, json={})))))
    # the risk gate and the sim executor both need a live option quote
    for _ in range(2):
        eng.quotes.on_quote(Quote(symbol=occ, bid=4.4, ask=4.6, last=4.5,
                                  bid_size=500, ask_size=500, volume=100))
    out = await run_pipeline(eng, canned_extraction())
    p = out[0]["proposal"]
    assert p is not None and p["secType"] == "OPT"
    if p["status"] != "executed":                        # show the reject reason
        import json as _j
        orders = (await client.get("/api/orders")).json()
        q_now = eng.quotes.get(occ)
        raise AssertionError(f"occ quote now: {q_now}\n"
                             + _j.dumps(orders, indent=1, default=str)[:1500])
    assert p["decidedVia"] == "auto"
    plan = p["context"]["exitPlan"]
    assert plan["author"] == "analyst" and plan["targets"] == [245.0, 252.0]
    assert plan["underlyingStop"] == 224.0 and plan["maxHoldSessions"] == 8

    async def adopted():
        # the sim executor fills only once it has a fresh option quote (post-latency)
        for _ in range(2):
            eng.quotes.on_quote(Quote(symbol=occ, bid=4.4, ask=4.6, last=4.5,
                                      bid_size=500, ask_size=500, volume=100))
        await _aio.sleep(0.15)
        return any(x["technique"] == "tip" and x["status"] == "open"
                   for x in eng.position_manager.positions())
    await wait_for(adopted, timeout=15)

    pos = next(x for x in eng.position_manager.positions()
               if x["technique"] == "tip" and x["status"] == "open")
    pol = pos["policy"]
    assert pol["ladder"] == {"targets": [245.0, 252.0], "fractions": [0.5, 0.3]}
    assert pol["stop"] == {"kind": "fixed", "price": 224.0}
    assert pol["premium_stop_pct"] == 45.0 and pol["time_stop_sessions"] == 8
    assert pos["direction"] == "long" and pos["symbol"] == "AAPL"
    assert pos["runId"] == p["context"]["analystRunId"]   # links back to the reasoning
    assert pos["overnight"] == "app_managed" and pos["overnightAck"]
    leg = pos["legs"][0]
    assert leg["symbol"] == occ and leg["secType"] == "OPT" and leg["qty"] == 2
    # journaled adoption (the note lands just after the adopt itself)
    from sqlalchemy import select as _sel
    from zargar.models import Event

    async def journaled():
        async with eng.sf() as session:
            kinds = (await session.execute(
                _sel(Event.type).where(Event.aggregate_id == p["id"]))).scalars().all()
        return "TipPositionAdopted" in kinds
    await wait_for(journaled)


async def test_discord_mirror_and_search(app_client):
    # the source's history is mirrored and searchable (follow-ups are context)
    client, eng = app_client
    src = "🌞 | jon-and-kian"
    msgs = [{"id": "m1", "channelId": "42", "source": src, "author": "Clanker [bot]",
             "authorId": "99", "isBot": True, "guild": "OWLS Capital",
             "text": "OPEN: NVDA 190C 10/17 Exp. At 4.20",
             "postedAt": "2026-08-28T09:53:49+00:00"},
            {"id": "m2", "channelId": "42", "source": src, "author": "Clanker [bot]",
             "isBot": True, "text": "sold 40% of the NVDA runner, house money now",
             "images": ["https://cdn.discordapp.com/x.png"],
             "postedAt": "2026-08-28T14:10:00+00:00"}]
    r = await client.post("/api/tip/discord/messages", json={"messages": msgs})
    assert r.json() == {"stored": 2}
    r = await client.post("/api/tip/discord/messages", json={"messages": msgs})
    assert r.json() == {"stored": 0}                     # dedupe on message id
    rows = (await client.get("/api/tip/discord/messages",
                             params={"source": src, "contains": "sold"})).json()
    assert len(rows) == 1 and rows[0]["id"] == "m2" and rows[0]["images"]
    # newest first, and the analyst tool sees the same story
    rows = (await client.get("/api/tip/discord/messages", params={"source": src})).json()
    assert [x["id"] for x in rows] == ["m2", "m1"]
    from zargar.techniques.tip.analyst import _run_tool, _source_history
    out = await _run_tool(eng, "search_messages", {"source": src, "contains": "NVDA"})
    assert len(out["messages"]) == 2
    hist = await _source_history(eng, src, hours=24 * 365)
    assert "sold 40%" in hist and "[images: m2 — view_image to look]" in hist
    # coverage stats drive the gateway's onboarding (how far back to fetch)
    stats = (await client.get("/api/tip/discord/mirror-stats")).json()
    assert stats["42"]["count"] == 2 and stats["42"]["oldestId"] == "m1"
    # pagination for the viewer: strictly older than m2 → only m1
    older = (await client.get("/api/tip/discord/messages",
                              params={"before": "2026-08-28T14:10:00+00:00"})).json()
    assert [x["id"] for x in older] == ["m1"]


async def test_mirror_downloads_image_bytes(app_client, tmp_path):
    # images are downloaded at mirror time (CDN links expire; the LLM cannot
    # fetch URLs) — served from OUR store, viewable by the analyst
    client, eng = app_client
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64

    async def fake_fetch(url):
        return png
    eng.signals_service._media_fetch = fake_fetch
    eng.signals_service.MEDIA_DIR = str(tmp_path / "media")
    r = await client.post("/api/tip/discord/messages", json={"messages": [
        {"id": "img1", "channelId": "42", "source": "src", "author": "bot", "isBot": True,
         "text": "chart only", "images": ["https://cdn.discordapp.com/attachments/a/b/c.png"],
         "postedAt": "2026-08-29T10:00:00+00:00"}]})
    assert r.json()["stored"] == 1

    async def downloaded():
        m = await eng.signals_service.discord_get_message("img1")
        return (m.get("localImages") or []) == ["img1-0.png"]
    await wait_for(downloaded)
    resp = await client.get("/api/tip/discord/media/img1/0")
    assert resp.status_code == 200 and resp.headers["content-type"] == "image/png"
    assert resp.content == png
    # the analyst can LOOK at it (image block, not a URL)
    from zargar.techniques.tip.analyst import _run_tool
    out = await _run_tool(eng, "view_image", {"message_id": "img1"})
    assert out["_media_type"] == "image/png" and out["_image_b64"]
    out = await _run_tool(eng, "view_image", {"message_id": "nope"})
    assert "unavailable" in out["error"]
    assert (await client.get("/api/tip/discord/media/nope/0")).status_code == 404


async def test_analyst_run_parent_child_linkage(app_client):
    # an intake run and the appraisals it spawned link both ways in the API
    client, eng = app_client
    from zargar.models import TipAnalystRun
    async with eng.sf() as session:
        session.add(TipAnalystRun(id="par1", ticker="GOOGL · AAPL", source="eva",
                                  status="done", kind="intake", verdict="1 tip"))
        session.add(TipAnalystRun(id="kid1", ticker="GOOGL", source="eva",
                                  status="done", verdict="watch", parent_id="par1"))
        await session.commit()
    run = (await client.get("/api/tip/analyst/runs/par1")).json()
    assert run["children"] == [{"id": "kid1", "ticker": "GOOGL",
                                "verdict": "watch", "status": "done"}]
    kid = (await client.get("/api/tip/analyst/runs/kid1")).json()
    assert kid["parentId"] == "par1"
    rows = (await client.get("/api/tip/analyst/runs")).json()
    assert next(r for r in rows if r["id"] == "kid1")["parentId"] == "par1"


async def test_adhoc_analysis_of_mirrored_message(app_client):
    # any past mirrored message can be run through the pipeline on demand;
    # the outcome lands in the same process-result store the banner polls
    client, eng = app_client
    from zargar.models import DiscordMessage
    async with eng.sf() as session:
        session.add(DiscordMessage(id="adhoc1", channel_id="42", source_name="TestLetter",
                                   author="Clanker [bot]", is_bot=True,
                                   text="OPEN: NVDA 190C 10/17 Exp. At 4.20"))
        await session.commit()
    r = await client.post("/api/tip/discord/analyze-message", json={"messageId": "adhoc1"})
    assert r.status_code == 200 and r.json()["key"] == "msg:adhoc1"

    async def landed():
        out = (await client.get("/api/tip/discord/process-result",
                                params={"channelId": "msg:adhoc1"})).json()
        # the pending marker lands instantly (keeps the banner honest); wait
        # for the FINAL result
        return out["result"] is not None and not out["result"].get("pending")
    await wait_for(landed)
    out = (await client.get("/api/tip/discord/process-result",
                            params={"channelId": "msg:adhoc1"})).json()["result"]
    # no LLM key in tests: the pipeline reports honestly instead of going silent
    assert out["author"].startswith("Clanker")
    assert out.get("note") or out.get("error") or out.get("signals") is not None
    # unknown message = 404, no ghost banner
    r = await client.post("/api/tip/discord/analyze-message", json={"messageId": "nope"})
    assert r.status_code == 404


async def test_mirror_media_catchup_rescues_url_only_rows(app_client, tmp_path):
    # rows mirrored before the local store existed (URL-only) get their bytes
    # downloaded by the startup catch-up sweep — while the links still live
    client, eng = app_client
    png = b"\x89PNG\r\n\x1a\n" + b"1" * 32

    async def fake_fetch(url):
        return png
    eng.signals_service._media_fetch = fake_fetch
    eng.signals_service.MEDIA_DIR = str(tmp_path / "media")
    from zargar.models import DiscordMessage
    async with eng.sf() as session:
        session.add(DiscordMessage(id="old1", channel_id="42", source_name="src",
                                   author="bot", is_bot=True, text="old chart",
                                   images=["https://cdn.discordapp.com/a.png"],
                                   local_images=[]))
        await session.commit()
    out = await eng.signals_service.discord_media_catchup()
    assert out["saved"] == 1 and out["unavailable"] == 0
    m = await eng.signals_service.discord_get_message("old1")
    assert m["localImages"] == ["old1-0.png"]
    # idempotent: nothing left to rescue
    assert (await eng.signals_service.discord_media_catchup())["candidates"] == 0


async def test_analyst_manage_tools_exit_only(app_client):
    # update_exit_plan / close_position: the analyst steers OPEN tip positions
    # (exit-only), and only tip positions
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    q = eng.quotes.get("AAPL")
    pid = next(p for p in eng.positions.portfolios() if p["kind"] == "sim")["id"]
    entry = round(q.last, 2)
    spec = {"portfolioId": pid, "symbol": "AAPL", "direction": "long",
            "techniqueId": "tip", "entry": entry, "risk": 5.0,
            "legs": [{"symbol": "AAPL", "secType": "STK", "qty": 10,
                      "avgFill": entry, "origin": "adoption"}],
            "policy": {"timeframe": "15m",
                       "stop": {"kind": "fixed", "price": round(entry * 0.95, 2)}}}
    pos = await eng.position_manager.adopt(spec)
    em = await eng.position_manager.adopt({**spec, "techniqueId": "enhanced_market"})

    from zargar.techniques.tip.analyst import _run_tool
    ctx = {"run_id": "testrun1", "ticker": "AAPL", "source": "TestLetter"}
    out = await _run_tool(eng, "update_exit_plan", {
        "position_id": pos["id"], "exit_targets": [round(entry * 1.04, 2)],
        "exit_fractions": [0.5], "underlying_stop": round(entry * 0.97, 2),
        "max_hold_sessions": 4, "reason": "source trimmed 40% — tighten"}, ctx=ctx)
    assert out.get("updated"), out
    p2 = eng.position_manager.get(pos["id"])
    assert p2.policy["ladder"]["targets"] == [round(entry * 1.04, 2)]
    assert p2.policy["time_stop_sessions"] == 4
    assert p2.state.stop == round(entry * 0.97, 2)       # tightened stop applies live
    # not yours: another technique's position is refused
    out = await _run_tool(eng, "update_exit_plan", {
        "position_id": em["id"], "reason": "nope"}, ctx=ctx)
    assert "not yours" in out.get("error", "")
    # a reason is mandatory (it is journaled)
    out = await _run_tool(eng, "close_position", {"position_id": pos["id"]}, ctx=ctx)
    assert "reason" in out.get("error", "")
    out = await _run_tool(eng, "close_position", {
        "position_id": pos["id"], "fraction": 1.0,
        "reason": "source closed the trade"}, ctx=ctx)
    assert out.get("closed"), out
    # the journal carries the exit-plan change
    from sqlalchemy import select as _sel
    from zargar.models import Event
    async with eng.sf() as session:
        kinds = (await session.execute(
            _sel(Event.type).where(Event.aggregate_id == pos["id"]))).scalars().all()
    assert "TipExitPlanUpdated" in kinds
    # off-switch
    await eng.settings.set("techniques.tip.analyst_manage_enabled", False)
    out = await _run_tool(eng, "update_exit_plan",
                          {"position_id": em["id"], "reason": "x"}, ctx=ctx)
    assert "disabled" in out.get("error", "")


class _FakeAnthropicRetro:
    """Scripted retro: saves a rule, then grades the trade."""

    def __init__(self):
        self.calls = 0
        self.messages = self
        self.seen_header = ""

    async def create(self, **kw):
        self.calls += 1
        if self.calls == 1:
            self.seen_header = kw["messages"][0]["content"]
            return _FakeAnthropicResp([
                _Block(type="tool_use", id="tu1", name="save_note",
                       input={"scope": "rule",
                              "text": "Cut hedge positions at 40% premium bleed — "
                                      "evidence: position pos-retro-1."})])
        return _FakeAnthropicResp([_Block(type="text", text=(
            '{"grade": "bad_call", "what_worked": "Sizing was small.",'
            ' "what_didnt": "Chased premium after the alert.",'
            ' "rule_update": "Cut hedge positions at 40% premium bleed.",'
            ' "confidence": 0.7}'))])


async def test_retro_sweep_teaches_rules(app_client):
    # a closed tip position gets ONE retro: run persisted (kind=retro), a rule
    # saved to the knowledge base, the position tagged so it never re-retros
    client, eng = app_client
    from zargar.models import ManagedPositionRow
    async with eng.sf() as session:
        session.add(ManagedPositionRow(
            id="pos-retro-1", technique="tip", symbol="SPY", portfolio_id="pf1",
            status="closed", tags=["source:TestLetter", "proposal"],
            config={"direction": "short", "entry": 769.3, "risk": 5.0,
                    "policy": {"ladder": {"targets": [760.0], "fractions": [0.5]}},
                    "runId": None, "entryMark": 3.4},
            legs=[{"symbol": "SPY260918P00750000", "secType": "OPT", "qty": 0,
                   "avgFill": 3.4, "multiplier": 100.0}],
            state={"realizedPnl": -230.0, "sessionsSeen": ["2026-08-26", "2026-08-27"],
                   "exits": [{"kind": "premium_stop", "reason": "bled 50%"}],
                   "events": [{"what": "closed", "text": "premium stop"}]}))
        await session.commit()
    from zargar.techniques.tip.retro import run_tip_retros
    fake = _FakeAnthropicRetro()
    out = await run_tip_retros(eng, client=fake)
    assert out["retros"] == 1 and out["failed"] == 0
    assert "CLOSED POSITION" in fake.seen_header and "YOUR TRADING RULES" in fake.seen_header
    runs = (await client.get("/api/tip/analyst/runs")).json()
    rr = next(r for r in runs if r["kind"] == "retro")
    assert rr["ticker"] == "SPY" and rr["status"] == "done"
    run = (await client.get(f"/api/tip/analyst/runs/{rr['id']}")).json()
    assert run["opinion"]["grade"] == "bad_call"
    assert run["opinion"]["positionId"] == "pos-retro-1"
    rules = (await client.get("/api/tip/notes", params={"scope": "rule"})).json()
    assert len(rules) == 1 and "premium bleed" in rules[0]["text"]
    # exactly once: the tag stops a second retro
    out2 = await run_tip_retros(eng, client=_FakeAnthropicRetro())
    assert out2["retros"] == 0 and out2["failed"] == 0


class _FakeAnthropicAtLevel:
    """Scripted analyst: take, but WAIT for the level (ARM-PLAN P1)."""

    def __init__(self):
        self.calls = 0
        self.messages = self

    async def create(self, **kw):
        self.calls += 1
        return _FakeAnthropicResp([_Block(type="text", text=(
            '{"verdict": "take", "instrument": "option",'
            ' "contract": "AAPL261016C00240000", "contract_label": "AAPL 240C 2026-10-16",'
            ' "limit_price": 4.6, "quantity": 2,'
            ' "entry_mode": "at_level", "entry_level": 225.0,'
            ' "entry_note": "extended — wait for the retest",'
            ' "exit_targets": [245.0], "exit_fractions": [0.5],'
            ' "underlying_stop": 220.0, "max_hold_sessions": 7,'
            ' "rationale": "Good tip, wrong price — arm the retest.",'
            ' "confidence": 0.66}'))])


async def test_take_at_level_arms_instead_of_proposing(app_client):
    # ARM-PLAN P1: the analyst chooses WHEN — at_level arms a waiting plan in
    # the source's mode; no tip-time proposal is minted
    client, eng = app_client
    from zargar.techniques.tip.runner import attach_tip_runner
    await attach_tip_runner(eng)                      # the arm lane needs the runner
    await wait_quote(eng, "AAPL")
    await eng.settings.set("verification.max_price_deviation_pct", 10.0)
    eng.signals_service._analyst_client = _FakeAnthropicAtLevel()
    out = await run_pipeline(eng, canned_extraction())
    item = out[0]
    assert item["proposal"] is None, "at_level must not mint a tip-time proposal"
    armed = item["armed"]
    assert armed is not None and armed["technique"] == "tip"
    assert armed["config"]["mode"] == "proposal"       # the source's default mode
    [trig] = armed["triggers"]
    assert trig["entry"] == 225.0                      # the ANALYST'S level, not the tip's
    sig = item["signal"]
    assert sig["extraction"]["analyst"]["armedRunId"] == armed["runId"]
    # journaled lane decision
    from sqlalchemy import select as _sel
    from zargar.models import Event
    async with eng.sf() as session:
        rows = (await session.execute(
            _sel(Event.payload).where(Event.type == "TipLaneDecided"))).scalars().all()
    assert any(r.get("lane") == "arm" and r.get("armedRunId") == armed["runId"]
               for r in rows)


async def test_resume_pending_adoptions_after_restart(app_client):
    # ARM-PLAN P2: an approved tip proposal whose order was resting at shutdown
    # is adopted on boot; already-adopted ones are skipped (idempotent)
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    pid = next(p for p in eng.positions.portfolios() if p["kind"] == "sim")["id"]
    from zargar.models import Order, Proposal
    occ = "AAPL261016C00240000"
    async with eng.sf() as session:
        session.add(Order(id="ord-r1", portfolio_id=pid, symbol=occ, sec_type="OPT",
                          side="BUY", qty=2, order_type="LMT", limit_price=4.6,
                          status="FILLED", filled_qty=2, avg_fill_price=4.5,
                          source="signal"))
        session.add(Proposal(id="prop-r1", portfolio_id=pid, symbol=occ, sec_type="OPT",
                             side="BUY", qty=2, order_type="LMT", limit_price=4.6,
                             status="executed", order_id="ord-r1",
                             context={"techniqueId": "tip", "sourceName": "TestLetter",
                                      "vehicle": {"kind": "option", "underlying": "AAPL",
                                                  "optionType": "call"},
                                      "exitPlan": {"targets": [245.0], "fractions": [1.0],
                                                   "underlyingStop": 224.0,
                                                   "maxHoldSessions": 5,
                                                   "avoidEarnings": True},
                                      "signalPrices": {"entry": 231.5}},
                             expires_at=dt.datetime.now(dt.timezone.utc)
                             + dt.timedelta(hours=1)))
        await session.commit()
    from zargar.techniques.tip.lifecycle import resume_pending_adoptions
    assert await resume_pending_adoptions(eng) == 1

    async def adopted():
        for p in eng.position_manager.positions():
            if p.get("technique") == "tip" and any(
                    l.get("entryOrderId") == "ord-r1" for l in p.get("legs", [])):
                return p
        return None
    pos = await wait_for(adopted, timeout=10)
    assert pos["policy"]["ladder"]["targets"] == [245.0]
    assert pos["policy"]["stop"] == {"kind": "fixed", "price": 224.0}
    # idempotent: the adopted order is not re-armed
    assert await resume_pending_adoptions(eng) == 0


class _FakeAnthropicNotes:
    """Scripted analyst: saves a note first, then answers 'watch'."""

    def __init__(self):
        self.calls = 0
        self.messages = self
        self.seen_header = ""

    async def create(self, **kw):
        self.calls += 1
        if self.calls == 1:
            self.seen_header = kw["messages"][0]["content"]
            return _FakeAnthropicResp([
                _Block(type="tool_use", id="tu1", name="save_note",
                       input={"scope": "ticker",
                              "text": "Puts on this name are hedges for the source's Oct-Dec calls."})])
        return _FakeAnthropicResp([_Block(type="text", text=(
            '{"verdict": "watch", "instrument": "shares",'
            ' "rationale": "Hedge context noted; not a directional call to chase.",'
            ' "confidence": 0.6}'))])


async def test_shared_notes_read_and_written_by_analyst(app_client):
    # the shared knowledge loop: a saved note is handed to the next run's
    # prompt; the analyst can save its own via the save_note tool
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    await eng.settings.set("verification.max_price_deviation_pct", 10.0)
    r = await client.post("/api/tip/notes", json={
        "scope": "ticker:AAPL", "text": "Source often trims within 2 sessions."})
    assert r.status_code == 200 and r.json()["author"] == "user"
    fake = _FakeAnthropicNotes()
    eng.signals_service._analyst_client = fake
    out = await run_pipeline(eng, canned_extraction())
    sig = out[0]["signal"]
    assert "often trims within 2 sessions" in fake.seen_header   # injected knowledge
    # the analyst's own note persisted, scoped to the ticker, authored by the run
    notes = (await client.get("/api/tip/notes")).json()
    an = next(n for n in notes if n["author"].startswith("analyst:"))
    assert an["scope"] == "ticker:AAPL" and "Oct-Dec calls" in an["text"]
    assert an["signalId"] == sig["id"] and an["runId"]
    # scoped fetch + the run trace shows the save
    scoped = (await client.get("/api/tip/notes", params={"scope": "ticker:AAPL"})).json()
    assert len(scoped) == 2
    run = (await client.get(f"/api/tip/analyst/runs/{an['runId']}")).json()
    assert any(s["kind"] == "tool_call" and s.get("tool") == "save_note" for s in run["trace"])
    # journaled + deletable
    from sqlalchemy import select as _sel
    from zargar.models import Event
    async with eng.sf() as session:
        kinds = (await session.execute(
            _sel(Event.type).where(Event.type == "TipNoteAdded"))).scalars().all()
    assert len(kinds) == 2
    assert (await client.delete(f"/api/tip/notes/{an['id']}")).status_code == 200
    assert (await client.delete(f"/api/tip/notes/{an['id']}")).status_code == 404


class _FakeExtractor:
    """Canned extraction so process_content (and its intake run) can be driven
    end-to-end without the API."""
    available = True
    model = "fake-extractor"

    def __init__(self, result):
        self.result = result

    async def extract(self, text, **kw):
        return self.result


class _FlakyExtractor(_FakeExtractor):
    """Fails with a transient 529-style error N times, then extracts."""

    def __init__(self, result, fail_times=2):
        super().__init__(result)
        self.fail_times = fail_times
        self.calls = 0

    async def extract(self, text, **kw):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("Error code: 529 - overloaded_error: Overloaded")
        return self.result


async def test_transient_extraction_error_retries(app_client, monkeypatch):
    # a 529 Overloaded dropped a real tip outright (2026-08-31) — process_content
    # now retries transient API errors twice before giving up
    client, eng = app_client
    monkeypatch.setattr(type(eng.signals_service), "_extract_retry_delays", (0.0, 0.0))
    flaky = _FlakyExtractor(canned_extraction(), fail_times=2)
    eng.signals_service.extractor = flaky
    row = RawContent(id=new_id(), source_type="manual", source_name="TestLetter",
                     subject="alert", body_text=SOURCE_TEXT)
    async with eng.sf() as session:
        session.add(row)
        await session.commit()
    out = await eng.signals_service.process_content(row.id)
    assert flaky.calls == 3
    assert out.get("status") != "error", out


class _FakeAnthropicReview:
    """Scripted review: looks at OUR positions and the source's open tips,
    saves a note, then reports — flagging the line that was actually fresh."""

    def __init__(self):
        self.calls = 0
        self.messages = self

    async def create(self, **kw):
        self.calls += 1
        if self.calls == 1:
            return _FakeAnthropicResp([
                _Block(type="tool_use", id="t1", name="get_positions", input={}),
                _Block(type="tool_use", id="t2", name="get_open_tips",
                       input={"source": "EvaPanda"})])
        if self.calls == 2:
            return _FakeAnthropicResp([
                _Block(type="tool_use", id="t3", name="save_note",
                       input={"scope": "source",
                              "text": "Source's open book: AAPL 300C swing added 08-28."})])
        return _FakeAnthropicResp([_Block(type="text", text=(
            '{"headline": "Positions recap from EvaPanda, one fresh add.",'
            ' "details": "Recap lines match the source\'s known book; nothing we hold overlaps.",'
            ' "watch": ["AAPL"],'
            ' "missed_tip": "AAPL 300C 10/16 was added today — a fresh actionable line",'
            ' "confidence": 0.6}'))])


async def test_intake_run_reviews_non_tradable_updates(app_client):
    # a positions-recap message used to dead-end ("no analyst run") — now the
    # message gets ONE streamed intake run: extraction, per-signal verdicts with
    # reasons, then the analyst reviewing the update against OUR book
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    text = ("Update: Current Open Positions — AAPL 300C 10/16 @ 2.34 (Swing) - "
            "Added Today. All that i have for now.")
    recap = ExtractionResult(signals=[TradeSignal(
        ticker="AAPL", direction="long", action="open", instrument="call",
        thesis_summary="positions recap",
        evidence_quotes=["AAPL 300C 10/16 @ 2.34"],
        confidence="commentary_only", is_actionable=False)],
        source_type="portfolio_update")
    eng.signals_service.extractor = _FakeExtractor(recap)
    fake = _FakeAnthropicReview()
    eng.signals_service._analyst_client = fake
    out = await eng.signals_service.ingest_manual(text, source_name="EvaPanda")
    assert out["intakeRunId"]
    assert out["signals"][0]["signal"]["status"] == "verification_failed"
    run = (await client.get(f"/api/tip/analyst/runs/{out['intakeRunId']}")).json()
    assert run["kind"] == "intake" and run["status"] == "done"
    assert run["verdict"] == "review" and run["ticker"] == "AAPL"
    kinds = [s["kind"] for s in run["trace"]]
    for k in ("start", "extract", "signal", "tool_call", "tool_result", "final"):
        assert k in kinds, f"missing {k} in {kinds}"
    tools = [s.get("tool") for s in run["trace"] if s["kind"] == "tool_call"]
    assert "get_positions" in tools and "get_open_tips" in tools
    # the review's verdict card carries the missed-tip flag for the human
    assert "added today" in (run["opinion"]["missedTip"] or "").lower()
    assert run["opinion"]["watch"] == ["AAPL"]
    # the durable note landed in the shared knowledge base
    notes = (await client.get("/api/tip/notes")).json()
    assert any("open book" in n["text"] for n in notes)
    # the run shows in the list as an intake run
    runs = (await client.get("/api/tip/analyst/runs")).json()
    assert any(r["id"] == out["intakeRunId"] and r["kind"] == "intake" for r in runs)


async def test_intake_run_hands_off_to_appraisal(app_client):
    # a tradable alert's intake run records the whole path and links the
    # appraisal run (kind stays 'appraise' for the per-tip run)
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    await eng.settings.set("verification.max_price_deviation_pct", 10.0)
    eng.signals_service.extractor = _FakeExtractor(canned_extraction())
    eng.signals_service._analyst_client = _FakeAnthropic()
    out = await eng.signals_service.ingest_manual(SOURCE_TEXT, source_name="TestLetter")
    assert out["signals"][0]["signal"]["status"] in ("verified", "proposed")
    run = (await client.get(f"/api/tip/analyst/runs/{out['intakeRunId']}")).json()
    assert run["kind"] == "intake" and run["status"] == "done"
    assert run["verdict"] == "1 tip"
    hand = next(s for s in run["trace"] if s["kind"] == "handoff")
    assert hand["runId"]
    appraisal = (await client.get(f"/api/tip/analyst/runs/{hand['runId']}")).json()
    assert appraisal["kind"] == "appraise" and appraisal["verdict"] == "take"


async def test_missing_quote_parks_signal(app_client):
    # "no market data" is a feed state, not a bad tip (the AMZN case): the
    # signal parks and is re-judged when data arrives — never fatally killed
    client, eng = app_client
    from zargar.signals.verification import verify_signal
    sig = canned_extraction().signals[0].model_copy(update={"ticker": "ZZZQX"})
    v = await verify_signal(sig, eng.quotes, eng.settings, grounding={"passed": True})
    assert not v["passed"] and v["park"] is True
    tr = next(c for c in v["checks"] if c["name"] == "ticker_resolves")
    assert not tr["passed"] and not tr["fatal"] and "parked" in tr["detail"]


async def test_analyst_positions_tool(app_client):
    # the analyst can see OUR book: real portfolio positions show up compactly;
    # shadow-book fills are excluded (they are the source's ledger, not ours)
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    from zargar.techniques.tip.analyst import _run_tool
    empty = await _run_tool(eng, "get_positions", {})
    assert "no open positions" in (empty.get("note") or "")
    pf = next(p for p in eng.positions.portfolios() if not p.get("book"))
    await eng.positions.apply_fill(pf["id"], "AAPL", "STK", "BUY", 10, 230.0, 0.0)
    got = await _run_tool(eng, "get_positions", {"symbol": "AAPL"})
    [row] = got["positions"]
    assert row["symbol"] == "AAPL" and row["qty"] == 10 and row["kind"] == pf["kind"]


async def test_analyst_quote_tool_falls_back_to_history(app_client, monkeypatch):
    # a cold symbol on a closed market must not blind the analyst (run d7aedd08:
    # SKIP purely for want of a print) — get_quote serves the last session's
    # close from history, marked stale
    client, eng = app_client
    from zargar.techniques.tip.analyst import _run_tool
    import zargar.marketstructure.history as hist

    class _B:
        close = 123.45

    async def fake_recent(sym, tf, sessions=2):
        return [_B()]

    monkeypatch.setattr(hist, "fetch_recent", fake_recent)

    async def no_ensure(sym):        # the sim feed would happily invent a quote
        return None

    monkeypatch.setattr(eng, "ensure_symbol", no_ensure)
    out = await _run_tool(eng, "get_quote", {"symbol": "ZZZQX"})
    assert out["last"] == 123.45 and out["stale"] is True
    assert "not" in out["note"] or "do not" in out["note"]


async def test_analyst_failure_never_blocks(app_client):
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    await eng.settings.set("verification.max_price_deviation_pct", 10.0)

    class Boom:
        def __init__(self):
            self.messages = self

        async def create(self, **kw):
            raise RuntimeError("api down")

    eng.signals_service._analyst_client = Boom()
    out = await run_pipeline(eng, canned_extraction())
    sig = out[0]["signal"]
    assert sig["status"] == "verified"                # pipeline unaffected
    assert "analyst" not in (sig["extraction"] or {})


async def test_discord_process_result_roundtrip(app_client):
    # "▶ tip" outcomes are reported back and polled by the UI — a message that
    # extracts as no tip must not look like silence (found live 2026-08-28)
    client, eng = app_client
    r = await client.post("/api/tip/discord/process-last", json={"channelId": "42"})
    assert r.status_code == 200
    assert (await client.get("/api/tip/discord/process-pending")).json() == {"channelIds": ["42"]}
    r = await client.post("/api/tip/discord/process-result", json={
        "channelId": "42", "ok": True,
        "note": "the message did not extract as a trade tip",
        "author": "me", "text": "hello", "signals": []})
    assert r.status_code == 200
    out = (await client.get("/api/tip/discord/process-result",
                            params={"channelId": "42"})).json()
    assert out["result"]["note"].startswith("the message did not")
    assert out["result"]["author"] == "me"
    # re-queueing clears the stale result so the UI never shows the previous outcome
    await client.post("/api/tip/discord/process-last", json={"channelId": "42"})
    out = (await client.get("/api/tip/discord/process-result",
                            params={"channelId": "42"})).json()
    assert out["result"] is None


async def test_discord_catalog_and_watch(app_client):
    # the gateway reports a catalog; the UI reads it and sets the allowlist
    client, eng = app_client
    cat = {"user": {"id": "1", "username": "me"},
           "dms": [{"channelId": "10", "name": "OWLSbot", "isBot": True}],
           "guilds": [{"guildId": "5", "guildName": "OWLS",
                       "channels": [{"channelId": "600", "name": "jon-and-kian"}]}]}
    r = await client.post("/api/tip/discord/catalog", json=cat)
    assert r.status_code == 200
    got = (await client.get("/api/tip/discord/catalog")).json()
    assert got["guilds"][0]["channels"][0]["name"] == "jon-and-kian"
    assert got["at"]                                   # stamped on report

    # empty watchlist by default (allowlist)
    assert (await client.get("/api/tip/discord/watch")).json()["watch"] == []
    # enable one channel as a source
    r = await client.put("/api/tip/discord/watch", json={"watch": [
        {"channelId": "600", "kind": "channel", "sourceName": "jon-and-kian",
         "label": "#jon-and-kian", "enabled": True}]})
    saved = r.json()["watch"]
    assert saved[0]["channelId"] == "600" and saved[0]["botsOnly"] is True  # channel default
    assert (await client.get("/api/tip/discord/watch")).json()["watch"][0]["sourceName"] == "jon-and-kian"


async def test_discord_peek_roundtrip(app_client):
    # UI queues a peek; gateway takes it, posts the last message; UI reads it
    client, eng = app_client
    assert (await client.post("/api/tip/discord/peek", json={"channelId": "600"})).status_code == 200
    pending = (await client.get("/api/tip/discord/peek-pending")).json()["channelIds"]
    assert pending == ["600"]
    assert (await client.get("/api/tip/discord/peek-pending")).json()["channelIds"] == []  # taken once
    await client.post("/api/tip/discord/peek-result", json={
        "channelId": "600", "text": "OPEN: NTR 82.5C", "author": "Jon [bot]",
        "messageAt": "2026-08-28T13:25:00Z"})
    res = (await client.get("/api/tip/discord/peek?channelId=600")).json()["result"]
    assert res["text"] == "OPEN: NTR 82.5C" and res["author"] == "Jon [bot]" and res["at"]


async def test_proposal_reject_and_expiry(app_client):
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    await eng.settings.set("verification.max_price_deviation_pct", 10.0)
    # this test deliberately ingests the same tip twice — opt out of dedupe
    await eng.settings.set("techniques.tip.dedupe_window_hours", 0)
    out = await run_pipeline(eng, canned_extraction())
    proposal = out[0]["proposal"]
    r = await client.post(f"/api/proposals/{proposal['id']}/reject")
    assert r.json()["status"] == "rejected"

    # expiry path — off-hours proposals now expire relative to the NEXT open
    # (ARM-PLAN P1), so force this one due instead of relying on a 0-min TTL
    out2 = await run_pipeline(eng, canned_extraction())
    p2 = out2[0]["proposal"]
    assert p2 is not None
    from zargar.models import Proposal as _P
    async with eng.sf() as session:
        rowp = await session.get(_P, p2["id"])
        rowp.expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
        await session.commit()
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


async def test_duplicate_tip_attaches_not_reproposes(app_client):
    """v2 dedupe: the same tip seen twice bumps seen_count on the original —
    no second proposal, no second shadow fill, and the scorecard counts it."""
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    await eng.settings.set("verification.max_price_deviation_pct", 10.0)
    out = await run_pipeline(eng, canned_extraction())
    assert out[0]["proposal"] is not None
    out2 = await run_pipeline(eng, canned_extraction())
    assert out2[0].get("duplicateOf") == out[0]["signal"]["id"]
    assert out2[0]["proposal"] is None and out2[0]["shadowOrder"] is None
    assert out2[0]["signal"]["seenCount"] == 2

    cards = (await client.get("/api/signals/sources")).json()
    card = next(c for c in cards if c["source"] == "TestLetter")
    assert card["signals"] == 1 and card["seenAgain"] == 1
    assert card["policy"]["entry"] == "level_touch"
    assert card["barCleared"] is False   # one tip is nowhere near the bar


def _spread_cboe(exp: str):
    """A CBOE mock serving one AAPL expiry with the 240/250 calls."""
    import httpx as _hx

    def _row(sym, bid, ask):
        return {"option": sym, "bid": bid, "ask": ask, "last_trade_price": (bid + ask) / 2,
                "volume": 500, "open_interest": 2000, "delta": 0.5, "gamma": 0.05,
                "theta": -0.03, "vega": 0.1, "iv": 0.2}

    d = dt.date.fromisoformat(exp)
    occ240 = f"AAPL{d:%y%m%d}C{240000:08d}"
    occ250 = f"AAPL{d:%y%m%d}C{250000:08d}"
    payload = {"data": {"current_price": 232.0, "close": 231.5, "prev_day_close": 231.0,
                        "iv30": 0.22,
                        "options": [_row(occ240, 4.4, 4.6), _row(occ250, 1.4, 1.6)]}}

    def handler(request: _hx.Request) -> _hx.Response:
        return _hx.Response(200, json=payload)
    from zargar.options.chain import CboeClient
    return CboeClient(_hx.AsyncClient(transport=_hx.MockTransport(handler))), occ240, occ250


async def test_spread_tip_proposes_and_opens_defined_risk(app_client):
    # ARM-PLAN P5 end-to-end: a stated 340/360-style call spread proposes as ONE
    # unit; approval opens it leg-sequenced (long fills FIRST, short leg covered)
    import asyncio as _aio

    from zargar.domain import Quote
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    await eng.settings.set("verification.max_price_deviation_pct", 10.0)
    # the long leg alone is ~$1.4k of premium — align the risk caps like a real
    # config would have to (the preflight warning covers the mismatch case)
    await eng.settings.set("risk.max_position_notional", 5000.0)
    await eng.settings.set("risk.max_option_premium_pct", 25.0)
    await eng.settings.set("risk.max_option_premium_notional", 5000.0)
    await eng.settings.set("risk.max_position_pct", 30.0)
    exp = (dt.date.today() + dt.timedelta(days=17)).isoformat()
    fake, occ240, occ250 = _spread_cboe(exp)
    eng.options.use_client(fake)

    tip = canned_extraction()
    tip.signals[0].legs = [{"action": "buy", "type": "call", "strike": 240.0},
                           {"action": "sell", "type": "call", "strike": 250.0}]
    tip.signals[0].expiry = exp

    # keep quotes flowing for both legs so the sequenced fills land
    stop = False

    async def pump():
        while not stop:
            eng.quotes.on_quote(Quote(symbol=occ240, bid=4.4, ask=4.6, last=4.5,
                                      bid_size=500, ask_size=500, volume=100))
            eng.quotes.on_quote(Quote(symbol=occ250, bid=1.4, ask=1.6, last=1.5,
                                      bid_size=500, ask_size=500, volume=100))
            await _aio.sleep(0.1)
    pump_task = _aio.create_task(pump())
    try:
        out = await run_pipeline(eng, tip)
        p = out[0]["proposal"]
        assert p is not None and p["secType"] == "SPREAD"
        v = p["context"]["vehicle"]
        assert v["kind"] == "spread" and len(v["legs"]) == 2
        assert abs(p["limitPrice"] - 3.2) < 0.01              # buy ask 4.6 - sell bid 1.4
        assert "defined-risk" in p["context"]["explain"]
        # the shadow book expressed the same spread (one managed position)
        expr = out[0]["signal"]["extraction"]["shadowExpression"]
        assert expr["vehicle"] == "spread", expr.get("fallback")

        r = await client.post(f"/api/proposals/{p['id']}/approve", json={})
        assert r.status_code == 200
        res = r.json()
        assert res["proposal"]["status"] == "executed", res["proposal"]

        async def adopted():
            for pos in eng.position_manager.positions():
                if (pos.get("technique") == "tip" and pos.get("portfolioId") == p["portfolioId"]
                        and len(pos.get("legs", [])) == 2):
                    return pos
            return None
        pos = await wait_for(adopted, timeout=20)
    finally:
        stop = True
        await pump_task
    legs = {l["symbol"]: l["qty"] for l in pos["legs"]}
    assert legs[occ240] > 0 and legs[occ250] < 0             # long 240C, short 250C
    assert pos["policy"]["stop"]["kind"] == "none"
    assert "defined-risk" in pos["policy"]["stop"]["guard"]


async def test_lone_short_option_leg_is_still_naked(app_client):
    # the defined-risk exception NEVER lets a lone short leg through: without
    # the covering long position, a spread-tagged SELL is rejected as naked
    from zargar.orders import OrderIntent
    client, eng = app_client
    await wait_quote(eng, "AAPL")
    pid = next(p for p in eng.positions.portfolios() if p["kind"] == "sim")["id"]
    exp = (dt.date.today() + dt.timedelta(days=17)).isoformat()
    d = dt.date.fromisoformat(exp)
    occ = f"AAPL{d:%y%m%d}C{250000:08d}"
    from zargar.domain import Quote
    eng.quotes.on_quote(Quote(symbol=occ, bid=1.4, ask=1.6, last=1.5,
                              bid_size=500, ask_size=500, volume=100))
    out = await eng.orders.place(OrderIntent(
        portfolio_id=pid, symbol=occ, sec_type="OPT", side="SELL", qty=1,
        order_type="LMT", limit_price=1.4, source="technique", technique_id="tip",
        tags=["spread:deadbeef"]))
    assert out["status"] == "REJECTED_RISK"
    assert "naked short options" in (out.get("rejectReason") or "")
