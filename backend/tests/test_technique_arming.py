"""Armed plans with execution: accounts, modes, the auto lifecycle (entry ->
fills -> trims -> stop / flatten), pause/resume/disarm/stop-all, audit trail,
persistence + restore, and the live-account gate. Sim venue only; fills are
driven by publishing quotes on the bus (the sim executor fills against them)."""
from __future__ import annotations

import asyncio
import datetime as dt
from types import SimpleNamespace

import httpx
import pytest

from zargar import bus as topics
from zargar.api.app import create_app
from zargar.domain import Bar, Quote
from zargar.engine import Engine
from zargar.technique import service as service_mod
from zargar.technique.arming import ArmConfig
from zargar.technique.rulebook import ET, session_bounds, session_date
from zargar.technique.service import attach_technique_layer

from .conftest import make_test_config, wait_for
from .test_technique_walkforward import by_day, continuous_market, plan_at_close, weekdays

MIN = 60_000


def _ms(day: dt.date, h: int, m: int) -> int:
    return int(dt.datetime(day.year, day.month, day.day, h, m, tzinfo=ET).timestamp() * 1000)


@pytest.fixture
async def rig(fresh_db, monkeypatch):
    config = make_test_config(anthropic_api_key="")        # no model: plans are deterministic, critic off
    eng = Engine(config)
    await eng.start()
    await attach_technique_layer(eng)
    await eng.settings.set("technique.options.enabled", False, journal=False)
    await eng.settings.set("risk.max_position_notional", 1_000_000.0, journal=False)
    await eng.settings.set("risk.max_position_pct", 100.0, journal=False)
    await eng.settings.set("risk.stale_quote_seconds", 600, journal=False)
    app = create_app(config, eng)
    transport = httpx.ASGITransport(app=app)
    # pin the sim price for TEST (seed_price is hash-based) and build the market around it
    import zargar.brokers.sim as simmod
    monkeypatch.setitem(simmod.KNOWN_PRICES, "TEST", 100.0)
    await eng.ensure_symbol("TEST")
    await wait_for(lambda: eng.quotes.get("TEST") is not None and eng.quotes.get("TEST").last > 0, timeout=5)
    px = float(eng.quotes.get("TEST").last)
    days = weekdays(6)
    market = continuous_market(days, lo=100.0, hi=104.0)     # same geometry as the walk-forward tests
    sessions = by_day(market["1m"])

    async def fake_gather(req_):
        out = {}
        for tf in req_.timeframes:
            bars = market.get(tf) or []
            out[tf] = [b for b in bars if req_.as_of_ms is None or b.ts <= req_.as_of_ms]
        return {k: v for k, v in out.items() if v}, ["synthetic bars"]

    async def fake_session(symbol, tf, date, **kw):
        return [b for b in (market.get(tf) or []) if session_date(b.ts) == date]

    monkeypatch.setattr(service_mod, "gather_bars", fake_gather)
    monkeypatch.setattr(service_mod, "fetch_session", fake_session)
    sim = next(p for p in eng.positions.portfolios() if p["kind"] == "sim")
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield SimpleNamespace(client=client, eng=eng, svc=eng.technique, days=days, market=market,
                              sessions=sessions, sim=sim, px=px)
    await eng.technique.stop()
    await eng.stop()


async def _plan_run(rig):
    close_ts = session_bounds(rig.days[3].isoformat())[1]
    run = await rig.svc.analyze("TEST", as_of_ms=close_ts, wait=True)
    assert run["status"] == "done" and run["mode"] == "plan", run.get("error")
    return run


async def _quote(rig, price: float, ts_ms: int | None = None):
    """Move the market to `price`: pin the sim feed there (it keeps ticking TEST on
    its own) and publish a quote so the risk gate sees a fresh price and the sim
    executor fills against it."""
    st = getattr(rig.eng.feed, "_symbols", {}).get("TEST")
    if st is not None:
        st.price = price
        st.sigma_per_min = 0.0
        st.drift_per_min = 0.0
        st.spread_bps = 1.0
    q = Quote(symbol="TEST", bid=round(price - 0.01, 2), ask=round(price + 0.01, 2), last=price,
              bid_size=100000, ask_size=100000, volume=1_000_000)
    q.ts = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    rig.eng.bus.publish(topics.QUOTES, q)
    await asyncio.sleep(0.15)


async def _feed_until(rig, run_id, bars, pred, *, quote_fn=None):
    """Feed bars until pred(snapshot) is true; returns (snapshot, next index)."""
    snap = None
    for i, b in enumerate(bars):
        if quote_fn:
            await quote_fn(b)
        snap = await rig.svc.armer.on_bar(run_id, b)
        if snap and pred(snap):
            return snap, i + 1
    return snap, len(bars)


# --- config / gates ---------------------------------------------------------------------------------

