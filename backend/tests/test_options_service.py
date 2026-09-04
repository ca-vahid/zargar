"""OptionsService + routes on the sim engine with a stubbed CBOE chain.

Covers: expiries/ladder/contract snapshots, contract quotes published from the
chain (sim feed owns them) and the overlay on live quotes, option orders in
practice end-to-end through the risk gate to a simulated fill, derived
open/close actions, the new option risk checks, expiry settlement, and the
REST surface (no SnapTrade configured -> impact is 503, capabilities empty).
"""
import datetime as dt
import json

import httpx
import pytest

from zargar.api.app import create_app
from zargar.domain import Quote
from zargar.engine import Engine
from zargar.options.chain import CboeClient
from zargar.orders import OrderIntent, derive_option_action

from .conftest import make_test_config, wait_for

TODAY = dt.date.today()
EXP1 = (TODAY + dt.timedelta(days=(4 - TODAY.weekday()) % 7 or 7)).isoformat()   # next Friday-ish
EXP2 = (dt.date.fromisoformat(EXP1) + dt.timedelta(days=7)).isoformat()


def _occ(root, exp, cp, strike):
    d = dt.date.fromisoformat(exp)
    return f"{root}{d:%y%m%d}{cp}{int(round(strike * 1000)):08d}"


def _row(sym, bid, ask, last=None, vol=500, oi=2000, delta=0.5, iv=0.2):
    return {"option": sym, "bid": bid, "ask": ask, "last_trade_price": last if last is not None else (bid + ask) / 2,
            "volume": vol, "open_interest": oi, "delta": delta, "gamma": 0.05,
            "theta": -0.03, "vega": 0.1, "iv": iv}


def cboe_payload(spot=100.0):
    return {"data": {
        "current_price": spot, "close": spot - 0.5, "prev_day_close": spot - 1.0, "iv30": 0.22,
        "options": [
            _row(_occ("XYZ", EXP1, "C", 100), 2.00, 2.10),
            _row(_occ("XYZ", EXP1, "C", 105), 0.50, 0.60, vol=20, oi=50),
            _row(_occ("XYZ", EXP1, "P", 100), 1.90, 2.00, delta=-0.5),
            _row(_occ("XYZ", EXP1, "P", 95), 0.40, 0.44, delta=-0.25),
            _row(_occ("XYZ", EXP2, "C", 100), 3.00, 3.20),
            _row(_occ("XYZ", EXP1, "C", 110), 0.02, 0.20, vol=0, oi=5),   # wide spread
            # an already-expired contract (yesterday) for the settlement test
            _row(_occ("XYZ", (TODAY - dt.timedelta(days=1)).isoformat(), "C", 90), 9.9, 10.1),
        ],
    }}


def make_cboe(payload=None) -> CboeClient:
    payload = payload or cboe_payload()

    def handler(request: httpx.Request) -> httpx.Response:
        sym = request.url.path.rsplit("/", 1)[-1].replace(".json", "")
        if sym != "XYZ":
            return httpx.Response(404, json={})
        return httpx.Response(200, json=payload)
    return CboeClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.fixture
async def opt_engine(fresh_db):
    config = make_test_config()
    eng = Engine(config)
    await eng.start()
    eng.options.use_client(make_cboe())
    app = create_app(config, eng)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield eng, client
    await eng.stop()


def sim_pid(eng: Engine) -> str:
    return next(p["id"] for p in eng.positions.portfolios() if p["kind"] == "sim")


# --- chain API -------------------------------------------------------------------

