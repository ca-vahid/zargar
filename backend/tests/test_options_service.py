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

    r = await client.get("/api/options/quote/AAPL")
    assert r.status_code == 400


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