async def test_arm_options_and_config_validation(rig):
    opts = (await rig.client.get("/api/technique/armed/options")).json()
    assert any(p["kind"] == "sim" for p in opts["portfolios"]) and opts["defaults"]["mode"] == "proposal"
    assert opts["tradingMode"] == "practice" and opts["allowLiveAuto"] is False
    run = await _plan_run(rig)
    # bad mode
    r = await rig.client.post(f"/api/technique/runs/{run['id']}/arm", json={"mode": "yolo", "portfolioId": rig.sim["id"]})
    assert r.status_code == 400
    # unknown account
    r = await rig.client.post(f"/api/technique/runs/{run['id']}/arm", json={"mode": "auto", "portfolioId": "nope"})
    assert r.status_code == 400 and "account" in r.json()["detail"]
    # live auto is gated three ways
    live = [p for p in rig.eng.positions.portfolios() if p["kind"] in ("live", "paper")]
    if live:
        r = await rig.client.post(f"/api/technique/runs/{run['id']}/arm",
                                  json={"mode": "auto", "portfolioId": live[0]["id"], "allowLive": True})
        assert r.status_code == 400 and "allow_live_auto" in r.json()["detail"]
    # risk % outside R1 cap
    r = await rig.client.post(f"/api/technique/runs/{run['id']}/arm",
                              json={"mode": "auto", "instrument": "shares", "portfolioId": rig.sim["id"], "riskPct": 9})
    assert r.status_code == 400 and "riskPct" in r.json()["detail"]
    # a full (non-plan) run cannot be armed
    r = await rig.client.post("/api/technique/runs/does-not-exist/arm", json={})
    assert r.status_code == 404


# --- auto lifecycle --------------------------------------------------------------------------------------

async def test_auto_mode_full_lifecycle_entry_trims_stop(rig):
    run = await _plan_run(rig)
    armed = (await rig.client.post(f"/api/technique/runs/{run['id']}/arm",
                                   json={"mode": "auto", "instrument": "shares", "portfolioId": rig.sim["id"], "riskPct": 1.0,
                                         "maxQty": 50, "slippagePct": 1.0})).json()
    assert armed["status"] == "armed" and armed["config"]["mode"] == "auto" and armed["portfolio"]["kind"] == "sim"
    assert armed["summary"].startswith("watching")
    plan_for = armed["planFor"]
    bars = rig.sessions[plan_for]
    assert any(t["kind"] == "bounce" for t in armed["triggers"]), armed["triggers"]
    b1 = next(t for t in armed["triggers"] if t["kind"] == "bounce")
    entry, stop, targets = b1["entry"], b1["stop"], b1["targets"]
    # keep a fresh quote near the price so RiskGate's collar/staleness pass and the sim can fill
    async def q(bar):
        await _quote(rig, bar.close)
    snap, i = await _feed_until(rig, run["id"], bars, lambda s: any(t["kind"] == "bounce" for t in s["trades"]), quote_fn=q)
    assert snap and snap["trades"], snap and snap["events"][-5:]
    tr = next(t for t in snap["trades"] if t["kind"] == "bounce")
    assert tr["status"] in ("working", "open"), (tr["status"], tr["reason"], tr["errors"], snap["events"][-6:])
    assert tr["entryOrderId"] and tr["qty"] >= 1 and tr["limitPrice"] >= entry
    # entry fills once a quote prints at/below the limit
    await _quote(rig, entry)
    def _bt():
        d = rig.svc.armer.detail(run["id"]) or {}
        return next((t for t in d.get("trades", []) if t["kind"] == "bounce"), {})
    await wait_for(lambda: _bt().get("status") == "open", timeout=5)
    d = rig.svc.armer.detail(run["id"])
    tr = _bt()
    assert tr["filledQty"] == tr["qty"] and tr["remaining"] == tr["qty"] and tr["avgFill"]
    assert d["openPositions"] == 1 and "in trade" in d["summary"]
    orders = await rig.eng.orders.list_orders(rig.sim["id"])
    assert any(o["source"] == "technique" and o["side"] == "BUY" and o["status"] == "FILLED" for o in orders)
    # first target: a bar whose high reaches tp1 -> 30% trim sent as MKT, filled by the next quote
    tp1_bar = Bar(symbol="TEST", tf="1m", ts=bars[i].ts, open=entry, high=targets[0] + 0.05, low=entry - 0.01,
                  close=targets[0], volume=1000)
    await _quote(rig, targets[0])
    snap = await rig.svc.armer.on_bar(run["id"], tp1_bar)
    await _quote(rig, targets[0])
    await wait_for(lambda: _bt().get("exits") and _bt()["exits"][0].get("filledQty"), timeout=5)
    tr = _bt()
    assert tr["exits"][0]["kind"] == "tp1" and tr["trimsDone"] == 1
    assert tr["remaining"] == tr["filledQty"] - tr["exits"][0]["filledQty"] and tr["realizedPnl"] > 0
    # stop hit -> remaining sold at market
    stop_bar = Bar(symbol="TEST", tf="1m", ts=bars[i + 1].ts, open=targets[0], high=targets[0], low=stop - 0.05,
                   close=stop - 0.02, volume=1000)
    await _quote(rig, stop - 0.02)
    await rig.svc.armer.on_bar(run["id"], stop_bar)
    await _quote(rig, stop - 0.02)
    await wait_for(lambda: _bt().get("status") == "closed", timeout=5)
    tr = _bt()
    assert [e["kind"] for e in tr["exits"]] == ["tp1", "stop"] and tr["remaining"] == 0 and tr["closedTs"]
    # audit trail: journal carries the whole story, incl. the orders it raised
    audit = (await rig.client.get(f"/api/technique/armed/{run['id']}/audit")).json()
    types = [e["type"] for e in audit]
    for t in ("TechniquePlanArmed", "TechniquePlanTriggerFired", "TechniquePlanOrderIntent", "TechniquePlanOrderResult",
              "TechniquePlanPositionOpened", "TechniquePlanExit", "TechniquePlanPositionClosed",
              "OrderIntentCreated", "RiskCheckPassed", "OrderFilled"):
        assert t in types, t
    # persisted projection
    hist = (await rig.client.get("/api/technique/armed/history")).json()
    row = next(h for h in hist if h["runId"] == run["id"])
    assert row["mode"] == "auto" and row["portfolioId"] == rig.sim["id"] and row["state"]["trades"][0]["status"] == "closed"
    # the run's setups carry the fired trigger
    full = (await rig.client.get(f"/api/technique/runs/{run['id']}")).json()
    assert full["setups"] and full["setups"][0]["valid"] is True