async def test_expiries_and_chain_ladder(opt_engine):
    eng, client = opt_engine
    r = await client.get("/api/options/XYZ/expiries")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["underlying"] == "XYZ" and body["spot"] == 100.0 and body["delayed"] is True
    dates = [e["date"] for e in body["expiries"]]
    assert dates == sorted(dates) and EXP1 in dates and EXP2 in dates
    assert all(e["dte"] >= 0 for e in body["expiries"])   # expired contract filtered out

    r = await client.get(f"/api/options/XYZ/chain?expiry={EXP1}")
    assert r.status_code == 200, r.text
    chain = r.json()
    strikes = [row["strike"] for row in chain["rows"]]
    assert strikes == [95.0, 100.0, 105.0, 110.0]
    atm = next(row for row in chain["rows"] if row["strike"] == 100.0)
    assert atm["call"]["bid"] == 2.0 and atm["call"]["ask"] == 2.1
    assert atm["call"]["delta"] == 0.5 and atm["call"]["iv"] == 0.2
    assert atm["put"]["delta"] == -0.5
    assert atm["call"]["inTheMoney"] is False          # spot == strike
    itm_put = next(row for row in chain["rows"] if row["strike"] == 105.0)
    assert itm_put["call"]["inTheMoney"] is False and itm_put["put"] is None
    wide = next(row for row in chain["rows"] if row["strike"] == 110.0)["call"]
    assert wide["spreadPct"] > 100

    r = await client.get("/api/options/NOPE/expiries")
    assert r.status_code == 404


async def test_contract_quote_is_published_and_overlaid(opt_engine):
    eng, client = opt_engine
    sym = _occ("XYZ", EXP1, "C", 100)
    r = await client.get(f"/api/options/quote/{sym}")
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["symbol"] == sym and c["available"] is True
    assert c["underlying"] == "XYZ" and c["strike"] == 100.0 and c["right"] == "C"
    assert c["display"].startswith("XYZ ") and c["multiplier"] == 100
    # the sim feed owns option quotes: the service published one from the chain
    q = eng.quotes.get(sym)
    assert q is not None and q.bid == 2.0 and q.ask == 2.1 and q.last > 0
    assert sym in eng.options.tracked
    # a live-feed quote for the same symbol keeps the chain's bid/ask (overlay)
    eng.quotes.on_quote(Quote(symbol=sym, bid=1.0, ask=9.0, last=2.07))
    q2 = eng.quotes.get(sym)
    assert (q2.bid, q2.ask, q2.last) == (2.0, 2.1, 2.07)
    # 2026-09-02 GOOGL 0DTE: the live tape printed far past the delayed chain's
    # band (chain last 2.05) -> the band re-centres on the print, same width
    eng.quotes.on_quote(Quote(symbol=sym, bid=1.0, ask=9.0, last=3.0))
    q3 = eng.quotes.get(sym)
    assert (q3.bid, q3.ask, q3.last) == (2.95, 3.05, 3.0)
    # a refreshed chain band (still delayed) re-applies to the stored quote the same way
    eng.quotes.set_overlay(sym, bid=2.2, ask=2.3, bid_size=0, ask_size=0, anchor_last=2.25)
    q4 = eng.quotes.get(sym)
    assert (q4.bid, q4.ask) == (2.95, 3.05)
    # the chain catches up (its last == the live print): the chain band stands
    eng.quotes.set_overlay(sym, bid=2.9, ask=3.1, bid_size=0, ask_size=0, anchor_last=3.0)
    q5 = eng.quotes.get(sym)
    assert (q5.bid, q5.ask) == (2.9, 3.1)

    r = await client.get("/api/options/quote/AAPL")
    assert r.status_code == 400