async def test_auto_mode_derives_a_loss_halt(rig):
    """Auto mode with no loss limit set gets one derived from equity x risk%."""
    run = await _plan_run(rig)
    armed = (await rig.client.post(f"/api/technique/runs/{run['id']}/arm",
                                   json={"mode": "auto", "instrument": "shares", "portfolioId": rig.sim["id"],
                                         "riskPct": 1.0, "maxQty": 10})).json()
    assert armed["config"]["dailyLossLimit"] > 0, armed["config"]
    await rig.svc.armer.disarm(run["id"], reason="test")
    # proposal mode does not silently add one
    run2 = await _plan_run(rig)
    r2 = await rig.client.post(f"/api/technique/runs/{run2['id']}/arm",
                               json={"mode": "proposal", "instrument": "shares", "portfolioId": rig.sim["id"]})
    assert r2.status_code == 200, r2.text
    assert r2.json()["config"]["dailyLossLimit"] == 0


async def test_quote_stop_watch_exits_between_bars(rig):
    """A crash through the stop mid-minute is caught by the ~2s quote watch and
    sold reduce-only at market — no waiting for the bar close. One breach poll is
    not enough (bad tick); two consecutive are."""
    await rig.eng.settings.set("technique.arm.quote_exit_seconds", 0.05, journal=False)
    run = await _plan_run(rig)
    armed = (await rig.client.post(f"/api/technique/runs/{run['id']}/arm",
                                   json={"mode": "auto", "instrument": "shares", "portfolioId": rig.sim["id"],
                                         "riskPct": 1.0, "maxQty": 50, "slippagePct": 1.0})).json()
    bars = rig.sessions[armed["planFor"]]
    b1 = next(t for t in armed["triggers"] if t["kind"] == "bounce")

    async def q(bar):
        await _quote(rig, bar.close)
    snap, i = await _feed_until(rig, run["id"], bars, lambda s: any(t["kind"] == "bounce" for t in s["trades"]), quote_fn=q)
    await _quote(rig, b1["entry"])

    def _bt():
        d = rig.svc.armer.detail(run["id"]) or {}
        return next((t for t in d.get("trades", []) if t["kind"] == "bounce"), {})
    await wait_for(lambda: _bt().get("status") == "open", timeout=5)
    risk = b1["entry"] - b1["stop"]
    crash = round(b1["stop"] - 0.6 * risk, 2)          # decisively through (excess_r = 0.25)
    # no closed bar is fed — the quote watch alone must react
    await _quote(rig, crash)
    await wait_for(lambda: (_bt().get("exits") or [{}])[0].get("kind") == "stop", timeout=5)
    await _quote(rig, crash)                            # lets the sim fill the market sell
    await wait_for(lambda: _bt().get("status") == "closed", timeout=5)
    tr = _bt()
    assert [e["kind"] for e in tr["exits"]] == ["stop"] and tr["remaining"] == 0
    audit = (await rig.client.get(f"/api/technique/armed/{run['id']}/audit")).json()
    exit_ev = next(e for e in audit if e["type"] == "TechniquePlanExit")
    assert "intra-minute quote breach" in exit_ev["payload"]["reason"]


async def test_quote_at_the_stop_is_left_to_the_bar_close(rig):
    """At-or-slightly-past the stop is the bar-close logic's call (mental-stop
    discipline) — the quote watch must NOT fire there."""
    await rig.eng.settings.set("technique.arm.quote_exit_seconds", 0.05, journal=False)
    run = await _plan_run(rig)
    armed = (await rig.client.post(f"/api/technique/runs/{run['id']}/arm",
                                   json={"mode": "auto", "instrument": "shares", "portfolioId": rig.sim["id"],
                                         "riskPct": 1.0, "maxQty": 50, "slippagePct": 1.0})).json()
    bars = rig.sessions[armed["planFor"]]
    b1 = next(t for t in armed["triggers"] if t["kind"] == "bounce")

    async def q(bar):
        await _quote(rig, bar.close)
    await _feed_until(rig, run["id"], bars, lambda s: any(t["kind"] == "bounce" for t in s["trades"]), quote_fn=q)
    await _quote(rig, b1["entry"])

    def _bt():
        d = rig.svc.armer.detail(run["id"]) or {}
        return next((t for t in d.get("trades", []) if t["kind"] == "bounce"), {})
    await wait_for(lambda: _bt().get("status") == "open", timeout=5)
    await _quote(rig, round(b1["stop"] - 0.01, 2))      # at the stop, not decisively through
    await asyncio.sleep(0.5)                            # several watch cycles
    assert _bt().get("status") == "open" and not _bt().get("exits")


async def test_auto_mode_flattens_before_close_and_disarm_flatten(rig):
    run = await _plan_run(rig)
    armed = (await rig.client.post(f"/api/technique/runs/{run['id']}/arm",
                                   json={"mode": "auto", "instrument": "shares", "portfolioId": rig.sim["id"], "qty": 5, "slippagePct": 1.0,
                                         "flattenMinutesBeforeClose": 5})).json()
    plan_for = armed["planFor"]
    bars = rig.sessions[plan_for]
    b1 = next(t for t in armed["triggers"] if t["kind"] == "bounce")
    async def q(bar):
        await _quote(rig, bar.close)
    snap, i = await _feed_until(rig, run["id"], bars, lambda s: any(t["kind"] == "bounce" for t in s["trades"]), quote_fn=q)
    tr0 = next(t for t in snap["trades"] if t["kind"] == "bounce")
    assert tr0["status"] in ("working", "open"), (tr0["status"], tr0["reason"], tr0["errors"])
    await _quote(rig, b1["entry"])
    def _bt():
        d = rig.svc.armer.detail(run["id"]) or {}
        return next((t for t in d.get("trades", []) if t["kind"] == "bounce"), {})
    await wait_for(lambda: _bt().get("status") == "open", timeout=5)
    assert _bt()["qty"] == 5      # fixed size
    # a bar inside the flatten window -> everything sold
    day = dt.datetime.fromtimestamp(bars[0].ts / 1000, ET).date()
    flat_bar = Bar(symbol="TEST", tf="1m", ts=_ms(day, 15, 56), open=b1["entry"], high=b1["entry"] + 0.1,
                   low=b1["entry"] - 0.05, close=b1["entry"] + 0.05, volume=1000)
    await _quote(rig, b1["entry"] + 0.05)
    await rig.svc.armer.on_bar(run["id"], flat_bar)
    await _quote(rig, b1["entry"] + 0.05)
    await wait_for(lambda: _bt().get("status") == "closed", timeout=5)
    tr = _bt()
    assert tr["exits"][-1]["kind"] == "flatten"
    # session end -> expired + disarmed, persisted as such
    await rig.svc.armer.on_bar(run["id"], Bar(symbol="TEST", tf="1m", ts=_ms(day, 15, 59), open=1, high=1, low=1, close=1, volume=1))
    assert (await rig.client.get("/api/technique/armed")).json() == []
    hist = (await rig.client.get("/api/technique/armed/history")).json()
    assert next(h for h in hist if h["runId"] == run["id"])["status"] in ("disarmed", "expired")


async def test_pause_resume_halt_and_stop_all(rig):
    run = await _plan_run(rig)
    await rig.client.post(f"/api/technique/runs/{run['id']}/arm", json={"mode": "alert", "portfolioId": rig.sim["id"]})
    plan_for = (await rig.client.get("/api/technique/armed")).json()[0]["planFor"]
    bars = rig.sessions[plan_for]
    # paused: the touch is logged but nothing fires
    p = (await rig.client.post(f"/api/technique/armed/{run['id']}/pause")).json()
    assert p["status"] == "paused"
    snap, i = await _feed_until(rig, run["id"], bars, lambda s: any(e["event"] == "paused_skip" for e in s["events"]))
    assert snap and not snap["trades"]
    # resume; kill switch engaged -> still no fire, journaled
    await rig.client.post(f"/api/technique/armed/{run['id']}/resume")
    await rig.eng.engage_halt("test")
    snap, j = await _feed_until(rig, run["id"], bars[i:], lambda s: any(e["event"] == "halt_skip" for e in s["events"]))
    assert snap and not snap["trades"]
    await rig.eng.release_halt()
    # now it fires in alert mode: setup only, no order
    snap, _ = await _feed_until(rig, run["id"], bars[i + j:], lambda s: bool(s["trades"]))
    assert snap["trades"][0]["status"] == "alert"
    assert not await rig.eng.orders.list_orders(rig.sim["id"])
    events = (await rig.client.get("/api/events", params={"aggregate_id": run["id"]})).json()
    types = [e["type"] for e in events]
    assert "TechniquePlanPaused" in types and "TechniquePlanResumed" in types and "TechniquePlanTriggerFired" in types
    assert any(e["payload"].get("event") == "halt" for e in events if e["type"] == "TechniquePlanTriggerSkipped")
    # stop all
    run2 = await _plan_run(rig)
    await rig.client.post(f"/api/technique/runs/{run2['id']}/arm", json={"mode": "alert", "portfolioId": rig.sim["id"]})
    assert len((await rig.client.get("/api/technique/armed")).json()) == 2
    r = (await rig.client.post("/api/technique/armed/stop-all")).json()
    assert r["disarmed"] == 2 and (await rig.client.get("/api/technique/armed")).json() == []