def make_alpaca_opra(quotes: dict, trades: dict | None = None, *, status: int = 200,
                     snapshots: dict | None = None):
    """A stubbed OPRA latest-quotes/trades pair (`AlpacaOptionsData` over MockTransport)."""
    from zargar.options.chain import AlpacaOptionsData

    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, json={"message": "forbidden"})
        if request.url.path.endswith("/quotes/latest"):
            return httpx.Response(200, json={"quotes": quotes})
        if request.url.path.endswith("/trades/latest"):
            return httpx.Response(200, json={"trades": trades or {}})
        if request.url.path.endswith("/options/snapshots"):
            return httpx.Response(200, json={"snapshots": snapshots or {}})
        return httpx.Response(404, json={})
    return AlpacaOptionsData("k", "s", httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://data.alpaca.markets"))


async def test_tracked_contract_quotes_come_from_opra_not_the_delayed_chain(opt_engine):
    """2026-09-02: every practice fill / premium stop / risk check ran on CBOE's
    ~15-min-delayed row (GOOGL 340C 'bought' at 0.13 in a 0.60 market). With
    the Alpaca keys present the tracked contract's bid/ask/last come from OPRA
    each refresh, badged live; a refusal backs off to the chain row."""
    eng, client = opt_engine
    sym = _occ("XYZ", EXP1, "C", 100)
    eng.options.use_quote_source(make_alpaca_opra(
        {sym: {"bp": 2.5, "ap": 2.6, "bs": 12, "as": 7, "t": "2026-09-02T17:10:34.713648101Z"}},
        {sym: {"p": 2.55, "s": 3, "t": "2026-09-02T17:10:33.1Z"}}))
    await eng.options.track(sym)
    q = eng.quotes.get(sym)
    assert (q.bid, q.ask, q.last, q.bid_size, q.ask_size) == (2.5, 2.6, 2.55, 12, 7)   # not CBOE's 2.0/2.1
    assert eng.options.served_live(sym)
    r = await client.get(f"/api/options/quote/{sym}")
    body = r.json()
    assert body["provider"] == "alpaca" and body["delayed"] is False
    assert body["bid"] == 2.5 and body["ask"] == 2.6
    # a Yahoo `last`-only print between passes keeps the OPRA band (overlay)
    eng.quotes.on_quote(Quote(symbol=sym, bid=0.0, ask=0.0, last=2.56))
    q2 = eng.quotes.get(sym)
    assert (q2.bid, q2.ask, q2.last) == (2.5, 2.6, 2.56)
    # OPRA refused (subscription lapsed): the chain row serves, badged delayed
    eng.options.use_quote_source(make_alpaca_opra({}, status=403))
    await eng.options.refresh_tracked()
    assert not eng.options.served_live(sym)
    q3 = eng.quotes.get(sym)
    # on the sim feed the service OWNS the quote, so the chain row is published
    # whole (2.0/2.1, last 2.05); on a live feed the band would re-centre on the
    # last real print instead (covered by the overlay test above)
    assert (q3.bid, q3.ask, q3.last) == (2.0, 2.1, 2.05)
    assert (await client.get(f"/api/options/quote/{sym}")).json()["delayed"] is True


async def test_gate_fails_closed_on_a_delayed_quote_when_a_live_source_is_configured(opt_engine):
    """The audit's #1: `ts` is re-stamped on every chain refresh, so quote_fresh
    called a 15-min-old ask '4.8 s old'. Quotes now carry their source; with
    OPRA configured, a chain-sourced option quote fails quote_fresh for entries
    (exits are reduce-only and never read it). Sim/tests without a live source
    keep the old behaviour, labelled."""
    eng, client = opt_engine
    pid = sim_pid(eng)
    sym = _occ("XYZ", EXP1, "C", 100)
    # no live source configured (test default): chain quote accepted, labelled delayed
    await eng.options.track(sym)
    q = eng.quotes.get(sym)
    assert q.source == "chain" and q.delayed and eng.quotes.source_age_seconds(sym) > 800
    r = await client.post("/api/orders", json={"portfolio_id": pid, "symbol": sym, "sec_type": "OPT",
                                               "side": "BUY", "qty": 1, "order_type": "MKT", "dry_run": True})
    fresh = next(c for c in r.json()["risk"]["checks"] if c["name"] == "quote_fresh")
    assert fresh["passed"] and "delayed chain" in fresh["detail"]
    # a live source is configured but refuses (outage / lapsed subscription): fail CLOSED
    eng.options.use_quote_source(make_alpaca_opra({}, status=403))
    eng.risk.live_option_quotes_expected = lambda: True
    await eng.options.refresh_tracked()
    r = await client.post("/api/orders", json={"portfolio_id": pid, "symbol": sym, "sec_type": "OPT",
                                               "side": "BUY", "qty": 1, "order_type": "MKT", "dry_run": True})
    fresh = next(c for c in r.json()["risk"]["checks"] if c["name"] == "quote_fresh")
    assert not fresh["passed"] and "real-time source configured" in fresh["detail"]
    # OPRA serving again: the quote is live and the gate passes on it
    eng.options._alpaca_down_until = 0.0
    eng.options.use_quote_source(make_alpaca_opra(
        {sym: {"bp": 2.5, "ap": 2.6, "bs": 1, "as": 1, "t": "2026-09-02T17:10:34.7Z"}}))
    await eng.options.refresh_tracked()
    q = eng.quotes.get(sym)
    assert q.source == "opra" and not q.delayed
    r = await client.post("/api/orders", json={"portfolio_id": pid, "symbol": sym, "sec_type": "OPT",
                                               "side": "BUY", "qty": 1, "order_type": "MKT", "dry_run": True})
    fresh = next(c for c in r.json()["risk"]["checks"] if c["name"] == "quote_fresh")
    assert fresh["passed"] and "delayed" not in fresh["detail"]


async def test_reprice_moves_a_picked_contract_onto_the_live_nbbo(opt_engine):
    """Sizing / entry limit / never-chase read the PICK's bid/ask — the chain's
    delayed row ($1,500 / 0.13 = 115 contracts on 2026-09-02). reprice() after
    track() puts the real-time NBBO on the dict; without a live source the dict
    is left as picked and labelled."""
    eng, client = opt_engine
    sym = _occ("XYZ", EXP1, "C", 100)
    pick = {"symbol": sym, "bid": 2.0, "ask": 2.1, "mid": 2.05, "spreadPct": 4.88}
    out = await eng.options.reprice(dict(pick))
    assert out["priced"] == "chain" and out["ask"] == 2.1
    eng.options.use_quote_source(make_alpaca_opra(
        {sym: {"bp": 2.5, "ap": 2.6, "bs": 1, "as": 1, "t": "2026-09-02T17:10:34.7Z"}}))
    out = await eng.options.reprice(dict(pick))
    assert out["priced"] == "opra" and (out["bid"], out["ask"], out["mid"]) == (2.5, 2.6, 2.55)
    assert abs(out["spreadPct"] - 3.92) < 0.01


async def test_live_greeks_merge_onto_the_tracked_snapshot(opt_engine):
    """Phase 2: delta/IV for tracked contracts come from Alpaca's real-time
    snapshots (the roll-up trigger + monetize IV-tighten read them); the chain
    row keeps supplying what Alpaca omits (open interest)."""
    eng, client = opt_engine
    sym = _occ("XYZ", EXP1, "C", 100)
    await eng.options.track(sym)
    before = eng.options.snapshot_cached(sym)
    assert before and before["greeks"]["delta"] == 0.5 and int(before["open_interest"]) == 2000
    eng.options.use_quote_source(make_alpaca_opra(
        {sym: {"bp": 2.5, "ap": 2.6, "bs": 1, "as": 1, "t": "2026-09-02T17:10:34.7Z"}},
        snapshots={sym: {"greeks": {"delta": 0.61, "gamma": 0.03, "theta": -0.05, "vega": 0.08},
                         "impliedVolatility": 0.44}}))
    await eng.options.refresh_tracked()                  # greeks fetch fires on pass 1
    snap = eng.options.snapshot_cached(sym)
    assert snap["greeks"]["delta"] == 0.61 and snap["greeks"]["mid_iv"] == 0.44
    assert snap.get("greeksLive") is True
    assert int(snap["open_interest"]) == 2000            # OI still the chain's


async def test_quiet_feed_republishes_the_chain_quote(opt_engine, monkeypatch):
    """2026-09-02: on the live feed a thin contract (Monday expiry, no Yahoo
    prints) got ONE published quote at track() time and nothing after — the
    sim executor never saw a post-latency print and the research book's market
    orders sat 2 h. When the feed has gone quiet the refresh must publish the
    chain quote; while the feed is printing, only the overlay is applied."""
    from zargar.options import service as svc
    eng, client = opt_engine
    sym = _occ("XYZ", EXP1, "C", 100)
    await eng.options.track(sym)
    eng.options._owns_quotes = False                    # behave like the live feed
    seen: list[Quote] = []
    orig = eng.quotes.on_quote

    def spy(q):
        seen.append(q)
        orig(q)
    monkeypatch.setattr(eng.quotes, "on_quote", spy)
    # the feed printed a moment ago: refresh applies the overlay only
    orig(Quote(symbol=sym, bid=1.0, ask=9.0, last=2.05))
    seen.clear()
    await eng.options.refresh_tracked()
    assert not seen and eng.quotes.get(sym).ask == 2.1
    # the feed has gone quiet: the chain quote is published as a fresh print
    monkeypatch.setattr(svc, "FEED_QUIET_SECONDS", -1.0)
    await eng.options.refresh_tracked()
    assert len(seen) == 1 and seen[0].symbol == sym and seen[0].ask == 2.1
    assert eng.quotes.age_seconds(sym) < 5


# --- trading in practice --------------------------------------------------------------

async def test_derive_option_action_table():
    assert derive_option_action("BUY", 0, 1) == "BUY_TO_OPEN"
    assert derive_option_action("BUY", 2, 1) == "BUY_TO_OPEN"
    assert derive_option_action("BUY", -2, 1) == "BUY_TO_CLOSE"
    assert derive_option_action("SELL", 2, 1) == "SELL_TO_CLOSE"
    assert derive_option_action("SELL", 0, 1) == "SELL_TO_OPEN"


async def test_option_order_practice_roundtrip(opt_engine):
    eng, client = opt_engine
    pid = sim_pid(eng)
    sym = _occ("XYZ", EXP1, "C", 100)

    # dry run first: option checks present, action derived, nothing routed
    r = await client.post("/api/orders", json={
        "portfolio_id": pid, "symbol": sym.lower(), "sec_type": "OPT", "side": "BUY",
        "qty": 2, "order_type": "LMT", "limit_price": 2.1, "dry_run": True})
    assert r.status_code == 200, r.text
    dry = r.json()
    assert dry["status"] == "DRY_RUN" and dry["optionAction"] == "BUY_TO_OPEN"
    names = {c["name"] for c in dry["risk"]["checks"]}
    assert {"options_allowed", "option_premium_cap", "no_naked_short_option",
            "option_symbol", "option_not_expired", "option_max_contracts",
            "option_premium_notional", "option_spread"} <= names
    assert dry["option"]["strike"] == 100.0 and dry["symbol"] == sym

    # real practice order fills on the simulator against the chain quote
    r = await client.post("/api/orders", json={
        "portfolio_id": pid, "symbol": sym, "sec_type": "OPT", "side": "BUY",
        "qty": 2, "order_type": "MKT"})
    assert r.status_code == 200, r.text
    order = r.json()
    assert order["status"] == "SUBMITTED", order
    await eng.options.refresh_tracked()   # re-publish the chain quote -> sim fill

    async def filled():
        rows = await eng.orders.list_orders(pid)
        return any(o["id"] == order["id"] and o["status"] == "FILLED" for o in rows)
    await wait_for(filled)
    assert eng.positions.position_qty(pid, sym, "OPT") == 2
    pos = next(p for p in eng.positions.positions_list(pid) if p["symbol"] == sym)
    assert pos["secType"] == "OPT" and pos["option"]["underlying"] == "XYZ"
    assert pos["currency"] == "USD"
    # 2 contracts x ~2.1 x 100 = ~$420 left the cash balance (+ commission)
    cash = eng.positions.portfolio(pid)["cash"]
    assert 10_000 - cash > 400

    # closing more than held is refused outright; closing what we hold derives SELL_TO_CLOSE
    r = await client.post("/api/orders", json={
        "portfolio_id": pid, "symbol": sym, "sec_type": "OPT", "side": "SELL",
        "qty": 3, "order_type": "MKT", "dry_run": True})
    assert r.status_code == 400 and "only 2" in r.json()["detail"]
    r = await client.post("/api/orders", json={
        "portfolio_id": pid, "symbol": sym, "sec_type": "OPT", "side": "SELL",
        "qty": 2, "order_type": "LMT", "limit_price": 2.0, "dry_run": True})
    assert r.json()["optionAction"] == "SELL_TO_CLOSE"


async def test_option_risk_checks_block_bad_orders(opt_engine):
    eng, client = opt_engine
    pid = sim_pid(eng)
    wide = _occ("XYZ", EXP1, "C", 110)
    r = await client.post("/api/orders", json={
        "portfolio_id": pid, "symbol": wide, "sec_type": "OPT", "side": "BUY",
        "qty": 1, "order_type": "MKT", "dry_run": True})
    body = r.json()
    assert body["status"] == "REJECTED_RISK"
    failed = {c["name"] for c in body["risk"]["checks"] if not c["passed"]}
    assert "option_spread" in failed

    # too many contracts
    sym = _occ("XYZ", EXP1, "C", 105)
    r = await client.post("/api/orders", json={
        "portfolio_id": pid, "symbol": sym, "sec_type": "OPT", "side": "BUY",
        "qty": 11, "order_type": "LMT", "limit_price": 0.6, "dry_run": True})
    failed = {c["name"] for c in r.json()["risk"]["checks"] if not c["passed"]}
    assert "option_max_contracts" in failed

    # expired contract
    old = _occ("XYZ", (TODAY - dt.timedelta(days=1)).isoformat(), "C", 90)
    r = await client.post("/api/orders", json={
        "portfolio_id": pid, "symbol": old, "sec_type": "OPT", "side": "BUY",
        "qty": 1, "order_type": "LMT", "limit_price": 10.0, "dry_run": True})
    failed = {c["name"] for c in r.json()["risk"]["checks"] if not c["passed"]}
    assert "option_not_expired" in failed

    # naked short still blocked; a non-OCC symbol with sec_type OPT is a 400
    r = await client.post("/api/orders", json={
        "portfolio_id": pid, "symbol": sym, "sec_type": "OPT", "side": "SELL",
        "qty": 1, "order_type": "LMT", "limit_price": 0.6, "dry_run": True})
    failed = {c["name"] for c in r.json()["risk"]["checks"] if not c["passed"]}
    assert "no_naked_short_option" in failed
    r = await client.post("/api/orders", json={
        "portfolio_id": pid, "symbol": "AAPL", "sec_type": "OPT", "side": "BUY",
        "qty": 1, "order_type": "MKT", "dry_run": True})
    assert r.status_code == 400


async def test_expired_practice_position_settles_at_intrinsic(opt_engine):
    eng, client = opt_engine
    pid = sim_pid(eng)
    old = _occ("XYZ", (TODAY - dt.timedelta(days=1)).isoformat(), "C", 90)
    await eng.positions.apply_fill(pid, old, "OPT", "BUY", 1, 5.0, 0.0)
    assert eng.positions.position_qty(pid, old, "OPT") == 1
    settled = await eng.options.settle_expired()
    assert len(settled) == 1
    rec = settled[0]
    assert rec["symbol"] == old and rec["intrinsic"] == 10.0   # spot 100 - strike 90
    assert eng.positions.position_qty(pid, old, "OPT") == 0
    pos = next(p for p in eng.positions.positions_list(pid) if p["symbol"] == old)
    assert pos["realizedPnl"] == pytest.approx((10.0 - 5.0) * 100)
    r = await client.get("/api/events?type=OptionExpired")
    assert r.status_code == 200
    assert any(e["type"] == "OptionExpired" for e in r.json())
    # the settlement is a TRADE: a FILLED source="settle" order + execution row
    # exist, so the Ledger sees the exit and the cash identity holds
    # (audit 2026-09-04: META 590C settled +$5,985 with no execution row)
    rows = await eng.orders.list_orders(pid)
    st = next(o for o in rows if o["source"] == "settle" and o["symbol"] == old)
    assert st["status"] == "FILLED" and st["side"] == "SELL" and st["avgFillPrice"] == 10.0
    from sqlalchemy import select
    from zargar.models import Execution
    async with eng.sf() as session:
        ex = (await session.execute(select(Execution).where(
            Execution.order_id == st["id"]))).scalars().all()
    assert len(ex) == 1 and ex[0].qty == 1 and ex[0].price == 10.0 and ex[0].commission == 0.0


async def test_routes_without_snaptrade(opt_engine):
    eng, client = opt_engine
    r = await client.get("/api/options/capabilities")
    assert r.status_code == 200 and r.json() == {"accounts": []}
    r = await client.post("/api/options/impact", json={
        "portfolio_id": sim_pid(eng), "symbol": _occ("XYZ", EXP1, "C", 100),
        "side": "BUY", "qty": 1, "limit_price": 2.1})
    assert r.status_code == 503
    r = await client.get("/api/options/expiring?days=60")
    assert r.status_code == 200 and r.json() == []