async def test_proposal_mode_creates_practice_proposal(rig):
    run = await _plan_run(rig)
    await rig.client.post(f"/api/technique/runs/{run['id']}/arm",
                          json={"mode": "proposal", "instrument": "shares", "portfolioId": rig.sim["id"], "riskPct": 1.0, "maxQty": 20})
    plan_for = (await rig.client.get("/api/technique/armed")).json()[0]["planFor"]
    snap, _ = await _feed_until(rig, run["id"], rig.sessions[plan_for], lambda s: bool(s["trades"]))
    tr = snap["trades"][0]
    assert tr["status"] == "proposal" and tr["proposalId"]
    from zargar.models import Proposal
    async with rig.eng.sf() as session:
        p = await session.get(Proposal, tr["proposalId"])
    assert p is not None and p.portfolio_id == rig.sim["id"] and p.qty <= 20 and p.status == "pending"
    assert p.context["technique"]["runId"] == run["id"]


async def test_restore_after_restart(rig):
    """Today's armed/paused rows are re-armed on start; stale days are expired."""
    run = await _plan_run(rig)
    await rig.client.post(f"/api/technique/runs/{run['id']}/arm", json={"mode": "alert", "portfolioId": rig.sim["id"]})
    # simulate a restart: forget in-memory state, restore from the table
    rig.svc.armer._armed.clear()
    n = await rig.svc.armer.restore()
    # the plan is for a past session (synthetic market), so it is expired rather than re-armed
    assert n == 0
    hist = (await rig.client.get("/api/technique/armed/history")).json()
    assert next(h for h in hist if h["runId"] == run["id"])["status"] == "expired"
    # a row for "today" is restored
    from zargar.models import TechniqueArmed
    today = session_date(int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000))
    async with rig.eng.sf() as session:
        row = await session.get(TechniqueArmed, run["id"])
        row.status = "paused"
        row.plan_for = today
        await session.commit()
    n = await rig.svc.armer.restore()
    assert n == 1 and rig.svc.armer.get(run["id"]).status == "paused"
    await rig.svc.armer.disarm(run["id"])


    # ...and a plan armed ahead of time for the NEXT session (weekend arming) survives too
    rig.svc.armer._armed.clear()
    async with rig.eng.sf() as session:
        row = await session.get(TechniqueArmed, run["id"])
        row.status = "armed"
        row.plan_for = (dt.date.fromisoformat(today) + dt.timedelta(days=3)).isoformat()
        await session.commit()
    assert await rig.svc.armer.restore() == 1
    assert rig.svc.armer.get(run["id"]).status == "armed"


async def test_arm_config_roundtrip():
    c = ArmConfig.from_dict({"portfolioId": "p", "mode": "auto", "riskPct": 0.75, "maxQty": 10, "allowLive": True})
    assert c.to_dict()["riskPct"] == 0.75 and c.allow_live and c.max_qty == 10
    assert ArmConfig.from_dict(c.to_dict()) == c


# --- options instrument (the book's expression) ------------------------------------------------------

OCC = "TEST260828C00101000"


async def _fake_pick(rig, monkeypatch, *, ask=2.50, bid=2.40):
    await rig.eng.settings.set("technique.options.enabled", True, journal=False)   # the pick is faked, no chain call
    async def pick(symbol, direction="long", *, spot=None, **kw):
        return {"available": True, "symbol": OCC, "display": "TEST 28AUG26 101C", "underlying": "TEST", "expiry": "2026-08-28",
                "strike": 101.0, "optionType": "call", "bid": bid, "ask": ask, "mid": round((bid + ask) / 2, 2), "spreadPct": 4.0,
                "delta": 0.45, "theta": -0.08, "iv": 0.55, "dte": 5, "is0dte": False, "openInterest": 1200, "volume": 300,
                "warnings": [], "provider": "fake", "chainSize": 40}
    monkeypatch.setattr(rig.svc, "option_pick", pick)
    if getattr(rig.eng, "options", None) is not None:
        async def track(symbol):
            return None
        monkeypatch.setattr(rig.eng.options, "track", track)


async def _opt_quote(rig, bid: float, ask: float):
    q = Quote(symbol=OCC, bid=bid, ask=ask, last=round((bid + ask) / 2, 2), bid_size=500, ask_size=500, volume=1000)
    # the sim feed only ticks the underlying, so publish twice: once for the risk gate /
    # working order, once more after the sim executor's 120ms latency so the LMT can fill
    for _ in range(2):
        q.ts = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
        rig.eng.quotes.on_quote(q)      # cache (risk gate) + bus (sim executor fills)
        await asyncio.sleep(0.2)


async def test_arm_options_lists_accounts_with_cash_and_options_capability(rig):
    opts = (await rig.client.get("/api/technique/armed/options")).json()
    sim = next(p for p in opts["portfolios"] if p["kind"] == "sim")
    assert sim["optionsOk"] is True and "cash" in sim and opts["defaults"]["instrument"] == "options"
    assert opts["defaults"]["contracts"] == 1 and opts["optionsProvider"]


async def test_auto_options_one_contract_lifecycle(rig, monkeypatch):
    await _fake_pick(rig, monkeypatch)
    await rig.eng.settings.set("risk.max_option_premium_notional", 100000.0, journal=False)
    run = await _plan_run(rig)
    armed = (await rig.client.post(f"/api/technique/runs/{run['id']}/arm",
                                   json={"mode": "auto", "instrument": "options", "contracts": 1,
                                         "portfolioId": rig.sim["id"], "singleContractExit": "tp2"})).json()
    assert armed["config"]["instrument"] == "options" and armed["config"]["contracts"] == 1
    plan_for = armed["planFor"]
    bars = rig.sessions[plan_for]
    b1 = next(t for t in armed["triggers"] if t["kind"] == "bounce")
    entry, stop, targets = b1["entry"], b1["stop"], b1["targets"]
    async def q(bar):
        await _quote(rig, bar.close)
        await _opt_quote(rig, 2.40, 2.50)
    snap, i = await _feed_until(rig, run["id"], bars, lambda s: any(t["kind"] == "bounce" for t in s["trades"]), quote_fn=q)
    tr = next(t for t in snap["trades"] if t["kind"] == "bounce")
    assert tr["status"] in ("working", "open"), (tr["status"], tr["reason"], tr["errors"], snap["events"][-6:])
    assert tr["instrument"] == "options" and tr["contract"]["symbol"] == OCC and tr["qty"] == 1 and tr["limitPrice"] == 2.5
    await _opt_quote(rig, 2.40, 2.50)          # ask <= limit -> fills
    def _bt():
        d = rig.svc.armer.detail(run["id"]) or {}
        return next((t for t in d.get("trades", []) if t["kind"] == "bounce"), {})
    await wait_for(lambda: _bt().get("status") == "open", timeout=5)
    tr = _bt()
    assert tr["filledQty"] == 1 and tr["premiumPaid"] == pytest.approx(250.0, abs=1) and tr["orderSymbol"] == OCC
    orders = await rig.eng.orders.list_orders(rig.sim["id"])
    assert any(o["secType"] == "OPT" and o["symbol"] == OCC and o["side"] == "BUY" and o["status"] == "FILLED" for o in orders)
    # TP1 on the underlying: a single contract does NOT trim (exit is at TP2)
    tp1_bar = Bar(symbol="TEST", tf="1m", ts=bars[i].ts, open=entry, high=targets[0] + 0.05, low=entry - 0.01, close=targets[0], volume=1000)
    await rig.svc.armer.on_bar(run["id"], tp1_bar)
    assert _bt()["exits"] == [] and _bt()["trimsDone"] == 1
    # TP2 on the underlying -> sell the contract at the bid (LMT), option now worth more
    await _opt_quote(rig, 4.10, 4.20)
    tp2_bar = Bar(symbol="TEST", tf="1m", ts=bars[i + 1].ts, open=targets[0], high=targets[1] + 0.05, low=targets[0], close=targets[1], volume=1000)
    await rig.svc.armer.on_bar(run["id"], tp2_bar)
    await _opt_quote(rig, 4.10, 4.20)
    await wait_for(lambda: _bt().get("status") == "closed", timeout=5)
    tr = _bt()
    assert [e["kind"] for e in tr["exits"]] == ["tp2"] and tr["remaining"] == 0
    assert tr["realizedPnl"] == pytest.approx((4.10 - 2.50) * 100, abs=2)       # premium move x 100
    audit = (await rig.client.get(f"/api/technique/armed/{run['id']}/audit")).json()
    intent = next(e for e in audit if e["type"] == "TechniquePlanOrderIntent")
    assert intent["payload"]["secType"] == "OPT" and intent["payload"]["contract"]["symbol"] == OCC


async def test_auto_options_without_a_contract_fails_cleanly(rig, monkeypatch):
    async def pick(symbol, direction="long", *, spot=None, **kw):
        return {"available": False, "error": "no call just OTM at 2026-08-28", "provider": "fake"}
    monkeypatch.setattr(rig.svc, "option_pick", pick)
    await rig.eng.settings.set("technique.options.enabled", True, journal=False)
    run = await _plan_run(rig)
    await rig.client.post(f"/api/technique/runs/{run['id']}/arm",
                          json={"mode": "auto", "instrument": "options", "contracts": 1, "portfolioId": rig.sim["id"]})
    plan_for = (await rig.client.get("/api/technique/armed")).json()[0]["planFor"]
    async def q(bar):
        await _quote(rig, bar.close)
    snap, _ = await _feed_until(rig, run["id"], rig.sessions[plan_for], lambda s: bool(s["trades"]), quote_fn=q)
    tr = snap["trades"][0]
    assert tr["status"] == "failed" and "no option contract" in tr["reason"] and any("no call just OTM" in e for e in tr["errors"])
    assert not await rig.eng.orders.list_orders(rig.sim["id"])


async def test_proposal_options_carries_the_contract(rig, monkeypatch):
    await _fake_pick(rig, monkeypatch)
    run = await _plan_run(rig)
    await rig.client.post(f"/api/technique/runs/{run['id']}/arm",
                          json={"mode": "proposal", "instrument": "options", "contracts": 2, "portfolioId": rig.sim["id"]})
    plan_for = (await rig.client.get("/api/technique/armed")).json()[0]["planFor"]
    snap, _ = await _feed_until(rig, run["id"], rig.sessions[plan_for], lambda s: bool(s["trades"]))
    tr = snap["trades"][0]
    assert tr["status"] == "proposal" and tr["proposalId"] and tr["contract"]["symbol"] == OCC
    from zargar.models import Proposal
    async with rig.eng.sf() as session:
        p = await session.get(Proposal, tr["proposalId"])
    assert p.sec_type == "OPT" and p.symbol == OCC and p.qty == 2 and p.limit_price == 2.5
    assert p.context["contract"]["strike"] == 101.0 and p.context["sizing"]["notional"] == 500.0


# --- safety: reduce-only exits, loss halt, restore, scorecard, pre-flight --------------------------

async def _open_a_share_trade(rig, run, *, risk_pct=1.0, max_qty=50, loss_limit=0.0, max_open=1):
    body = {"mode": "auto", "instrument": "shares", "portfolioId": rig.sim["id"], "riskPct": risk_pct,
            "maxQty": max_qty, "slippagePct": 1.0, "dailyLossLimit": loss_limit, "maxOpenTrades": max_open}
    armed = (await rig.client.post(f"/api/technique/runs/{run['id']}/arm", json=body)).json()
    bars = rig.sessions[armed["planFor"]]
    b1 = next(t for t in armed["triggers"] if t["kind"] == "bounce")
    async def q(bar):
        await _quote(rig, bar.close)
    snap, i = await _feed_until(rig, run["id"], bars, lambda s: any(t["kind"] == "bounce" for t in s["trades"]), quote_fn=q)
    await _quote(rig, b1["entry"])
    def _bt():
        d = rig.svc.armer.detail(run["id"]) or {}
        return next((t for t in d.get("trades", []) if t["kind"] == "bounce"), {})
    await wait_for(lambda: _bt().get("status") == "open", timeout=5)
    return armed, bars, b1, i, _bt


async def test_reduce_only_exits_pass_the_trading_mode_gate(rig):
    """practice mode blocks entries to real accounts but must NEVER block a
    reduce-only exit — a workspace switch cannot trap an open position."""
    from zargar.orders import OrderIntent
    live = next(p for p in rig.eng.positions.portfolios() if p["kind"] == "live")
    assert str(rig.eng.settings.get("trading.mode")) == "practice"
    buy = await rig.eng.orders.place(OrderIntent(portfolio_id=live["id"], symbol="TEST", sec_type="STK",
                                                 side="BUY", qty=1, order_type="MKT", source="manual"))
    assert "trading.mode=practice blocks" in (buy.get("rejectReason") or "")
    sell = await rig.eng.orders.place(OrderIntent(portfolio_id=live["id"], symbol="TEST", sec_type="STK",
                                                  side="SELL", qty=1, order_type="MKT", source="technique",
                                                  reduce_only=True))
    # it passes the mode gate; the only remaining objection is the missing venue
    assert "trading.mode" not in (sell.get("rejectReason") or ""), sell
    assert "no connected execution venue" in (sell.get("rejectReason") or ""), sell


async def test_exits_are_reduce_only_and_work_under_the_kill_switch(rig):
    run = await _plan_run(rig)
    armed, bars, b1, i, _bt = await _open_a_share_trade(rig, run)
    entry, stop = b1["entry"], b1["stop"]
    await rig.eng.engage_halt("panic")
    stop_bar = Bar(symbol="TEST", tf="1m", ts=bars[i].ts, open=entry, high=entry, low=stop - 0.05,
                   close=stop - 0.02, volume=1000)
    await _quote(rig, stop - 0.02)
    await rig.svc.armer.on_bar(run["id"], stop_bar)
    await _quote(rig, stop - 0.02)
    await wait_for(lambda: _bt().get("status") == "closed", timeout=5)
    tr = _bt()
    assert tr["exits"] and tr["exits"][-1]["kind"] == "stop" and tr["remaining"] == 0
    orders = await rig.eng.orders.list_orders(rig.sim["id"])
    sell = next(o for o in orders if o["side"] == "SELL")
    assert sell["status"] == "FILLED"
    await rig.eng.release_halt()


async def test_daily_loss_halt_flattens_and_stops_the_plan(rig):
    run = await _plan_run(rig)
    armed, bars, b1, i, _bt = await _open_a_share_trade(rig, run, loss_limit=0.01)
    entry, stop = b1["entry"], b1["stop"]
    stop_bar = Bar(symbol="TEST", tf="1m", ts=bars[i].ts, open=entry, high=entry, low=stop - 0.05,
                   close=stop - 0.02, volume=1000)
    await _quote(rig, stop - 0.02)
    await rig.svc.armer.on_bar(run["id"], stop_bar)
    await _quote(rig, stop - 0.02)
    # the open position marked at the quote already crosses the $0.01 limit, so the
    # halt fires on this very bar (unrealised counts now) — the plan flattens + stops
    await wait_for(lambda: (rig.svc.armer.armed()) == [], timeout=5)
    await _quote(rig, stop - 0.02)
    assert (await rig.client.get("/api/technique/armed")).json() == []
    events = (await rig.client.get("/api/events", params={"aggregate_id": run["id"]})).json()
    assert any(e["type"] == "TechniquePlanError" and e["payload"].get("stage") == "loss_halt" for e in events)


async def test_restore_reattaches_an_open_trade(rig):
    run = await _plan_run(rig)
    armed, bars, b1, i, _bt = await _open_a_share_trade(rig, run)
    from zargar.models import TechniqueArmed
    today = session_date(int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000))
    async with rig.eng.sf() as session:
        row = await session.get(TechniqueArmed, run["id"])
        row.plan_for = today
        await session.commit()
    rig.svc.armer._armed.clear()
    rig.svc.armer._order_index.clear()
    n = await rig.svc.armer.restore()
    assert n == 1
    d = rig.svc.armer.detail(run["id"])
    tr = next(t for t in d["trades"] if t["kind"] == "bounce")
    assert tr["status"] == "open" and tr["filledQty"] >= 1
    await rig.svc.armer.disarm(run["id"])


async def test_scorecard_after_close(rig):
    run = await _plan_run(rig)
    armed, bars, b1, i, _bt = await _open_a_share_trade(rig, run)
    day = dt.datetime.fromtimestamp(bars[0].ts / 1000, ET).date()
    close_bar = Bar(symbol="TEST", tf="1m", ts=_ms(day, 15, 59), open=b1["entry"], high=b1["entry"],
                    low=b1["entry"], close=b1["entry"], volume=1)
    await _quote(rig, b1["entry"])
    await rig.svc.armer.on_bar(run["id"], close_bar)
    hist = (await rig.client.get("/api/technique/armed/history")).json()
    row = next(h for h in hist if h["runId"] == run["id"])
    sc = row["state"].get("scorecard")
    assert sc and "rows" in sc and sc["symbol"] == "TEST" and "actualFires" in sc
    events = (await rig.client.get("/api/events", params={"aggregate_id": run["id"]})).json()
    assert any(e["type"] == "TechniquePlanScored" for e in events)


async def test_preflight_reports_the_risk_verdict(rig):
    run = await _plan_run(rig)
    pf = (await rig.client.post(f"/api/technique/runs/{run['id']}/arm/preflight",
                                json={"mode": "auto", "instrument": "shares", "portfolioId": rig.sim["id"],
                                      "riskPct": 1.0, "maxQty": 50})).json()
    assert pf["ok"] is True and pf["instrument"] == "shares" and pf["size"]["shares"] >= 1
    assert any(c["name"] == "kill_switch" for c in pf["checks"])
    await rig.eng.settings.set("risk.max_position_notional", 10.0, journal=False)
    pf2 = (await rig.client.post(f"/api/technique/runs/{run['id']}/arm/preflight",
                                 json={"mode": "auto", "instrument": "shares", "portfolioId": rig.sim["id"],
                                       "qty": 50})).json()
    assert pf2["ok"] is False
    await rig.eng.settings.set("risk.max_position_notional", 1_000_000.0, journal=False)


async def test_managed_proposal_is_adopted_and_managed(rig):
    """adopt_order takes an approved position and manages its exits (the same path
    the proposal-approval flow uses). The signals/proposals layer isn't attached in
    this rig, so we drive adopt_order directly with a real order."""
    from zargar.orders import OrderIntent
    run = await _plan_run(rig)
    armed = (await rig.client.post(f"/api/technique/runs/{run['id']}/arm",
                                   json={"mode": "alert", "portfolioId": rig.sim["id"]})).json()
    b1 = next(t for t in armed["triggers"] if t["kind"] == "bounce")
    entry, stop, targets = b1["entry"], b1["stop"], b1["targets"]
    # place a real BUY (limit above entry so a quote at entry fills it) and adopt it
    # BEFORE the fill, so the fill routes through the armer's order index
    limit = round(entry * 1.01, 2)
    order = await rig.eng.orders.place(OrderIntent(portfolio_id=rig.sim["id"], symbol="TEST", side="BUY",
                                                   qty=10, order_type="LMT", limit_price=limit, source="technique"))
    ok = await rig.svc.armer.adopt_order(run["id"], key="proposal:test1234",
                                         underlying={"entry": entry, "stop": stop,
                                                     "targets": [{"price": p} for p in targets]},
                                         order=order, instrument="shares")
    assert ok
    await _quote(rig, entry)
    def _pt():
        d = rig.svc.armer.detail(run["id"]) or {}
        return next((t for t in d.get("trades", []) if t["triggerId"] == "proposal:test1234"), {})
    await wait_for(lambda: _pt().get("status") == "open", timeout=5)
    # a stop bar closes the adopted position via the shared reduce-only exit
    day = dt.datetime.fromtimestamp(rig.sessions[armed["planFor"]][0].ts / 1000, ET).date()
    stop_bar = Bar(symbol="TEST", tf="1m", ts=_ms(day, 10, 0), open=entry, high=entry, low=stop - 0.05,
                   close=stop - 0.02, volume=1000)
    await _quote(rig, stop - 0.02)
    await rig.svc.armer.on_bar(run["id"], stop_bar)
    await _quote(rig, stop - 0.02)
    await wait_for(lambda: _pt().get("status") == "closed", timeout=5)
    assert _pt()["exits"][-1]["kind"] == "stop"
